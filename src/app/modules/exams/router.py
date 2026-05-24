"""Exam routes — frontend-shaped, demo-mode friendly.

The frontend uses simple string subject codes ("MATH"), camelCase JSON, and
expects an async-style submit/result flow. We keep the DB-backed core (ExamAttempt
rows, ExamAnswer rows, real grading) but project it through camelCase schemas and
accept either a subject code or a UUID.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select

from app.core.deps import CurrentUser, DbSession
from app.core.slugs import short_slug
from app.models.catalog import Question, QuestionType, Subject, SubjectCode, Topic
from app.models.exam import ExamAnswer, ExamAttempt, ExamKind, ExamStatus, Grade
from app.models.formula import Formula, FormulaKind
from app.models.progress import MasteryTopic
from app.modules.exams.grader import estimate_rasch, grade_answer, grade_for_score

router = APIRouter(prefix="/api/v1", tags=["exams"])


# ════════════════════════════════════════════════════════════════════════════
# Frontend-shaped schemas (camelCase via aliases)
# ════════════════════════════════════════════════════════════════════════════

_FRONTEND_CONFIG = ConfigDict(populate_by_name=True, from_attributes=True)


class _CamelModel(BaseModel):
    model_config = _FRONTEND_CONFIG


class ExamQuestionOut(_CamelModel):
    """Mirrors frontend `ExamQuestion` in lib/api.ts."""

    id: str
    index: int
    section: str            # "A" | "B"
    type: str               # "closed" | "open_a" | "open_b"
    domain: str
    topic: str
    prompt: str
    options: list[dict] | None = None
    weight: float


class ExamSessionOut(_CamelModel):
    """Mirrors frontend `ExamSession` in lib/api.ts."""

    id: str
    slug: str
    subject: str
    started_at: int = Field(alias="startedAt")
    duration_ms: int = Field(alias="durationMs")
    questions: list[ExamQuestionOut]


class StartExamIn(BaseModel):
    """Body for `POST /api/exam/sessions`. Accepts subject code or UUID."""

    subject: str | None = None
    subject_id: uuid.UUID | None = None
    kind: str = "full_mock"   # "diagnostic" | "full_mock" | "checkpoint"
    target_grade: str | None = None


class AnswerIn(_CamelModel):
    """Frontend sends either `{qIndex, answer, flagged}` or
    `{question_index, answer, time_taken_ms, flagged}`. We accept both."""

    question_index: int = Field(alias="qIndex")
    answer: dict | list | str | None = None
    flagged: bool = False
    time_taken_ms: int | None = Field(default=None, alias="timeMs")


class AutosaveIn(_CamelModel):
    answers: list[AnswerIn]


class SubmitOut(_CamelModel):
    """Frontend expects `{ jobId }` — we make grading synchronous, but the
    polling loop in ExamAnalyzing.tsx works either way."""

    job_id: str = Field(alias="jobId")
    session_id: str = Field(alias="sessionId")


class TopicBreakdownOut(_CamelModel):
    topic: str
    domain: str
    mastery: float
    impact: float


class StrongTopicOut(_CamelModel):
    topic: str
    domain: str
    mastery: float


class SectionStats(_CamelModel):
    correct: int
    total: int
    ball: float


class ExamBreakdownItem(_CamelModel):
    q_index: int = Field(alias="qIndex")
    topic: str
    your_answer: str | None = Field(default=None, alias="yourAnswer")
    correct_answer: str = Field(alias="correctAnswer")
    correct: bool
    time_spent_ms: int = Field(alias="timeSpentMs")


class ExamSummaryOut(_CamelModel):
    """Mirrors frontend `ExamSummary`."""

    session_id: str = Field(alias="sessionId")
    rasch_score: float = Field(alias="raschScore")
    grade: str
    total_correct: int = Field(alias="totalCorrect")
    total_questions: int = Field(alias="totalQuestions")
    section_a: SectionStats = Field(alias="sectionA")
    section_b: SectionStats = Field(alias="sectionB")
    weak_topics: list[TopicBreakdownOut] = Field(alias="weakTopics")
    strong_topics: list[StrongTopicOut] = Field(alias="strongTopics")
    breakdown: list[ExamBreakdownItem]
    certificate_ready: bool = Field(alias="certificateReady")


class FormulaItem(BaseModel):
    name: str
    eq: str
    # Optional URL for humanities subjects where we surface curated references
    # (history primary sources, atlases, literary texts) instead of formulas.
    href: str | None = None


class FormulaGroup(BaseModel):
    title: str
    items: list[FormulaItem]
    # "formula" (default) renders LaTeX-style; "reference" renders as clickable
    # external links so subjects like history/geography surface trusted sources
    # rather than meaningless equations.
    kind: str = "formula"


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_DURATIONS = {
    ExamKind.DIAGNOSTIC: 30,
    ExamKind.FULL_MOCK: 150,
    ExamKind.CHECKPOINT: 15,
}

SECTION_A_TARGET = 35
SECTION_B_TARGET = 10
FULL_MOCK_TARGET = SECTION_A_TARGET + SECTION_B_TARGET


def _now() -> datetime:
    return datetime.now(UTC)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


async def _resolve_subject(db, payload: StartExamIn) -> Subject:
    if payload.subject_id:
        subj = (
            await db.execute(select(Subject).where(Subject.id == payload.subject_id))
        ).scalar_one_or_none()
    elif payload.subject:
        try:
            code = SubjectCode(payload.subject.upper())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Unknown subject code") from e
        subj = (
            await db.execute(select(Subject).where(Subject.code == code))
        ).scalar_one_or_none()
    else:
        raise HTTPException(status_code=400, detail="subject or subject_id required")
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subj


async def _resolve_subject_by_code(db, subject_code: str) -> Subject:
    """For GET endpoints that take subject as a string."""
    try:
        code = SubjectCode(subject_code.upper())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Unknown subject code") from e
    subj = (
        await db.execute(select(Subject).where(Subject.code == code))
    ).scalar_one_or_none()
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subj


def _section_for_question(q: Question) -> str:
    return "A" if q.type == QuestionType.CLOSED else "B"


_DOMAIN_FROM_TOPIC_HINT = {
    "algebra": "Algebra",
    "geometry": "Geometry",
    "trigonometry": "Trigonometry",
    "functions": "Functions",
    "probability": "Functions",
    "sequences": "Sequences & series",
    "logarithms": "Algebra",
    "inequalities": "Algebra",
    "kinematics": "Mechanics",
    "newton": "Mechanics",
    "momentum": "Mechanics",
    "energy": "Mechanics",
    "thermodynamics": "Thermodynamics",
    "electro": "Electromagnetism",
    "circuit": "Electromagnetism",
    "optics": "Waves & optics",
    "waves": "Waves & optics",
    "atomic": "General chemistry",
    "periodic": "General chemistry",
    "bonding": "General chemistry",
    "stoichiometry": "General chemistry",
    "acid": "General chemistry",
    "redox": "General chemistry",
    "organic": "Organic chemistry",
    "solutions": "General chemistry",
    "gas laws": "General chemistry",
    "cell": "Biology",
    "genetics": "Biology",
    "anatomy": "Biology",
    "plants": "Biology",
    "animals": "Biology",
    "evolution": "Biology",
    "ecology": "Biology",
}


def _domain_for(topic: Topic, fallback: str = "Algebra") -> str:
    """Use the depth-1 ancestor (`Algebra`/`Geometry`/`Functions`) if present,
    else derive from the topic's English name. Callers should pass the
    subject's display name as `fallback` so unmapped topics get a subject-
    appropriate label rather than always reading "Algebra"."""
    if topic.parent_id:
        # Best-effort: the topic name itself is descriptive enough for the UI.
        pass
    name_lc = (topic.name_en or "").lower()
    for key, val in _DOMAIN_FROM_TOPIC_HINT.items():
        if key in name_lc:
            return val
    return fallback


def _question_options_view(q: Question) -> list[dict] | None:
    if not q.options or q.type != QuestionType.CLOSED:
        return None
    out: list[dict] = []
    for letter in ("A", "B", "C", "D"):
        opt = q.options.get(letter)
        if opt is None:
            continue
        if isinstance(opt, dict):
            text = opt.get("en") or opt.get("uz") or opt.get("ru") or ""
        else:
            text = str(opt)
        out.append({"letter": letter, "text": text})
    return out or None


def _pick_questions(
    questions: list[Question], target_count: int, prefer_section: str | None = None
) -> list[Question]:
    """Round-robin sampler across topics with a deterministic seed."""
    if len(questions) <= target_count:
        return list(questions)
    rng = random.Random(target_count)
    by_topic: dict[uuid.UUID, list[Question]] = {}
    for q in questions:
        by_topic.setdefault(q.topic_id, []).append(q)
    for lst in by_topic.values():
        rng.shuffle(lst)
    picks: list[Question] = []
    while len(picks) < target_count:
        progressed = False
        for tid in list(by_topic.keys()):
            if by_topic[tid]:
                picks.append(by_topic[tid].pop())
                progressed = True
                if len(picks) >= target_count:
                    break
        if not progressed:
            break
    return picks


async def _select_full_mock_questions(db, subject_id: uuid.UUID) -> list[Question]:
    """Pick 35 closed (Section A) + 10 open (Section B). Falls back to any if the
    typed pool is too small."""
    closed = (
        await db.execute(
            select(Question).where(
                Question.subject_id == subject_id,
                Question.type == QuestionType.CLOSED,
            )
        )
    ).scalars().all()
    open_q = (
        await db.execute(
            select(Question).where(
                Question.subject_id == subject_id,
                Question.type.in_([QuestionType.OPEN_A, QuestionType.OPEN_B]),
            )
        )
    ).scalars().all()
    a_picked = _pick_questions(list(closed), SECTION_A_TARGET)
    b_picked = _pick_questions(list(open_q), SECTION_B_TARGET)
    picks = a_picked + b_picked
    if not picks:
        # Last-resort: any question — better than 503'ing the demo.
        any_q = (
            await db.execute(
                select(Question).where(Question.subject_id == subject_id)
            )
        ).scalars().all()
        picks = _pick_questions(list(any_q), FULL_MOCK_TARGET)
    return picks


def _persist_layout(questions: list[Question]) -> list[dict]:
    return [
        {
            "question_id": str(q.id),
            "index": i,
            "topic_id": str(q.topic_id),
            "points": float(q.points),
            "difficulty": float(q.difficulty),
        }
        for i, q in enumerate(questions)
    ]


async def _load_attempt_questions(
    db, attempt: ExamAttempt
) -> tuple[dict[uuid.UUID, Question], dict[uuid.UUID, Topic]]:
    qids = [uuid.UUID(lay["question_id"]) for lay in attempt.question_layout]
    questions = (
        await db.execute(select(Question).where(Question.id.in_(qids)))
    ).scalars().all()
    qmap = {q.id: q for q in questions}
    topic_ids = {q.topic_id for q in questions}
    topics = (
        await db.execute(select(Topic).where(Topic.id.in_(topic_ids)))
    ).scalars().all()
    tmap = {t.id: t for t in topics}
    return qmap, tmap


def _build_session_view(
    attempt: ExamAttempt,
    subject: Subject,
    qmap: dict[uuid.UUID, Question],
    tmap: dict[uuid.UUID, Topic],
) -> ExamSessionOut:
    qviews: list[ExamQuestionOut] = []
    subject_label = subject.name_en
    for layout in attempt.question_layout:
        qid = uuid.UUID(layout["question_id"])
        q = qmap.get(qid)
        if not q:
            continue
        t = tmap.get(q.topic_id)
        prompt = (q.body_en or q.body_uz or "").strip()
        # The frontend renders `prompt` as the question stem. If the body
        # contains a math expression on its own line, we still ship it as-is.
        qviews.append(
            ExamQuestionOut(
                id=str(q.id),
                index=layout["index"],
                section=_section_for_question(q),
                type=q.type.value,
                domain=_domain_for(t, fallback=subject_label) if t else subject_label,
                topic=t.name_en if t else "",
                prompt=prompt,
                options=_question_options_view(q),
                weight=float(q.points),
            )
        )
    qviews.sort(key=lambda v: v.index)

    duration_ms = DEFAULT_DURATIONS[attempt.kind] * 60 * 1000
    if attempt.expires_at and attempt.started_at:
        duration_ms = int((attempt.expires_at - attempt.started_at).total_seconds() * 1000)

    return ExamSessionOut(
        id=str(attempt.id),
        slug=attempt.slug,
        subject=subject.code.value,
        startedAt=_ms(attempt.started_at),
        durationMs=duration_ms,
        questions=qviews,
    )


async def _load_attempt_for_user(
    db, attempt_id_or_slug: str, user_id: uuid.UUID
) -> ExamAttempt:
    stmt = select(ExamAttempt)
    try:
        aid = uuid.UUID(attempt_id_or_slug)
        stmt = stmt.where(ExamAttempt.id == aid)
    except ValueError:
        stmt = stmt.where(ExamAttempt.slug == attempt_id_or_slug)
    attempt = (await db.execute(stmt)).scalar_one_or_none()
    if not attempt or attempt.user_id != user_id:
        raise HTTPException(status_code=404, detail="Exam attempt not found")
    return attempt


# ════════════════════════════════════════════════════════════════════════════
# Start exam (frontend: POST /api/exam/sessions { subject })
# ════════════════════════════════════════════════════════════════════════════


async def _create_attempt(
    db,
    user_id: uuid.UUID,
    subject_id: uuid.UUID,
    kind: ExamKind,
    questions: list[Question],
    title_hint: str,
) -> ExamAttempt:
    if not questions:
        raise HTTPException(
            status_code=503,
            detail="No questions seeded for this subject — run scripts/seed_questions.py",
        )
    now = _now()
    attempt = ExamAttempt(
        slug=short_slug(f"{kind.value}-{title_hint}"),
        user_id=user_id,
        subject_id=subject_id,
        kind=kind,
        status=ExamStatus.IN_PROGRESS,
        question_layout=_persist_layout(questions),
        started_at=now,
        expires_at=now + timedelta(minutes=DEFAULT_DURATIONS[kind]),
    )
    db.add(attempt)
    await db.flush()
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def _session_view(db, attempt: ExamAttempt) -> ExamSessionOut:
    subject = (
        await db.execute(select(Subject).where(Subject.id == attempt.subject_id))
    ).scalar_one()
    qmap, tmap = await _load_attempt_questions(db, attempt)
    return _build_session_view(attempt, subject, qmap, tmap)


def _parse_kind(s: str | None) -> ExamKind:
    if not s:
        return ExamKind.FULL_MOCK
    s = s.lower().replace("-", "_")
    try:
        return ExamKind(s)
    except ValueError:
        return ExamKind.FULL_MOCK


@router.post(
    "/exam/sessions",
    response_model=ExamSessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new exam session (frontend-shaped)",
)
async def create_session(
    payload: StartExamIn, user: CurrentUser, db: DbSession
) -> ExamSessionOut:
    """Frontend's `createExamSession(subject)` lands here. Defaults to a 45-q
    full mock for the named subject."""
    subj = await _resolve_subject(db, payload)
    kind = _parse_kind(payload.kind)
    if payload.target_grade and not user.target_grade:
        user.target_grade = payload.target_grade

    if kind == ExamKind.FULL_MOCK:
        picked = await _select_full_mock_questions(db, subj.id)
    elif kind == ExamKind.DIAGNOSTIC:
        questions = (
            await db.execute(
                select(Question).where(Question.subject_id == subj.id).order_by(Question.difficulty)
            )
        ).scalars().all()
        picked = _pick_questions(list(questions), 20)
    else:
        # checkpoint without a topic — pick any 8 from subject
        questions = (
            await db.execute(select(Question).where(Question.subject_id == subj.id))
        ).scalars().all()
        picked = _pick_questions(list(questions), 8)

    attempt = await _create_attempt(db, user.id, subj.id, kind, picked, subj.slug)
    return await _session_view(db, attempt)


@router.get("/exam/sessions/{attempt_id_or_slug}", response_model=ExamSessionOut)
async def get_session(
    attempt_id_or_slug: str, user: CurrentUser, db: DbSession
) -> ExamSessionOut:
    attempt = await _load_attempt_for_user(db, attempt_id_or_slug, user.id)
    return await _session_view(db, attempt)


# ════════════════════════════════════════════════════════════════════════════
# In-flight answer saving
# ════════════════════════════════════════════════════════════════════════════


async def _upsert_answer(
    db, attempt: ExamAttempt, payload: AnswerIn
) -> None:
    layout = next(
        (lay for lay in attempt.question_layout if lay["index"] == payload.question_index),
        None,
    )
    if not layout:
        raise HTTPException(status_code=400, detail="Invalid question index")
    existing = (
        await db.execute(
            select(ExamAnswer).where(
                ExamAnswer.attempt_id == attempt.id,
                ExamAnswer.question_index == payload.question_index,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.answer = payload.answer
        existing.flagged = payload.flagged
        if payload.time_taken_ms is not None:
            existing.time_taken_ms = payload.time_taken_ms
    else:
        db.add(
            ExamAnswer(
                attempt_id=attempt.id,
                question_id=uuid.UUID(layout["question_id"]),
                question_index=payload.question_index,
                answer=payload.answer,
                flagged=payload.flagged,
                time_taken_ms=payload.time_taken_ms,
            )
        )


@router.patch(
    "/exam/sessions/{attempt_id_or_slug}/answer",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Save a single answer (frontend autosaves on every selection)",
)
async def save_answer(
    attempt_id_or_slug: str,
    payload: AnswerIn,
    user: CurrentUser,
    db: DbSession,
) -> None:
    attempt = await _load_attempt_for_user(db, attempt_id_or_slug, user.id)
    if attempt.status != ExamStatus.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Attempt no longer active")
    await _upsert_answer(db, attempt, payload)
    await db.commit()


@router.patch(
    "/exam/sessions/{attempt_id_or_slug}/autosave",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bulk autosave (frontend calls every 30s)",
)
async def autosave(
    attempt_id_or_slug: str,
    payload: AutosaveIn,
    user: CurrentUser,
    db: DbSession,
) -> None:
    attempt = await _load_attempt_for_user(db, attempt_id_or_slug, user.id)
    if attempt.status != ExamStatus.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Attempt no longer active")
    for ans in payload.answers:
        await _upsert_answer(db, attempt, ans)
    await db.commit()


# ════════════════════════════════════════════════════════════════════════════
# Submit + grade + result
# ════════════════════════════════════════════════════════════════════════════


async def _update_mastery_from_attempt(
    db,
    attempt: ExamAttempt,
    answers: list[ExamAnswer],
    questions: dict[uuid.UUID, Question],
):
    by_topic: dict[uuid.UUID, list[tuple[ExamAnswer, Question]]] = {}
    for a in answers:
        q = questions.get(a.question_id)
        if not q:
            continue
        by_topic.setdefault(q.topic_id, []).append((a, q))
    for topic_id, pairs in by_topic.items():
        row = (
            await db.execute(
                select(MasteryTopic).where(
                    MasteryTopic.user_id == attempt.user_id,
                    MasteryTopic.topic_id == topic_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            row = MasteryTopic(
                user_id=attempt.user_id,
                topic_id=topic_id,
                subject_id=attempt.subject_id,
                attempts_count=0,
                correct_count=0,
                weighted_earned=Decimal("0.00"),
                weighted_total=Decimal("0.00"),
                mastery_pct=Decimal("0.00"),
            )
            db.add(row)
        for a, q in pairs:
            row.attempts_count += 1
            if a.is_correct:
                row.correct_count += 1
            weighted = float(q.points) * (1.0 + float(q.difficulty))
            row.weighted_total = Decimal(str(float(row.weighted_total) + weighted))
            if a.is_correct:
                row.weighted_earned = Decimal(
                    str(float(row.weighted_earned) + weighted)
                )
            row.last_attempted_at = _now()
        if float(row.weighted_total) > 0:
            pct = float(row.weighted_earned) / float(row.weighted_total) * 100.0
            row.mastery_pct = Decimal(f"{min(100.0, pct):.2f}")


async def _grade_attempt(
    db, attempt: ExamAttempt
) -> tuple[list[ExamAnswer], dict[uuid.UUID, Question]]:
    qmap, _ = await _load_attempt_questions(db, attempt)
    answers = (
        await db.execute(select(ExamAnswer).where(ExamAnswer.attempt_id == attempt.id))
    ).scalars().all()
    answered_idx = {a.question_index for a in answers}
    for layout in attempt.question_layout:
        if layout["index"] not in answered_idx:
            row = ExamAnswer(
                attempt_id=attempt.id,
                question_id=uuid.UUID(layout["question_id"]),
                question_index=layout["index"],
                answer=None,
            )
            db.add(row)
            answers.append(row)

    rasch_inputs: list[dict] = []
    for a in answers:
        q = qmap.get(a.question_id)
        if not q:
            continue
        ok, pts = grade_answer(q, a.answer)
        a.is_correct = ok
        a.points_awarded = pts
        rasch_inputs.append(
            {
                "is_correct": ok,
                "points": float(q.points),
                "difficulty": float(q.difficulty),
            }
        )

    rasch = estimate_rasch(rasch_inputs)
    g = grade_for_score(rasch)
    raw_score = float(sum(float(a.points_awarded) for a in answers))

    topic_breakdown: dict[str, dict] = {}
    for a in answers:
        q = qmap.get(a.question_id)
        if not q:
            continue
        slot = topic_breakdown.setdefault(
            str(q.topic_id), {"correct": 0, "total": 0, "pct": 0.0}
        )
        slot["total"] += 1
        if a.is_correct:
            slot["correct"] += 1
    for slot in topic_breakdown.values():
        slot["pct"] = (
            round(slot["correct"] / slot["total"] * 100.0, 2) if slot["total"] else 0.0
        )
    weakest = sorted(
        (
            {"topic_id": tid, **slot}
            for tid, slot in topic_breakdown.items()
            if slot["total"] >= 2
        ),
        key=lambda s: s["pct"],
    )[:5]

    attempt.status = ExamStatus.GRADED
    attempt.submitted_at = _now()
    attempt.graded_at = _now()
    attempt.rasch_score = rasch
    attempt.raw_score = Decimal(f"{raw_score:.2f}")
    attempt.grade = Grade(g)
    attempt.topic_breakdown = topic_breakdown
    attempt.weakest_topics = weakest

    await _update_mastery_from_attempt(db, attempt, answers, qmap)
    await db.commit()
    return answers, qmap


@router.post(
    "/exam/sessions/{attempt_id_or_slug}/submit",
    response_model=SubmitOut,
    summary="Submit + grade. Returns a job ID for frontend's polling animation.",
)
async def submit_session(
    attempt_id_or_slug: str, user: CurrentUser, db: DbSession
) -> SubmitOut:
    attempt = await _load_attempt_for_user(db, attempt_id_or_slug, user.id)
    if attempt.status == ExamStatus.GRADED:
        return SubmitOut(jobId=f"job-{attempt.id}", sessionId=str(attempt.id))
    if attempt.status not in (ExamStatus.IN_PROGRESS, ExamStatus.SUBMITTED):
        raise HTTPException(status_code=409, detail="Attempt already cancelled")
    await _grade_attempt(db, attempt)
    return SubmitOut(jobId=f"job-{attempt.id}", sessionId=str(attempt.id))


@router.get(
    "/exam/sessions/{attempt_id_or_slug}/result", response_model=ExamSummaryOut
)
async def get_result(
    attempt_id_or_slug: str, user: CurrentUser, db: DbSession
) -> ExamSummaryOut:
    attempt = await _load_attempt_for_user(db, attempt_id_or_slug, user.id)
    if attempt.status != ExamStatus.GRADED:
        # Auto-grade lazily so the polling loop just works even if /submit was missed.
        if attempt.status == ExamStatus.IN_PROGRESS:
            await _grade_attempt(db, attempt)
        else:
            raise HTTPException(status_code=409, detail="Attempt not yet graded")

    qmap, tmap = await _load_attempt_questions(db, attempt)
    subject = (
        await db.execute(select(Subject).where(Subject.id == attempt.subject_id))
    ).scalar_one_or_none()
    subject_label = subject.name_en if subject else "Algebra"
    answers = (
        await db.execute(
            select(ExamAnswer)
            .where(ExamAnswer.attempt_id == attempt.id)
            .order_by(ExamAnswer.question_index)
        )
    ).scalars().all()

    section_a = SectionStats(correct=0, total=0, ball=0.0)
    section_b = SectionStats(correct=0, total=0, ball=0.0)
    breakdown: list[ExamBreakdownItem] = []
    for a in answers:
        q = qmap.get(a.question_id)
        if not q:
            continue
        sect = _section_for_question(q)
        if sect == "A":
            section_a.total += 1
            if a.is_correct:
                section_a.correct += 1
                section_a.ball += float(a.points_awarded)
        else:
            section_b.total += 1
            if a.is_correct:
                section_b.correct += 1
                section_b.ball += float(a.points_awarded)
        correct_str = q.correct_answer if isinstance(q.correct_answer, str) else (
            ",".join(map(str, q.correct_answer)) if isinstance(q.correct_answer, list) else "?"
        )
        topic = tmap.get(q.topic_id)
        breakdown.append(
            ExamBreakdownItem(
                qIndex=a.question_index,
                topic=topic.name_en if topic else "",
                yourAnswer=str(a.answer) if a.answer is not None else None,
                correctAnswer=correct_str,
                correct=bool(a.is_correct),
                timeSpentMs=int(a.time_taken_ms or 0),
            )
        )

    # Weak / strong topics from MasteryTopic
    mastery_rows = (
        await db.execute(
            select(MasteryTopic).where(
                MasteryTopic.user_id == attempt.user_id,
                MasteryTopic.subject_id == attempt.subject_id,
            )
        )
    ).scalars().all()
    mastery_by_topic = {m.topic_id: float(m.mastery_pct) for m in mastery_rows}

    weak_topics: list[TopicBreakdownOut] = []
    for entry in attempt.weakest_topics or []:
        tid = entry.get("topic_id")
        try:
            tuuid = uuid.UUID(tid) if tid else None
        except ValueError:
            tuuid = None
        topic = tmap.get(tuuid) if tuuid else None
        if not topic:
            continue
        mastery_pct = mastery_by_topic.get(topic.id, float(entry.get("pct", 0.0)))
        # impact ~= weight × (1 − mastery)
        impact = round(float(topic.weight) * (1.0 - mastery_pct / 100.0) * 8.0, 2)
        weak_topics.append(
            TopicBreakdownOut(
                topic=topic.name_en,
                domain=_domain_for(topic, fallback=subject_label),
                mastery=round(mastery_pct, 1),
                impact=impact,
            )
        )

    # Strong topics: top-mastery rows with at least 2 attempts
    strong_rows = sorted(
        [m for m in mastery_rows if m.attempts_count >= 2],
        key=lambda m: float(m.mastery_pct),
        reverse=True,
    )[:3]
    strong_topics: list[StrongTopicOut] = []
    for m in strong_rows:
        topic = tmap.get(m.topic_id)
        if not topic:
            topic = (
                await db.execute(select(Topic).where(Topic.id == m.topic_id))
            ).scalar_one_or_none()
            if not topic:
                continue
        strong_topics.append(
            StrongTopicOut(
                topic=topic.name_en,
                domain=_domain_for(topic, fallback=subject_label),
                mastery=round(float(m.mastery_pct), 1),
            )
        )

    return ExamSummaryOut(
        sessionId=str(attempt.id),
        raschScore=round(float(attempt.rasch_score or 0), 1),
        grade=attempt.grade.value if attempt.grade else "—",
        totalCorrect=sum(1 for a in answers if a.is_correct),
        totalQuestions=len(answers),
        sectionA=section_a,
        sectionB=section_b,
        weakTopics=weak_topics,
        strongTopics=strong_topics,
        breakdown=breakdown,
        certificateReady=(attempt.grade or Grade.FAIL) not in (Grade.FAIL,),
    )



# ════════════════════════════════════════════════════════════════════════════
# Formula sheet + recent attempts
# ════════════════════════════════════════════════════════════════════════════


def _formula_to_item(f: Formula) -> FormulaItem:
    return FormulaItem(name=f.name, eq=f.expression, href=f.href)


@router.get("/formulas", response_model=list[FormulaGroup])
async def formulas(db: DbSession, subject: str = "MATH") -> list[FormulaGroup]:
    """Per-subject reference content, pulled from the seeded `formulas` table.

    STEM subjects (MATH/PHYS/CHEM/BIO) return canonical formulas; humanities
    (HIST/GEOG/literature) return curated external source links so the right
    rail stays useful instead of showing irrelevant math equations. Group
    titles and per-row ordering come from the same DB columns the chat coach
    cites against, so both surfaces stay in sync."""
    try:
        code = SubjectCode(subject.upper())
    except ValueError:
        return []
    subj = (
        await db.execute(select(Subject).where(Subject.code == code))
    ).scalar_one_or_none()
    if not subj:
        return []
    rows = (
        await db.execute(
            select(Formula)
            .where(Formula.subject_id == subj.id)
            .order_by(Formula.kind, Formula.group_title, Formula.order_index)
        )
    ).scalars().all()
    if not rows:
        return []
    # Preserve the first-seen order of group_title so the response matches the
    # ordering implied by the seed (Algebra → Logarithms → Trigonometry … ).
    groups: dict[str, dict] = {}
    for f in rows:
        slot = groups.setdefault(
            f.group_title,
            {
                "title": f.group_title,
                "kind": f.kind.value,
                "items": [],
            },
        )
        slot["items"].append(_formula_to_item(f))
    return [FormulaGroup(**g) for g in groups.values()]


# ════════════════════════════════════════════════════════════════════════════
# Legacy v1 endpoints — kept so anything already wired against them keeps working
# ════════════════════════════════════════════════════════════════════════════


class _LegacyStartIn(BaseModel):
    subject_id: uuid.UUID | None = None
    subject: str | None = None
    target_grade: str | None = None
    topic_id: uuid.UUID | None = None


@router.post("/exams/full-mock", response_model=ExamSessionOut)
async def legacy_full_mock(
    payload: _LegacyStartIn, user: CurrentUser, db: DbSession
) -> ExamSessionOut:
    body = StartExamIn(
        subject=payload.subject,
        subject_id=payload.subject_id,
        kind="full_mock",
    )
    return await create_session(body, user, db)


@router.post("/exams/diagnostic", response_model=ExamSessionOut)
async def legacy_diagnostic(
    payload: _LegacyStartIn, user: CurrentUser, db: DbSession
) -> ExamSessionOut:
    body = StartExamIn(
        subject=payload.subject,
        subject_id=payload.subject_id,
        kind="diagnostic",
        target_grade=payload.target_grade,
    )
    return await create_session(body, user, db)


@router.get("/exams/me/recent", response_model=list[ExamSessionOut])
async def list_my_attempts(
    user: CurrentUser, db: DbSession, limit: int = 20
) -> list[ExamSessionOut]:
    attempts = (
        await db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.user_id == user.id)
            .order_by(desc(ExamAttempt.started_at))
            .limit(limit)
        )
    ).scalars().all()
    return [await _session_view(db, a) for a in attempts]


class ExamHistoryItemOut(_CamelModel):
    """Compact summary of an exam attempt for history lists (roadmap, mocks page)."""

    id: str
    slug: str
    subject: str
    subject_label: str = Field(alias="subjectLabel")
    kind: str
    status: str
    grade: str | None
    rasch_score: float | None = Field(alias="raschScore")
    raw_score: float | None = Field(alias="rawScore")
    total_correct: int = Field(alias="totalCorrect")
    total_questions: int = Field(alias="totalQuestions")
    started_at: int = Field(alias="startedAt")
    submitted_at: int | None = Field(alias="submittedAt")


@router.get("/exam/history", response_model=list[ExamHistoryItemOut])
async def exam_history(
    user: CurrentUser, db: DbSession, limit: int = 20
) -> list[ExamHistoryItemOut]:
    """Recent exam attempts with their scores — backs the mock-history UI on the
    ExamLanding and Roadmap pages so users can see how they did after submitting."""
    attempts = (
        await db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.user_id == user.id)
            .order_by(desc(ExamAttempt.started_at))
            .limit(limit)
        )
    ).scalars().all()
    if not attempts:
        return []

    subject_ids = {a.subject_id for a in attempts}
    subjects = (
        await db.execute(select(Subject).where(Subject.id.in_(subject_ids)))
    ).scalars().all()
    subj_by_id = {s.id: s for s in subjects}

    out: list[ExamHistoryItemOut] = []
    for a in attempts:
        subj = subj_by_id.get(a.subject_id)
        answers = (
            await db.execute(
                select(ExamAnswer).where(ExamAnswer.attempt_id == a.id)
            )
        ).scalars().all()
        total_correct = sum(1 for ans in answers if ans.is_correct)
        total_q = len(a.question_layout or [])
        out.append(
            ExamHistoryItemOut(
                id=str(a.id),
                slug=a.slug,
                subject=subj.code.value if subj else "MATH",
                subjectLabel=subj.name_en if subj else "Mathematics",
                kind=a.kind.value,
                status=a.status.value,
                grade=a.grade.value if a.grade else None,
                raschScore=float(a.rasch_score) if a.rasch_score is not None else None,
                rawScore=float(a.raw_score) if a.raw_score is not None else None,
                totalCorrect=total_correct,
                totalQuestions=total_q,
                startedAt=_ms(a.started_at),
                submittedAt=_ms(a.submitted_at) if a.submitted_at else None,
            )
        )
    return out


@router.get("/exams/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "exams", "status": "ok"}


# Module-level re-exports used by the regex parser when projecting answers.
__all__ = [
    "router",
    "ExamSessionOut",
    "ExamSummaryOut",
]
