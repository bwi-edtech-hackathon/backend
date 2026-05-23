"""Rule-based roadmap generator.

Ranks topics by impact (weight * (1 - mastery_pct/100)), respects prerequisite
DAG, packs into weekly buckets up to the user's exam date (default 6 weeks).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

from app.models.catalog import Topic
from app.models.progress import MasteryTopic

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
                "weight": float(topic.weight),
            }
        )
    return milestones


def generated_at_utc() -> datetime:
    return datetime.now(UTC)
