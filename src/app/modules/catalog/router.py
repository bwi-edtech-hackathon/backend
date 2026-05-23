"""Catalog routes — subjects + topics. Read endpoints implemented for MVP."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.deps import DbSession
from app.models.catalog import Subject, Topic

router = APIRouter(prefix="/api/v1", tags=["catalog"])


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    slug: str
    name_uz: str
    name_ru: str
    name_en: str
    has_essay: bool
    order_index: int


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    subject_id: uuid.UUID
    parent_id: uuid.UUID | None
    slug: str
    code: str | None
    depth: int
    order_index: int
    name_uz: str
    name_ru: str
    name_en: str
    weight: float
    prerequisites: list


@router.get("/subjects", response_model=list[SubjectOut])
async def list_subjects(db: DbSession) -> list[SubjectOut]:
    res = await db.execute(select(Subject).order_by(Subject.order_index, Subject.code))
    return [SubjectOut.model_validate(s) for s in res.scalars().all()]


@router.get("/subjects/{subject_id_or_slug}", response_model=SubjectOut)
async def get_subject(subject_id_or_slug: str, db: DbSession) -> SubjectOut:
    stmt = select(Subject)
    try:
        sid = uuid.UUID(subject_id_or_slug)
        stmt = stmt.where(Subject.id == sid)
    except ValueError:
        stmt = stmt.where(Subject.slug == subject_id_or_slug)
    subject = (await db.execute(stmt)).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    return SubjectOut.model_validate(subject)


@router.get("/subjects/{subject_id_or_slug}/topics", response_model=list[TopicOut])
async def list_topics(subject_id_or_slug: str, db: DbSession) -> list[TopicOut]:
    # Resolve subject
    stmt_s = select(Subject)
    try:
        sid = uuid.UUID(subject_id_or_slug)
        stmt_s = stmt_s.where(Subject.id == sid)
    except ValueError:
        stmt_s = stmt_s.where(Subject.slug == subject_id_or_slug)
    subject = (await db.execute(stmt_s)).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    res = await db.execute(
        select(Topic)
        .where(Topic.subject_id == subject.id)
        .order_by(Topic.depth, Topic.order_index)
    )
    return [TopicOut.model_validate(t) for t in res.scalars().all()]


@router.get("/topics/{topic_id_or_slug}", response_model=TopicOut)
async def get_topic(topic_id_or_slug: str, db: DbSession) -> TopicOut:
    stmt = select(Topic)
    try:
        tid = uuid.UUID(topic_id_or_slug)
        stmt = stmt.where(Topic.id == tid)
    except ValueError:
        stmt = stmt.where(Topic.slug == topic_id_or_slug)
    topic = (await db.execute(stmt)).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    return TopicOut.model_validate(topic)
