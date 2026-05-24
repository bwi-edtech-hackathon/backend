"""Roadmap generator: rule-based ordering + optional Gemini enrichment.

Ranks topics by impact (weight * (1 - mastery_pct/100)), respects prerequisite
DAG, packs into weekly buckets up to the user's exam date (default 6 weeks).
When `GEMINI_API_KEY` is configured, `enrich_with_gemini()` annotates the plan
with a one-paragraph coach summary and a per-milestone `focus` note. Falls
back to the rule-based plan unchanged when Gemini is disabled or errors out.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from app.core.config import settings
from app.models.catalog import Subject, Topic
from app.models.exam import ExamAttempt
from app.models.progress import MasteryTopic

logger = logging.getLogger(__name__)

WEEKLY_MINUTES_BUDGET = 240  # 4 hours/week default
DEFAULT_TOTAL_WEEKS = 6
EST_MINUTES_PER_TOPIC = 60


def _impact(topic: Topic, mastery_map: dict[uuid.UUID, float]) -> float:
    mastery = mastery_map.get(topic.id, 0.0)
    deficit = max(0.0, 1.0 - mastery / 100.0)
    return float(topic.weight) * deficit


def _topo_sort_by_impact(
    topics: Sequence[Topic], mastery_map: dict[uuid.UUID, float]
) -> list[Topic]:
    by_id = {t.id: t for t in topics}
    # Filter prerequisites to ones in our set; coerce string UUIDs from JSONB.
    prereqs: dict[uuid.UUID, set[uuid.UUID]] = {}
    for t in topics:
        deps: set[uuid.UUID] = set()
        for raw in t.prerequisites or []:
            try:
                pid = uuid.UUID(raw) if isinstance(raw, str) else uuid.UUID(str(raw))
                if pid in by_id:
                    deps.add(pid)
            except (ValueError, TypeError):
                continue
        prereqs[t.id] = deps

    visited: set[uuid.UUID] = set()
    out: list[Topic] = []

    # Greedy: at each step, pick the highest-impact topic whose prereqs are satisfied.
    remaining = list(topics)
    while remaining:
        ready = [t for t in remaining if prereqs[t.id].issubset(visited)]
        if not ready:
            # Break cycles by ignoring unsatisfied deps for highest-impact node
            ready = remaining
        next_topic = max(ready, key=lambda t: _impact(t, mastery_map))
        out.append(next_topic)
        visited.add(next_topic.id)
        remaining.remove(next_topic)
    return out


def _weeks_until(target: date | None, default: int = DEFAULT_TOTAL_WEEKS) -> int:
    if not target:
        return default
    delta = (target - date.today()).days
    return max(1, min(12, (delta // 7) + 1))


def generate_milestones(
    topics: Sequence[Topic],
    mastery_rows: Sequence[MasteryTopic],
    exam_date: date | None = None,
) -> list[dict]:
    """Return milestone list ready to store as JSONB on Roadmap.milestones."""
    mastery_map = {m.topic_id: float(m.mastery_pct) for m in mastery_rows}
    # Only target depth=2 topics (the main "Topics" level) for milestones
    main = [t for t in topics if t.depth == 2]
    ordered = _topo_sort_by_impact(main, mastery_map)
    total_weeks = _weeks_until(exam_date)
    per_week = max(1, len(ordered) // total_weeks)

    milestones: list[dict] = []
    for idx, topic in enumerate(ordered):
        mastery = mastery_map.get(topic.id, 0.0)
        if mastery >= 90:
            status = "mastered"
        elif mastery >= 50:
            status = "in_progress"
        elif idx == 0 or (idx > 0 and mastery_map.get(ordered[idx - 1].id, 0.0) >= 50):
            status = "active"
        else:
            status = "locked"
        week = min(total_weeks, (idx // per_week) + 1)
        # Default lane is computed from the topic's slot inside its week so the
        # rule-based plan still renders as a 2–3 lane constellation when Gemini
        # is disabled. Gemini overrides this in _resequence when it returns a
        # richer layout.
        milestones.append(
            {
                "topic_id": str(topic.id),
                "topic_slug": topic.slug,
                "topic_name_uz": topic.name_uz,
                "topic_name_en": topic.name_en,
                "order": idx,
                "status": status,
                "mastery_pct": round(mastery, 2),
                "est_minutes": EST_MINUTES_PER_TOPIC,
                "week_bucket": week,
                "lane": 0,
                "weight": float(topic.weight),
            }
        )
    _autolane(milestones)
    return milestones


def _autolane(milestones: list[dict], max_lanes: int = 3) -> None:
    """Deterministically spread same-week milestones across lanes 0..max_lanes-1
    so the rule-based path (and any Gemini fallback) still produces a branched
    constellation rather than a single stacked column."""
    cursor: dict[int, int] = {}
    for m in milestones:
        wk = int(m.get("week_bucket", 1))
        slot = cursor.get(wk, 0)
        m["lane"] = slot % max_lanes
        cursor[wk] = slot + 1


def generated_at_utc() -> datetime:
    return datetime.now(UTC)


# ─────────────────────── Gemini re-ordering ───────────────────────
# Gemini is used to suggest a smarter topic order than the rule-based topo
# sort — but the output shape is identical, so consumers (including the
# existing frontend Roadmap page) don't need to change. Falls back to the
# rule-based order when Gemini is disabled, slow, or returns garbage.

_GEMINI_ORDER_PROMPT = """You are a study coach for Uzbekistan's Milliy Sertifikat exam,
and you are also designing the VISUAL roadmap the student will see.

Subject: {subject}. The student has {weeks} weeks total: {study_weeks} weeks
to study, then 1 final week reserved for a mock exam and review.

Your job is to design a BRANCHED CONSTELLATION over those {study_weeks} study
weeks. Think of it as 2 or 3 parallel "spines" the student can advance on in
the same week — for example for Math: a "Algebra spine" (linear → quadratic
→ logarithms), a "Functions & analysis spine" (functions → sequences →
probability), and an optional "Geometry & trig spine" running alongside.
Spines should be COHERENT: each lane should tell a story (one theme, one
skill family), and they should converge as the exam approaches so the final
study week consolidates rather than fans out.

For every input topic you must return:
  • topic_id  — the exact string from the input list
  • week      — integer 1..{study_weeks} (when the student should study it)
  • lane      — integer 0, 1, or 2 (which spine the topic belongs to)

DESIGN RULES — apply ALL of them, do not optimize one in isolation:

1. IMPACT = weight × (1 − mastery / 100). High-impact topics deserve EARLY
   weeks so the student has more time to lift them. A 0.9-weight topic at
   30% mastery (impact 0.63) beats a 0.6-weight topic at 10% (impact 0.54).
2. PREREQUISITES come before dependents AND, ideally, sit on the SAME lane
   as their dependents so the spine reads as a clean progression. Typical
   math chains: Linear → Quadratic → Logarithms; Functions → Sequences →
   Probability; Trigonometry ↔ Geometry can share a lane. Even if a
   foundation has high mastery (e.g. Linear at 86%), keep it ahead of
   weaker dependents — a quick refresher is cheaper than re-learning.
3. PARALLELISM is the whole point. Each study week should have 2–3 topics
   active across DIFFERENT lanes, not stacked on the same lane. Avoid
   weeks where all topics sit on lane 0 — that defeats the constellation.
4. LANE COHERENCE > perfect impact ordering. It is better to keep a lane
   thematically consistent (all algebra together) than to greedily place
   the single highest-impact topic out of context.
5. CONVERGENCE near the exam. The final 1–2 study weeks should compress
   into fewer lanes (preferably 1–2) so the constellation visibly funnels
   toward the mock — a synthesis/review feel.
6. Already-mastered topics (>85%) can sit late on any lane — they only
   need brief review and shouldn't crowd the early high-impact slots.
7. RECENT MOCK EXAMS are ground truth: if a topic was weak on the latest
   mock, prioritise it EVEN IF long-run mastery looks acceptable.
8. LOAD BALANCING — aim for roughly equal topic counts per week. Do not
   pile 8 topics into week 1 and leave week 4 empty.

{mocks_block}Topics:
{plan_lines}

Return STRICT JSON only — no prose, no markdown fences — a single array of
objects, one per input topic. Every input topic_id MUST appear exactly
once. Example shape (NOT a recommendation, just format):
[
  {{"topic_id": "uuid-linear",      "week": 1, "lane": 0}},
  {{"topic_id": "uuid-functions",   "week": 1, "lane": 1}},
  {{"topic_id": "uuid-trig-basics", "week": 1, "lane": 2}},
  {{"topic_id": "uuid-quadratic",   "week": 2, "lane": 0}},
  {{"topic_id": "uuid-sequences",   "week": 2, "lane": 1}},
  ...
  {{"topic_id": "uuid-review",      "week": {study_weeks}, "lane": 0}}
]"""


def _format_mocks_block(
    recent_mocks: Sequence[ExamAttempt],
    topic_names: dict[uuid.UUID, str],
) -> str:
    """Render the last few graded mocks as a Gemini-readable block, newest
    first. Returns an empty string when there are no mocks so the prompt
    template just collapses naturally."""
    if not recent_mocks:
        return ""
    rows: list[str] = []
    for idx, attempt in enumerate(recent_mocks):
        submitted = attempt.submitted_at or attempt.started_at
        when = submitted.strftime("%Y-%m-%d") if submitted else "unknown"
        score = (
            f"{float(attempt.rasch_score):.1f}"
            if attempt.rasch_score is not None
            else "—"
        )
        grade = attempt.grade.value if attempt.grade else "—"
        # Pick the weakest topics from this attempt's per-topic breakdown.
        breakdown = attempt.topic_breakdown or {}
        weak_entries: list[tuple[str, float]] = []
        for tid_str, slot in breakdown.items():
            if not isinstance(slot, dict):
                continue
            if int(slot.get("total", 0) or 0) < 2:
                continue
            try:
                tid = uuid.UUID(tid_str)
            except (ValueError, TypeError):
                continue
            name = topic_names.get(tid)
            if not name:
                continue
            weak_entries.append((name, float(slot.get("pct", 0.0) or 0.0)))
        weak_entries.sort(key=lambda x: x[1])
        weak_str = (
            ", ".join(f"{n} ({p:.0f}%)" for n, p in weak_entries[:5])
            or "no per-topic data"
        )
        label = "latest" if idx == 0 else f"prior #{idx}"
        rows.append(
            f"  • {label} mock — {when} — Rasch {score}/75, grade {grade}; "
            f"weakest topics: {weak_str}"
        )
    return "Recent mock exams (newest first):\n" + "\n".join(rows) + "\n\n"


def _build_order_prompt(
    subject_name: str,
    weeks_total: int,
    study_weeks: int,
    milestones: list[dict],
    mocks_block: str = "",
) -> str:
    lines = [
        f"- {m['topic_name_en']} (topic_id={m['topic_id']}, "
        f"mastery={m['mastery_pct']}%, weight={m['weight']:.2f}, "
        f"impact={m['weight'] * (1 - m['mastery_pct'] / 100):.3f})"
        for m in milestones
    ]
    return _GEMINI_ORDER_PROMPT.format(
        subject=subject_name,
        weeks=weeks_total,
        study_weeks=study_weeks,
        plan_lines="\n".join(lines),
        mocks_block=mocks_block,
    )


_JSON_BLOCK = re.compile(r"\[[\s\S]*\]")


def _extract_layout(text: str) -> list[dict] | None:
    """Parse Gemini's response into a list of `{topic_id, week, lane}` dicts.

    Accepts both the new branched shape (objects with week/lane) and the
    legacy plain-string id list — older prompts or partial responses fall
    back gracefully to "order only, no layout"."""
    if not text:
        return None
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None

    out: list[dict] = []
    for item in data:
        if isinstance(item, str):
            out.append({"topic_id": item})
        elif isinstance(item, dict):
            tid = item.get("topic_id")
            if not isinstance(tid, str):
                continue
            entry: dict = {"topic_id": tid}
            if isinstance(item.get("week"), int):
                entry["week"] = item["week"]
            if isinstance(item.get("lane"), int):
                entry["lane"] = item["lane"]
            out.append(entry)
    return out or None


async def _call_gemini(prompt: str) -> str:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(model_name=settings.gemini_model)
    response = await asyncio.to_thread(model.generate_content, prompt)
    return (getattr(response, "text", "") or "").strip()


def _resequence(
    milestones: list[dict], layout: list[dict], total_weeks: int
) -> list[dict]:
    """Apply Gemini's branched layout to the existing milestones, recomputing
    `order`, `week_bucket`, `lane`, and `status` while preserving every other
    field. Topics not mentioned by Gemini are appended at the end and
    auto-distributed across lanes so they still render as a branch.

    The last week is reserved for the final mock + exam, so all topics are
    packed into weeks 1 .. max(1, total_weeks - 1). When total_weeks == 1 we
    fall back to placing everything in week 1 (no buffer is possible)."""
    by_id = {m["topic_id"]: m for m in milestones}
    seen: set[str] = set()
    ordered: list[dict] = []
    for entry in layout:
        tid = entry.get("topic_id")
        m = by_id.get(tid) if isinstance(tid, str) else None
        if m and tid not in seen:
            # Stash Gemini's suggested week/lane on the milestone so the
            # second pass below can clamp them into the legal range.
            if "week" in entry:
                m["_gemini_week"] = entry["week"]
            if "lane" in entry:
                m["_gemini_lane"] = entry["lane"]
            ordered.append(m)
            seen.add(tid)
    for m in milestones:
        if m["topic_id"] not in seen:
            ordered.append(m)

    study_weeks = max(1, total_weeks - 1) if total_weeks > 1 else 1
    max_lanes = 3

    # Pass 1: honor Gemini's week/lane when present and in range; otherwise
    # fall back to a uniform per-week packing for unannotated topics.
    per_week = max(1, len(ordered) // study_weeks)
    for idx, m in enumerate(ordered):
        m["order"] = idx
        gw = m.pop("_gemini_week", None)
        if isinstance(gw, int) and 1 <= gw <= study_weeks:
            m["week_bucket"] = gw
        else:
            m["week_bucket"] = min(study_weeks, (idx // per_week) + 1)
        gl = m.pop("_gemini_lane", None)
        if isinstance(gl, int) and 0 <= gl < max_lanes:
            m["lane"] = gl
        else:
            m["lane"] = -1  # marker — fill in pass 2

    # Pass 2: any lane Gemini didn't assign gets the least-loaded lane for
    # that week, so the constellation stays balanced even on partial output.
    lane_counts: dict[tuple[int, int], int] = {}
    for m in ordered:
        if m["lane"] >= 0:
            key = (m["week_bucket"], m["lane"])
            lane_counts[key] = lane_counts.get(key, 0) + 1
    for m in ordered:
        if m["lane"] < 0:
            wk = m["week_bucket"]
            # Pick the lane in this week with the fewest topics so far.
            best_lane = min(
                range(max_lanes),
                key=lambda ln: lane_counts.get((wk, ln), 0),
            )
            m["lane"] = best_lane
            lane_counts[(wk, best_lane)] = lane_counts.get((wk, best_lane), 0) + 1

    _assign_statuses(ordered)
    return ordered


def _assign_statuses(ordered: list[dict]) -> None:
    """Recompute status using the same thresholds as generate_milestones, but
    against the new sequence — so "active" sits on the first not-yet-mastered
    topic and "locked" cascades from there."""
    unlocked = True
    for idx, m in enumerate(ordered):
        mastery = float(m.get("mastery_pct", 0.0))
        if mastery >= 90:
            m["status"] = "mastered"
            continue
        if mastery >= 50:
            m["status"] = "in_progress"
            unlocked = True  # high mastery on a topic unlocks the next one
            continue
        if idx == 0 or unlocked:
            m["status"] = "active"
            unlocked = False  # next low-mastery topic is locked until this one progresses
        else:
            m["status"] = "locked"


async def enrich_with_gemini(
    milestones: list[dict],
    subject: Subject,
    exam_date: date | None = None,
    timeout_seconds: float = 25.0,
    recent_mocks: Sequence[ExamAttempt] | None = None,
    topic_names: dict[uuid.UUID, str] | None = None,
) -> list[dict]:
    """Re-order milestones using Gemini. Returns the input unchanged when
    Gemini is disabled, the call fails/times out, or the response can't be
    parsed — but in every case still packs topics into weeks 1..N-1 so the
    last week stays reserved for the exam.

    `recent_mocks` (newest first) and `topic_names` are optional — when
    provided, the prompt includes a short summary of those attempts so the
    re-ordering reflects current exam-day weak spots, not just long-run
    mastery aggregates."""
    if not milestones:
        return milestones

    weeks_total = max((m.get("week_bucket", 1) for m in milestones), default=1)
    # Fallback "layout" preserves the rule-based order/week/lane already on
    # each milestone so a Gemini outage doesn't collapse the constellation.
    fallback_layout = [
        {
            "topic_id": m["topic_id"],
            "week": int(m.get("week_bucket", 1)),
            "lane": int(m.get("lane", 0)),
        }
        for m in milestones
    ]

    if not settings.gemini_enabled:
        return _resequence(milestones, fallback_layout, weeks_total)

    study_weeks = max(1, weeks_total - 1) if weeks_total > 1 else 1
    mocks_block = _format_mocks_block(recent_mocks or [], topic_names or {})
    prompt = _build_order_prompt(
        subject.name_en, weeks_total, study_weeks, milestones, mocks_block
    )

    try:
        raw = await asyncio.wait_for(_call_gemini(prompt), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning("Gemini roadmap re-ordering timed out after %.1fs", timeout_seconds)
        return _resequence(milestones, fallback_layout, weeks_total)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini roadmap re-ordering failed: %s", exc)
        return _resequence(milestones, fallback_layout, weeks_total)

    layout = _extract_layout(raw) or fallback_layout
    return _resequence(milestones, layout, weeks_total)
