"""Exams routes — diagnostic, full mock, checkpoint, attempts, submit, result."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select

from app.core.deps import CurrentUser, DbSession
from app.core.slugs import short_slug
from app.models.catalog import Question, Subject, Topic
from app.models.exam import ExamAnswer, ExamAttempt, ExamKind, ExamStatus, Grade
from app.models.progress import MasteryTopic
from app.modules.exams.grader import estimate_rasch, grade_answer, grade_for_score

router = APIRouter(prefix="/api/v1", tags=["exams"])


# === Schemas ===
class StartDiagnosticIn(BaseModel):
    subject_id: uuid.UUID
    target_grade: str | None = None


class StartFullMockIn(BaseModel):
    subject_id: uuid.UUID


class StartCheckpointIn(BaseModel):
    topic_id: uuid.UUID


class QuestionView(BaseModel):
    id: uuid.UUID
    index: int
    type: str
    body_uz: str
    body_ru: str
    body_en: str
    options: dict | None
    points: float
    topic_id: uuid.UUID
    flagged: bool = False
    answered: bool = False


class AttemptOut(BaseModel):
    id: uuid.UUID
    slug: str
    kind: str
    status: str
    subject_id: uuid.UUID
    started_at: datetime
    expires_at: datetime | None
    submitted_at: datetime | None
    total_questions: int
    answered_count: int
    flagged_count: int
    questions: list[QuestionView]


class AnswerIn(BaseModel):
    question_index: int
    answer: dict | list | str | None = None
    time_taken_ms: int | None = None
    flagged: bool = False


class AutosaveIn(BaseModel):
    answers: list[AnswerIn]


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    attempt_id: uuid.UUID
    slug: str
    rasch_score: float
    raw_score: float
    grade: str
    correct_count: int
    total_questions: int
    topic_breakdown: dict
    weakest_topics: list[dict]
    submitted_at: datetime


# === Helpers ===
DEFAULT_DURATIONS = {
    ExamKind.DIAGNOSTIC: 30,
    ExamKind.FULL_MOCK: 150,
    ExamKind.CHECKPOINT: 15,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _pick_questions_for_subject(
    questions: list[Question], target_count: int
) -> list[Question]:
    """Spread picks across topics + difficulty bands."""
    if len(questions) <= target_count:
        return list(questions)
    rng = random.Random(target_count)  # deterministic-ish per request
    # Bucket by topic, then sample round-robin
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


async def _load_attempt(db, attempt_id_or_slug: str, user_id: uuid.UUID) -> ExamAttempt:
    stmt = select(ExamAttempt)
    try:
        aid = uuid.UUID(attempt_id_or_slug)
        stmt = stmt.where(ExamAttempt.id == aid)
    except ValueError:
        stmt = stmt.where(ExamAttempt.slug == attempt_id_or_slug)
    attempt = (await db.execute(stmt)).scalar_one_or_none()
    if not attempt or attempt.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Exam attempt not found"
        )
    return attempt


def _build_question_views(
    attempt: ExamAttempt, questions: dict[uuid.UUID, Question], answers: dict[int, ExamAnswer]
) -> list[QuestionView]:
    views: list[QuestionView] = []
    for layout in attempt.question_layout:
        qid = uuid.UUID(layout["question_id"])
        idx = layout["index"]
        q = questions.get(qid)
        if not q:
            continue
        a = answers.get(idx)
        views.append(
            QuestionView(
                id=q.id,
                index=idx,
                type=q.type.value,
                body_uz=q.body_uz,
                body_ru=q.body_ru,
                body_en=q.body_en,
                options=q.options,
                points=float(q.points),
                topic_id=q.topic_id,
                flagged=bool(a and a.flagged),
                answered=bool(a and a.answer is not None),
            )
        )
    views.sort(key=lambda v: v.index)
    return views


async def _attempt_to_out(db, attempt: ExamAttempt) -> AttemptOut:
    qids = [uuid.UUID(layout["question_id"]) for layout in attempt.question_layout]
    questions = (
        await db.execute(select(Question).where(Question.id.in_(qids)))
    ).scalars().all()
    qmap = {q.id: q for q in questions}
    answers = (
        await db.execute(select(ExamAnswer).where(ExamAnswer.attempt_id == attempt.id))
    ).scalars().all()
    amap = {a.question_index: a for a in answers}
    views = _build_question_views(attempt, qmap, amap)
    return AttemptOut(
        id=attempt.id,
        slug=attempt.slug,
        kind=attempt.kind.value,
        status=attempt.status.value,
        subject_id=attempt.subject_id,
        started_at=attempt.started_at,
        expires_at=attempt.expires_at,
        submitted_at=attempt.submitted_at,
        total_questions=len(attempt.question_layout),
        answered_count=sum(1 for a in answers if a.answer is not None),
        flagged_count=sum(1 for a in answers if a.flagged),
        questions=views,
    )


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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No questions available for this subject/topic",
        )
    now = _now()
    layout = [
        {
            "question_id": str(q.id),
            "index": i,
            "topic_id": str(q.topic_id),
            "points": float(q.points),
            "difficulty": float(q.difficulty),
        }
        for i, q in enumerate(questions)
    ]
    attempt = ExamAttempt(
        slug=short_slug(f"{kind.value}-{title_hint}"),
        user_id=user_id,
        subject_id=subject_id,
        kind=kind,
        status=ExamStatus.IN_PROGRESS,
        question_layout=layout,
        started_at=now,
        expires_at=now + timedelta(minutes=DEFAULT_DURATIONS[kind]),
    )
    db.add(attempt)
    await db.flush()
    await db.commit()
    await db.refresh(attempt)
    return attempt


# === Endpoints: start an exam ===
@router.post(
    "/exams/diagnostic",
    response_model=AttemptOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_diagnostic(
    payload: StartDiagnosticIn, user: CurrentUser, db: DbSession
) -> AttemptOut:
    if payload.target_grade and not user.target_grade:
        user.target_grade = payload.target_grade
    subj = (
        await db.execute(select(Subject).where(Subject.id == payload.subject_id))
    ).scalar_one_or_none()
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")

    questions = (
        await db.execute(
            select(Question).where(Question.subject_id == subj.id).order_by(Question.difficulty)
        )
    ).scalars().all()
    picked = _pick_questions_for_subject(list(questions), target_count=20)
    attempt = await _create_attempt(
        db, user.id, subj.id, ExamKind.DIAGNOSTIC, picked, subj.slug
    )
    return await _attempt_to_out(db, attempt)


@router.post(
    "/exams/full-mock",
    response_model=AttemptOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_full_mock(
    payload: StartFullMockIn, user: CurrentUser, db: DbSession
) -> AttemptOut:
    subj = (
        await db.execute(select(Subject).where(Subject.id == payload.subject_id))
    ).scalar_one_or_none()
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")
    questions = (
        await db.execute(select(Question).where(Question.subject_id == subj.id))
    ).scalars().all()
    picked = _pick_questions_for_subject(list(questions), target_count=45)
    attempt = await _create_attempt(
        db, user.id, subj.id, ExamKind.FULL_MOCK, picked, subj.slug
    )
    return await _attempt_to_out(db, attempt)


@router.post(
    "/exams/checkpoint",
    response_model=AttemptOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_checkpoint(
    payload: StartCheckpointIn, user: CurrentUser, db: DbSession
) -> AttemptOut:
    topic = (
        await db.execute(select(Topic).where(Topic.id == payload.topic_id))
    ).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    questions = (
        await db.execute(
            select(Question).where(Question.topic_id == topic.id).limit(20)
        )
    ).scalars().all()
    picked = _pick_questions_for_subject(list(questions), target_count=8)
    attempt = await _create_attempt(
        db, user.id, topic.subject_id, ExamKind.CHECKPOINT, picked, topic.slug
    )
    return await _attempt_to_out(db, attempt)


# === Endpoints: during the exam ===
@router.get("/exam-attempts/{attempt_id_or_slug}", response_model=AttemptOut)
async def get_attempt(
    attempt_id_or_slug: str, user: CurrentUser, db: DbSession
) -> AttemptOut:
    attempt = await _load_attempt(db, attempt_id_or_slug, user.id)
    return await _attempt_to_out(db, attempt)


@router.post(
    "/exam-attempts/{attempt_id_or_slug}/answer",
    response_model=AttemptOut,
)
async def submit_answer(
    attempt_id_or_slug: str,
    payload: AnswerIn,
    user: CurrentUser,
    db: DbSession,
) -> AttemptOut:
    attempt = await _load_attempt(db, attempt_id_or_slug, user.id)
    if attempt.status != ExamStatus.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Attempt no longer active")

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
    await db.commit()
    return await _attempt_to_out(db, attempt)


@router.patch("/exam-attempts/{attempt_id_or_slug}/autosave", response_model=AttemptOut)
async def autosave_answers(
    attempt_id_or_slug: str,
    payload: AutosaveIn,
    user: CurrentUser,
    db: DbSession,
) -> AttemptOut:
    attempt = await _load_attempt(db, attempt_id_or_slug, user.id)
    if attempt.status != ExamStatus.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Attempt no longer active")

    existing = (
        await db.execute(select(ExamAnswer).where(ExamAnswer.attempt_id == attempt.id))
    ).scalars().all()
    existing_map = {a.question_index: a for a in existing}

    layout_by_index = {lay["index"]: lay for lay in attempt.question_layout}

    for ans in payload.answers:
        layout = layout_by_index.get(ans.question_index)
        if not layout:
            continue
        if ans.question_index in existing_map:
            row = existing_map[ans.question_index]
            row.answer = ans.answer
            row.flagged = ans.flagged
            row.time_taken_ms = ans.time_taken_ms
        else:
            db.add(
                ExamAnswer(
                    attempt_id=attempt.id,
                    question_id=uuid.UUID(layout["question_id"]),
                    question_index=ans.question_index,
                    answer=ans.answer,
                    flagged=ans.flagged,
                    time_taken_ms=ans.time_taken_ms,
                )
            )
    await db.commit()
    return await _attempt_to_out(db, attempt)


# === Submit + grade ===
async def _update_mastery_from_attempt(db, attempt: ExamAttempt, answers: list[ExamAnswer], questions: dict[uuid.UUID, Question]):
    """Update MasteryTopic rows incrementally."""
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


@router.post(
    "/exam-attempts/{attempt_id_or_slug}/submit",
    response_model=ResultOut,
)
async def submit_attempt(
    attempt_id_or_slug: str, user: CurrentUser, db: DbSession
) -> ResultOut:
    attempt = await _load_attempt(db, attempt_id_or_slug, user.id)
    if attempt.status not in (ExamStatus.IN_PROGRESS, ExamStatus.SUBMITTED):
        raise HTTPException(status_code=409, detail="Attempt already graded or cancelled")

    qids = [uuid.UUID(lay["question_id"]) for lay in attempt.question_layout]
    questions = (
        await db.execute(select(Question).where(Question.id.in_(qids)))
    ).scalars().all()
    qmap = {q.id: q for q in questions}

    answers = (
        await db.execute(select(ExamAnswer).where(ExamAnswer.attempt_id == attempt.id))
    ).scalars().all()

    # Ensure rows exist for unanswered questions (mark wrong)
    answered_indices = {a.question_index for a in answers}
    for layout in attempt.question_layout:
        if layout["index"] not in answered_indices:
            row = ExamAnswer(
                attempt_id=attempt.id,
                question_id=uuid.UUID(layout["question_id"]),
                question_index=layout["index"],
                answer=None,
            )
            db.add(row)
            answers.append(row)

    # Grade each
    rasch_inputs: list[dict] = []
    for a in answers:
        q = qmap.get(a.question_id)
        if not q:
            continue
        is_correct, points = grade_answer(q, a.answer)
        a.is_correct = is_correct
        a.points_awarded = points
        rasch_inputs.append(
            {
                "is_correct": is_correct,
                "points": float(q.points),
                "difficulty": float(q.difficulty),
            }
        )

    rasch = estimate_rasch(rasch_inputs)
    g = grade_for_score(rasch)
    raw_score = float(sum(float(a.points_awarded) for a in answers))

    # Topic breakdown
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
    )[:3]

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

    return ResultOut(
        attempt_id=attempt.id,
        slug=attempt.slug,
        rasch_score=float(rasch),
        raw_score=raw_score,
        grade=g,
        correct_count=sum(1 for a in answers if a.is_correct),
        total_questions=len(answers),
        topic_breakdown=topic_breakdown,
        weakest_topics=weakest,
        submitted_at=attempt.submitted_at,
    )


@router.get("/exam-attempts/{attempt_id_or_slug}/result", response_model=ResultOut)
async def get_result(
    attempt_id_or_slug: str, user: CurrentUser, db: DbSession
) -> ResultOut:
    attempt = await _load_attempt(db, attempt_id_or_slug, user.id)
    if attempt.status != ExamStatus.GRADED:
        raise HTTPException(status_code=409, detail="Attempt not yet graded")
    answers = (
        await db.execute(select(ExamAnswer).where(ExamAnswer.attempt_id == attempt.id))
    ).scalars().all()
    return ResultOut(
        attempt_id=attempt.id,
        slug=attempt.slug,
        rasch_score=float(attempt.rasch_score or 0),
        raw_score=float(attempt.raw_score or 0),
        grade=attempt.grade.value if attempt.grade else "F",
        correct_count=sum(1 for a in answers if a.is_correct),
        total_questions=len(answers),
        topic_breakdown=attempt.topic_breakdown,
        weakest_topics=attempt.weakest_topics,
        submitted_at=attempt.submitted_at or _now(),
    )


@router.get("/exams/me/recent", response_model=list[AttemptOut])
async def list_my_attempts(
    user: CurrentUser, db: DbSession, limit: int = 20
) -> list[AttemptOut]:
    attempts = (
        await db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.user_id == user.id)
            .order_by(desc(ExamAttempt.started_at))
            .limit(limit)
        )
    ).scalars().all()
    return [await _attempt_to_out(db, a) for a in attempts]


@router.get("/exams/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "exams", "status": "ok"}
