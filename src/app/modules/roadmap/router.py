"""Roadmap routes — rule-based generator + milestone detail + regenerate."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.catalog import Question, Subject, Topic
from app.models.progress import MasteryTopic, Roadmap
from app.modules.roadmap.generator import generate_milestones, generated_at_utc

router = APIRouter(prefix="/api/v1", tags=["roadmap"])


# === Schemas ===
class MilestoneOut(BaseModel):
    topic_id: uuid.UUID
    topic_slug: str
    topic_name_uz: str
    topic_name_en: str
    order: int
    status: str
    mastery_pct: float
    est_minutes: int
    week_bucket: int
    weight: float


class RoadmapOut(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    subject_slug: str
    user_id: uuid.UUID
    generated_at: datetime
    weeks_total: int
    on_track: bool
    milestones: list[MilestoneOut]


class MilestoneDetailOut(BaseModel):
    milestone: MilestoneOut
    practice_question_ids: list[uuid.UUID]
    prerequisites: list[uuid.UUID]
    children: list[uuid.UUID]


# === Helpers ===
async def _resolve_subject(db, slug_or_id: str) -> Subject:
    stmt = select(Subject)
    try:
        sid = uuid.UUID(slug_or_id)
        stmt = stmt.where(Subject.id == sid)
    except ValueError:
        stmt = stmt.where(Subject.slug == slug_or_id)
    subj = (await db.execute(stmt)).scalar_one_or_none()
    if not subj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found"
        )
    return subj


async def _build_roadmap(db, user_id: uuid.UUID, subject: Subject, exam_date) -> Roadmap:
    topics = (
        await db.execute(
            select(Topic)
            .where(Topic.subject_id == subject.id)
            .order_by(Topic.depth, Topic.order_index)
        )
    ).scalars().all()
    mastery = (
        await db.execute(
            select(MasteryTopic).where(
                MasteryTopic.user_id == user_id,
                MasteryTopic.subject_id == subject.id,
            )
        )
    ).scalars().all()
    milestones = generate_milestones(topics, mastery, exam_date=exam_date)

    existing = (
        await db.execute(
            select(Roadmap).where(
                Roadmap.user_id == user_id, Roadmap.subject_id == subject.id
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.milestones = milestones
        existing.generated_at = generated_at_utc()
        rm = existing
    else:
        rm = Roadmap(
            user_id=user_id,
            subject_id=subject.id,
            milestones=milestones,
            generated_at=generated_at_utc(),
        )
        db.add(rm)
    await db.flush()
    await db.commit()
    await db.refresh(rm)
    return rm


def _on_track(milestones: list[dict]) -> bool:
    if not milestones:
        return False
    done = sum(1 for m in milestones if m["status"] == "mastered")
    return done / len(milestones) >= 0.5


def _weeks_total(milestones: list[dict]) -> int:
    if not milestones:
        return 0
    return max(m.get("week_bucket", 1) for m in milestones)


# === Endpoints ===
@router.get("/roadmap/{subject_id_or_slug}", response_model=RoadmapOut)
async def get_roadmap(
    subject_id_or_slug: str, user: CurrentUser, db: DbSession
) -> RoadmapOut:
    subj = await _resolve_subject(db, subject_id_or_slug)
    rm = (
        await db.execute(
            select(Roadmap).where(
                Roadmap.user_id == user.id, Roadmap.subject_id == subj.id
            )
        )
    ).scalar_one_or_none()
    if not rm:
        rm = await _build_roadmap(db, user.id, subj, user.exam_target_date)

    return RoadmapOut(
        id=rm.id,
        subject_id=subj.id,
        subject_slug=subj.slug,
        user_id=user.id,
        generated_at=rm.generated_at,
        weeks_total=_weeks_total(rm.milestones),
        on_track=_on_track(rm.milestones),
        milestones=[MilestoneOut(**m) for m in rm.milestones],
    )


@router.post(
    "/roadmap/{subject_id_or_slug}/regenerate",
    response_model=RoadmapOut,
    summary="Regenerate roadmap after a new exam/mastery update",
)
async def regenerate_roadmap(
    subject_id_or_slug: str, user: CurrentUser, db: DbSession
) -> RoadmapOut:
    subj = await _resolve_subject(db, subject_id_or_slug)
    rm = await _build_roadmap(db, user.id, subj, user.exam_target_date)
    return RoadmapOut(
        id=rm.id,
        subject_id=subj.id,
        subject_slug=subj.slug,
        user_id=user.id,
        generated_at=rm.generated_at,
        weeks_total=_weeks_total(rm.milestones),
        on_track=_on_track(rm.milestones),
        milestones=[MilestoneOut(**m) for m in rm.milestones],
    )


@router.get(
    "/roadmap/{subject_id_or_slug}/milestones/{topic_id_or_slug}",
    response_model=MilestoneDetailOut,
)
async def get_milestone_detail(
    subject_id_or_slug: str,
    topic_id_or_slug: str,
    user: CurrentUser,
    db: DbSession,
) -> MilestoneDetailOut:
    subj = await _resolve_subject(db, subject_id_or_slug)
    # Find topic by id or slug
    stmt = select(Topic).where(Topic.subject_id == subj.id)
    try:
        tid = uuid.UUID(topic_id_or_slug)
        stmt = stmt.where(Topic.id == tid)
    except ValueError:
        stmt = stmt.where(Topic.slug == topic_id_or_slug)
    topic = (await db.execute(stmt)).scalar_one_or_none()
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        )

    # Find milestone entry
    rm = (
        await db.execute(
            select(Roadmap).where(
                Roadmap.user_id == user.id, Roadmap.subject_id == subj.id
            )
        )
    ).scalar_one_or_none()
    if not rm:
        rm = await _build_roadmap(db, user.id, subj, user.exam_target_date)

    entry = next(
        (m for m in rm.milestones if m.get("topic_id") == str(topic.id)), None
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not in current roadmap",
        )

    # Practice questions for this topic
    q_ids = (
        await db.execute(
            select(Question.id)
            .where(Question.topic_id == topic.id)
            .order_by(Question.difficulty)
            .limit(10)
        )
    ).scalars().all()

    # Children
    children = (
        await db.execute(select(Topic.id).where(Topic.parent_id == topic.id))
    ).scalars().all()

    prereq_uuids = []
    for raw in topic.prerequisites or []:
        try:
            prereq_uuids.append(uuid.UUID(raw) if isinstance(raw, str) else uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue

    return MilestoneDetailOut(
        milestone=MilestoneOut(**entry),
        practice_question_ids=list(q_ids),
        prerequisites=prereq_uuids,
        children=list(children),
    )


@router.get("/roadmap/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "roadmap", "status": "ok"}
