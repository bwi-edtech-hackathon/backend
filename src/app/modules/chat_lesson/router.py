"""Chat lesson session CRUD. SSE streaming lives in /sse/chat_lesson.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from app.core.deps import CurrentUser, DbSession
from app.core.slugs import short_slug
from app.models.catalog import Topic
from app.models.chat import (
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    ChatTrigger,
)
from app.models.progress import MasteryTopic

router = APIRouter(prefix="/api/v1/chat-lesson", tags=["chat-lesson"])


# === Schemas ===
class CreateSessionIn(BaseModel):
    topic_id: uuid.UUID
    trigger: str = "proactive"


class SessionOut(BaseModel):
    id: uuid.UUID
    slug: str
    user_id: uuid.UUID
    subject_id: uuid.UUID
    topic_id: uuid.UUID | None
    topic_name_uz: str | None
    topic_name_en: str | None
    trigger: str
    status: str
    mastery_at_start: float
    mastery_estimate: float
    started_at: datetime
    ended_at: datetime | None
    message_count: int


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    parts: list
    token_count: int
    created_at: datetime


class SessionDetailOut(BaseModel):
    session: SessionOut
    messages: list[MessageOut]


# === Helpers ===
def _now() -> datetime:
    return datetime.now(UTC)


async def _load_session(db, session_id_or_slug: str, user_id: uuid.UUID) -> ChatSession:
    stmt = select(ChatSession)
    try:
        sid = uuid.UUID(session_id_or_slug)
        stmt = stmt.where(ChatSession.id == sid)
    except ValueError:
        stmt = stmt.where(ChatSession.slug == session_id_or_slug)
    sess = (await db.execute(stmt)).scalar_one_or_none()
    if not sess or sess.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return sess


async def _session_to_out(db, sess: ChatSession) -> SessionOut:
    topic = None
    if sess.topic_id:
        topic = (
            await db.execute(select(Topic).where(Topic.id == sess.topic_id))
        ).scalar_one_or_none()
    msg_count = (
        await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == sess.id)
        )
    ).scalars().all()
    return SessionOut(
        id=sess.id,
        slug=sess.slug,
        user_id=sess.user_id,
        subject_id=sess.subject_id,
        topic_id=sess.topic_id,
        topic_name_uz=topic.name_uz if topic else None,
        topic_name_en=topic.name_en if topic else None,
        trigger=sess.trigger.value,
        status=sess.status.value,
        mastery_at_start=float(sess.mastery_at_start),
        mastery_estimate=float(sess.mastery_estimate),
        started_at=sess.started_at,
        ended_at=sess.ended_at,
        message_count=len(msg_count),
    )


# === Endpoints ===
@router.post(
    "/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED
)
async def create_session(
    payload: CreateSessionIn, user: CurrentUser, db: DbSession
) -> SessionOut:
    topic = (
        await db.execute(select(Topic).where(Topic.id == payload.topic_id))
    ).scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Snapshot mastery
    mastery = (
        await db.execute(
            select(MasteryTopic).where(
                MasteryTopic.user_id == user.id, MasteryTopic.topic_id == topic.id
            )
        )
    ).scalar_one_or_none()
    mastery_pct = float(mastery.mastery_pct) if mastery else 0.0

    try:
        trig = ChatTrigger(payload.trigger.lower())
    except ValueError:
        trig = ChatTrigger.PROACTIVE

    sess = ChatSession(
        slug=short_slug(f"chat-{topic.slug}"),
        user_id=user.id,
        subject_id=topic.subject_id,
        topic_id=topic.id,
        trigger=trig,
        status=ChatSessionStatus.ACTIVE,
        mastery_at_start=Decimal(f"{mastery_pct:.2f}"),
        mastery_estimate=Decimal(f"{mastery_pct:.2f}"),
        started_at=_now(),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return await _session_to_out(db, sess)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    user: CurrentUser, db: DbSession, limit: int = 20
) -> list[SessionOut]:
    rows = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(desc(ChatSession.started_at))
            .limit(limit)
        )
    ).scalars().all()
    return [await _session_to_out(db, s) for s in rows]


@router.get("/sessions/{session_id_or_slug}", response_model=SessionDetailOut)
async def get_session(
    session_id_or_slug: str, user: CurrentUser, db: DbSession
) -> SessionDetailOut:
    sess = await _load_session(db, session_id_or_slug, user.id)
    out = await _session_to_out(db, sess)
    msgs = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == sess.id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()
    return SessionDetailOut(
        session=out,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role.value,
                content=m.content,
                parts=m.parts,
                token_count=m.token_count,
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )


@router.post(
    "/sessions/{session_id_or_slug}/end", response_model=SessionOut
)
async def end_session(
    session_id_or_slug: str,
    user: CurrentUser,
    db: DbSession,
    outcome: str = "ended",
) -> SessionOut:
    sess = await _load_session(db, session_id_or_slug, user.id)
    if sess.status == ChatSessionStatus.ACTIVE:
        sess.status = (
            ChatSessionStatus.ABANDONED
            if outcome == "abandoned"
            else ChatSessionStatus.ENDED
        )
        sess.ended_at = _now()
        await db.commit()
        await db.refresh(sess)
    return await _session_to_out(db, sess)


@router.get("/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "chat_lesson", "status": "ok"}
