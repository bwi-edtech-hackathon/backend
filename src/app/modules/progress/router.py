"""Progress routes — analytics dashboard, mastery heatmap, snapshots, predicted grade."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select

from app.core.deps import CurrentUser, DbSession
from app.models.battle import EloRating
from app.models.catalog import Subject, Topic
from app.models.exam import ExamAttempt, ExamStatus
from app.models.progress import MasterySnapshot, MasteryTopic

router = APIRouter(prefix="/api/v1", tags=["progress"])


# === Schemas ===
class SubjectProgress(BaseModel):
    subject_id: uuid.UUID
    subject_code: str
    subject_slug: str
    subject_name_uz: str
    subject_name_ru: str
    subject_name_en: str
    rasch_score: float
    elo: int
    elo_tier: str
    mastery_pct: float
    topics_mastered: int
    topics_total: int
    predicted_grade: str | None
    last_exam_score: float | None
    on_track: bool


class DashboardOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    streak_days: int
    target_exam_date: date | None
    target_grade: str | None
    per_subject: list[SubjectProgress]


class MasteryTopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    topic_id: uuid.UUID
    topic_slug: str
    topic_name_uz: str
    topic_name_ru: str
    topic_name_en: str
    depth: int
    parent_id: uuid.UUID | None
    mastery_pct: float
    attempts_count: int
    correct_count: int


class SnapshotOut(BaseModel):
    snapshot_date: date
    rasch_score: float
    grade: str | None
    elo: int


class PredictedGradeOut(BaseModel):
    subject_id: uuid.UUID
    current_rasch: float
    projected_rasch: float
    projected_grade: str
    days_to_exam: int | None
    confidence: float


# === Helpers ===
def _tier(rating: int) -> str:
    if rating < 1200:
        return "BRONZE"
    if rating < 1500:
        return "SILVER"
    if rating < 1800:
        return "GOLD"
    return "PLATINUM"


def _grade_for_score(score: float) -> str:
    if score >= 70:
        return "A+"
    if score >= 65:
        return "A"
    if score >= 60:
        return "B+"
    if score >= 55:
        return "B"
    if score >= 50:
        return "C+"
    if score >= 46:
        return "C"
    return "F"


def _grade_meets_target(predicted: str, target: str | None) -> bool:
    order = ["F", "C", "C+", "B", "B+", "A", "A+"]
    if not target:
        return True
    try:
        return order.index(predicted) >= order.index(target)
    except ValueError:
        return False


# === Endpoints ===
@router.get("/progress/dashboard", response_model=DashboardOut, summary="Home dashboard payload")
async def get_dashboard(user: CurrentUser, db: DbSession) -> DashboardOut:
    subjects = (await db.execute(select(Subject).order_by(Subject.order_index))).scalars().all()

    per_subject: list[SubjectProgress] = []
    for subj in subjects:
        # ELO
        elo_row = (
            await db.execute(
                select(EloRating).where(
                    EloRating.user_id == user.id, EloRating.subject_id == subj.id
                )
            )
        ).scalar_one_or_none()
        elo = elo_row.rating if elo_row else 1200

        # Mastery aggregate
        agg = (
            await db.execute(
                select(
                    func.coalesce(func.avg(MasteryTopic.mastery_pct), 0).label("avg"),
                    func.count(MasteryTopic.id).label("topics_touched"),
                    func.sum(
                        case((MasteryTopic.mastery_pct >= 75, 1), else_=0)
                    ).label("mastered"),
                ).where(
                    MasteryTopic.user_id == user.id,
                    MasteryTopic.subject_id == subj.id,
                )
            )
        ).one()
        mastery_pct = float(agg.avg or 0)
        topics_mastered = int(agg.mastered or 0)

        # Topic count
        total_topics = (
            await db.execute(
                select(func.count(Topic.id)).where(
                    Topic.subject_id == subj.id, Topic.depth == 2
                )
            )
        ).scalar_one()

        # Last exam
        last_exam = (
            await db.execute(
                select(ExamAttempt)
                .where(
                    ExamAttempt.user_id == user.id,
                    ExamAttempt.subject_id == subj.id,
                    ExamAttempt.status == ExamStatus.GRADED,
                )
                .order_by(ExamAttempt.graded_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        last_score = float(last_exam.rasch_score) if last_exam and last_exam.rasch_score else None
        rasch = last_score or 0.0

        predicted = _grade_for_score(rasch) if rasch > 0 else None
        on_track = _grade_meets_target(predicted, user.target_grade) if predicted else False

        per_subject.append(
            SubjectProgress(
                subject_id=subj.id,
                subject_code=subj.code.value,
                subject_slug=subj.slug,
                subject_name_uz=subj.name_uz,
                subject_name_ru=subj.name_ru,
                subject_name_en=subj.name_en,
                rasch_score=rasch,
                elo=elo,
                elo_tier=_tier(elo),
                mastery_pct=round(mastery_pct, 2),
                topics_mastered=topics_mastered,
                topics_total=int(total_topics or 0),
                predicted_grade=predicted,
                last_exam_score=last_score,
                on_track=on_track,
            )
        )

    return DashboardOut(
        user_id=user.id,
        full_name=user.full_name,
        streak_days=user.streak_days,
        target_exam_date=user.exam_target_date,
        target_grade=user.target_grade,
        per_subject=per_subject,
    )


@router.get(
    "/progress/mastery",
    response_model=list[MasteryTopicOut],
    summary="Per-topic mastery (heatmap source)",
)
async def get_mastery(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(..., description="Subject UUID"),
) -> list[MasteryTopicOut]:
    rows = (
        await db.execute(
            select(MasteryTopic, Topic)
            .join(Topic, Topic.id == MasteryTopic.topic_id)
            .where(MasteryTopic.user_id == user.id, MasteryTopic.subject_id == subject_id)
            .order_by(Topic.depth, Topic.order_index)
        )
    ).all()
    return [
        MasteryTopicOut(
            topic_id=t.id,
            topic_slug=t.slug,
            topic_name_uz=t.name_uz,
            topic_name_ru=t.name_ru,
            topic_name_en=t.name_en,
            depth=t.depth,
            parent_id=t.parent_id,
            mastery_pct=float(m.mastery_pct),
            attempts_count=m.attempts_count,
            correct_count=m.correct_count,
        )
        for m, t in rows
    ]


@router.get(
    "/progress/snapshots",
    response_model=list[SnapshotOut],
    summary="Rasch-score trend (line chart)",
)
async def get_snapshots(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
    weeks: int = Query(8, ge=1, le=52),
) -> list[SnapshotOut]:
    since = date.today() - timedelta(weeks=weeks)
    rows = (
        await db.execute(
            select(MasterySnapshot)
            .where(
                MasterySnapshot.user_id == user.id,
                MasterySnapshot.subject_id == subject_id,
                MasterySnapshot.snapshot_date >= since,
            )
            .order_by(MasterySnapshot.snapshot_date)
        )
    ).scalars().all()
    return [
        SnapshotOut(
            snapshot_date=s.snapshot_date,
            rasch_score=float(s.rasch_score),
            grade=s.grade,
            elo=s.elo,
        )
        for s in rows
    ]


@router.get(
    "/progress/predicted-grade",
    response_model=PredictedGradeOut,
    summary="Linear extrapolation to exam date",
)
async def get_predicted_grade(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
) -> PredictedGradeOut:
    # Get last 4 weeks of snapshots for linear fit
    since = date.today() - timedelta(weeks=4)
    snaps = (
        await db.execute(
            select(MasterySnapshot)
            .where(
                MasterySnapshot.user_id == user.id,
                MasterySnapshot.subject_id == subject_id,
                MasterySnapshot.snapshot_date >= since,
            )
            .order_by(MasterySnapshot.snapshot_date)
        )
    ).scalars().all()

    if not snaps:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No mastery snapshots yet — take a diagnostic first",
        )

    current_rasch = float(snaps[-1].rasch_score)

    # Linear slope: points per day
    if len(snaps) >= 2:
        first, last = snaps[0], snaps[-1]
        days = max((last.snapshot_date - first.snapshot_date).days, 1)
        slope = (float(last.rasch_score) - float(first.rasch_score)) / days
    else:
        slope = 0.0

    days_to_exam = None
    projected = current_rasch
    if user.exam_target_date:
        days_to_exam = max((user.exam_target_date - date.today()).days, 0)
        projected = max(0.0, min(100.0, current_rasch + slope * days_to_exam))

    confidence = min(1.0, len(snaps) / 8.0)

    return PredictedGradeOut(
        subject_id=subject_id,
        current_rasch=current_rasch,
        projected_rasch=round(projected, 2),
        projected_grade=_grade_for_score(projected),
        days_to_exam=days_to_exam,
        confidence=round(confidence, 2),
    )


@router.get("/progress/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "progress", "status": "ok"}
