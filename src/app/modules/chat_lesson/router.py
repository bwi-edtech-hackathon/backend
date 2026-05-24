"""Chat lesson session CRUD. SSE streaming lives in /sse/chat_lesson.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select

from app.core.deps import CurrentUser, DbSession
from app.core.slugs import short_slug, slugify
from app.models.catalog import Question, Subject, SubjectCode, Topic
from app.models.chat import (
    ChatMessage,
    ChatMessageRole,
    ChatSession,
    ChatSessionStatus,
    ChatTrigger,
)
from app.models.exam import ExamAnswer, ExamAttempt, ExamStatus
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
    topic_name_ru: str | None
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
        topic_name_ru=topic.name_ru if topic else None,
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


# ════════════════════════════════════════════════════════════════════════════
# Frontend-shaped layer — matches lib/api.ts in the React client.
# Mounted under /api/chat (separate from /api/v1/chat-lesson) so the legacy
# routes stay intact.
# ════════════════════════════════════════════════════════════════════════════

_FE_CFG = ConfigDict(populate_by_name=True, from_attributes=True)


class _CamelModel(BaseModel):
    model_config = _FE_CFG


class _ChatSessionSummary(_CamelModel):
    id: str
    topic: str
    preview: str
    when: str
    status: str    # "active" | "mastered" | "struggling" | "in_progress"
    subject: str | None = None    # SubjectCode string (e.g. "MATH", "HIST")


class _ChatMessageOut(_CamelModel):
    id: str
    role: str       # "coach" | "user"
    text: str
    created_at: int = Field(alias="createdAt")


class _CreateChatIn(BaseModel):
    topic: str | None = None
    subject: str | None = None     # default MATH


fe_router = APIRouter(prefix="/api/coach", tags=["chat-lesson-frontend"])


def _ago(dt: datetime) -> str:
    if dt.tzinfo is None:
        now = datetime.utcnow()
    else:
        now = datetime.now(UTC)
    seconds = (now - dt).total_seconds()
    if seconds < 60:
        return "Now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d"
    return "Old"


def _status_label(sess: ChatSession) -> str:
    if sess.status == ChatSessionStatus.ACTIVE:
        return "active"
    if sess.mastery_estimate >= 80:
        return "mastered"
    if sess.mastery_estimate < 40:
        return "struggling"
    return "in_progress"


async def _ensure_topic_for_user(
    db, topic_name: str, subject_code: str = "MATH"
) -> Topic:
    """Find a topic by English name (case-insensitive) under the given subject.
    Creates one on the fly if missing — keeps the demo unblocked when the user
    types a free-form topic in the chat sidebar."""
    try:
        code = SubjectCode(subject_code.upper())
    except ValueError:
        code = SubjectCode.MATH
    subject = (
        await db.execute(select(Subject).where(Subject.code == code))
    ).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not seeded")
    slug = slugify(topic_name)[:78]
    topic = (
        await db.execute(
            select(Topic).where(Topic.subject_id == subject.id, Topic.slug == slug)
        )
    ).scalar_one_or_none()
    if topic:
        return topic
    topic = Topic(
        subject_id=subject.id,
        slug=slug,
        depth=2,
        name_uz=topic_name,
        name_ru=topic_name,
        name_en=topic_name,
        weight=Decimal("0.5"),
    )
    db.add(topic)
    await db.flush()
    await db.commit()
    await db.refresh(topic)
    return topic


@fe_router.get("/sessions", response_model=list[_ChatSessionSummary])
async def fe_list_sessions(
    user: CurrentUser, db: DbSession, limit: int = 20
) -> list[_ChatSessionSummary]:
    rows = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(desc(ChatSession.started_at))
            .limit(limit)
        )
    ).scalars().all()
    subject_ids = {s.subject_id for s in rows if s.subject_id}
    subjects = (
        (
            await db.execute(select(Subject).where(Subject.id.in_(subject_ids)))
        ).scalars().all()
        if subject_ids
        else []
    )
    smap = {s.id: s for s in subjects}
    out: list[_ChatSessionSummary] = []
    for sess in rows:
        topic = None
        if sess.topic_id:
            topic = (
                await db.execute(select(Topic).where(Topic.id == sess.topic_id))
            ).scalar_one_or_none()
        # Pull the last user/coach message for preview.
        last_msg = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == sess.id)
                .order_by(desc(ChatMessage.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        preview = (last_msg.content[:60] + "…") if last_msg and len(last_msg.content) > 60 else (last_msg.content if last_msg else "Just started")
        subj = smap.get(sess.subject_id)
        out.append(
            _ChatSessionSummary(
                id=str(sess.id),
                topic=(topic.name_en if topic else "General"),
                preview=preview,
                when=_ago(sess.started_at),
                status=_status_label(sess),
                subject=subj.code.value if subj else None,
            )
        )
    return out


class _CreateFromExamIn(BaseModel):
    exam_session_id: str | None = None


@fe_router.post(
    "/sessions/from-exam",
    response_model=_ChatSessionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a chat session seeded with the user's wrong-answer breakdown.",
)
async def fe_create_session_from_exam(
    payload: _CreateFromExamIn, user: CurrentUser, db: DbSession
) -> _ChatSessionSummary:
    """Spawn a fresh chat session anchored to the most recent (or specified)
    graded exam attempt. The session is pre-populated with a system message
    summarizing the wrong answers + weakest topics, so the AI coach has full
    context when the user opens the chat from the exam result page."""
    attempt: ExamAttempt | None = None
    if payload.exam_session_id:
        try:
            aid = uuid.UUID(payload.exam_session_id)
            attempt = (
                await db.execute(
                    select(ExamAttempt).where(
                        ExamAttempt.id == aid, ExamAttempt.user_id == user.id
                    )
                )
            ).scalar_one_or_none()
        except ValueError:
            attempt = (
                await db.execute(
                    select(ExamAttempt).where(
                        ExamAttempt.slug == payload.exam_session_id,
                        ExamAttempt.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
    if attempt is None:
        attempt = (
            await db.execute(
                select(ExamAttempt)
                .where(ExamAttempt.user_id == user.id)
                .order_by(desc(ExamAttempt.started_at))
                .limit(1)
            )
        ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(status_code=404, detail="No exam attempts to review")

    # Look up the subject (for naming) + the weakest topic to anchor the session.
    subject = (
        await db.execute(select(Subject).where(Subject.id == attempt.subject_id))
    ).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=500, detail="Subject missing for attempt")

    anchor_topic: Topic | None = None
    weakest_entries = list(attempt.weakest_topics or [])
    if weakest_entries:
        first = weakest_entries[0]
        try:
            tid = uuid.UUID(first.get("topic_id"))
            anchor_topic = (
                await db.execute(select(Topic).where(Topic.id == tid))
            ).scalar_one_or_none()
        except (ValueError, TypeError):
            anchor_topic = None
    if anchor_topic is None:
        # Fall back to any topic on the attempt's question layout.
        layout = attempt.question_layout or []
        if layout:
            try:
                tid = uuid.UUID(layout[0]["topic_id"])
                anchor_topic = (
                    await db.execute(select(Topic).where(Topic.id == tid))
                ).scalar_one_or_none()
            except (ValueError, KeyError, TypeError):
                anchor_topic = None
    if anchor_topic is None:
        anchor_topic = await _ensure_topic_for_user(
            db, "Exam review", subject.code.value
        )

    mastery = (
        await db.execute(
            select(MasteryTopic).where(
                MasteryTopic.user_id == user.id,
                MasteryTopic.topic_id == anchor_topic.id,
            )
        )
    ).scalar_one_or_none()
    mastery_pct = float(mastery.mastery_pct) if mastery else 0.0

    sess = ChatSession(
        slug=short_slug(f"exam-review-{attempt.slug}"),
        user_id=user.id,
        subject_id=subject.id,
        topic_id=anchor_topic.id,
        trigger=ChatTrigger.REACTIVE,
        status=ChatSessionStatus.ACTIVE,
        mastery_at_start=Decimal(f"{mastery_pct:.2f}"),
        mastery_estimate=Decimal(f"{mastery_pct:.2f}"),
        started_at=_now(),
    )
    db.add(sess)
    await db.flush()

    # Gather wrong-answer details so we can give Gemini structured context.
    answers = (
        await db.execute(
            select(ExamAnswer)
            .where(ExamAnswer.attempt_id == attempt.id)
            .order_by(ExamAnswer.question_index)
        )
    ).scalars().all()
    wrong = [a for a in answers if a.is_correct is False]
    qids = {a.question_id for a in wrong}
    questions = (
        (await db.execute(select(Question).where(Question.id.in_(qids)))).scalars().all()
        if qids
        else []
    )
    qmap = {q.id: q for q in questions}
    topic_ids = {q.topic_id for q in questions}
    topics = (
        (await db.execute(select(Topic).where(Topic.id.in_(topic_ids)))).scalars().all()
        if topic_ids
        else []
    )
    tmap = {t.id: t for t in topics}

    # Aggregate wrong answers by topic for a compact summary.
    by_topic: dict[str, int] = {}
    for a in wrong:
        q = qmap.get(a.question_id)
        if not q:
            continue
        t = tmap.get(q.topic_id)
        label = t.name_en if t else "Unknown topic"
        by_topic[label] = by_topic.get(label, 0) + 1

    # System message: high-level exam summary.
    grade_label = attempt.grade.value if attempt.grade else "—"
    score = float(attempt.rasch_score) if attempt.rasch_score is not None else 0.0
    summary_lines = [
        f"Exam review session — {attempt.kind.value} in {subject.name_en}.",
        f"Result: {score:.1f} Rasch · grade {grade_label} "
        f"({sum(1 for a in answers if a.is_correct)}/{len(answers)} correct).",
    ]
    if by_topic:
        topic_summary = ", ".join(
            f"{name} ({n} wrong)"
            for name, n in sorted(by_topic.items(), key=lambda kv: -kv[1])[:6]
        )
        summary_lines.append(f"Wrong-answer topics: {topic_summary}.")
    if weakest_entries:
        topic_pct_lines: list[str] = []
        for entry in weakest_entries[:5]:
            tid_raw = entry.get("topic_id")
            try:
                tid = uuid.UUID(tid_raw) if tid_raw else None
            except (ValueError, TypeError):
                tid = None
            t = tmap.get(tid) if tid else None
            if not t and tid:
                t = (
                    await db.execute(select(Topic).where(Topic.id == tid))
                ).scalar_one_or_none()
            if not t:
                continue
            topic_pct_lines.append(f"{t.name_en} {float(entry.get('pct', 0.0)):.0f}%")
        if topic_pct_lines:
            summary_lines.append(
                "Weakest topics by accuracy: " + "; ".join(topic_pct_lines) + "."
            )
    summary_lines.append(
        f"Start by anchoring on {anchor_topic.name_en} — it had the highest impact "
        "on the final score."
    )
    summary_content = "\n".join(summary_lines)
    db.add(
        ChatMessage(
            session_id=sess.id,
            role=ChatMessageRole.SYSTEM,
            content=summary_content,
            parts=[],
            token_count=len(summary_content.split()),
        )
    )

    # Coach opener — what the user will see when they land on the page.
    opener_lines = [
        f"Let's review your last {subject.name_en.lower()} mock together.",
    ]
    if by_topic:
        top_topics = ", ".join(
            name for name, _ in sorted(by_topic.items(), key=lambda kv: -kv[1])[:3]
        )
        opener_lines.append(
            f"You slipped most on **{top_topics}** — we'll start there."
        )
    opener_lines.append(
        f"Looking at **{anchor_topic.name_en}** first: what does the topic remind you of? "
        "Tell me one concept or formula you remember from it."
    )
    opener = "\n\n".join(opener_lines)
    db.add(
        ChatMessage(
            session_id=sess.id,
            role=ChatMessageRole.COACH,
            content=opener,
            parts=[{"type": "token", "content": opener}],
            token_count=len(opener.split()),
        )
    )

    await db.commit()
    await db.refresh(sess)

    return _ChatSessionSummary(
        id=str(sess.id),
        topic=f"Exam review · {anchor_topic.name_en}",
        preview=opener_lines[0],
        when="Now",
        status="active",
        subject=subject.code.value,
    )


@fe_router.post(
    "/sessions",
    response_model=_ChatSessionSummary,
    status_code=status.HTTP_201_CREATED,
)
async def fe_create_session(
    payload: _CreateChatIn, user: CurrentUser, db: DbSession
) -> _ChatSessionSummary:
    topic_name = (payload.topic or "New Chat").strip() or "New Chat"
    subject_code = payload.subject or "MATH"
    topic = await _ensure_topic_for_user(db, topic_name, subject_code)
    mastery = (
        await db.execute(
            select(MasteryTopic).where(
                MasteryTopic.user_id == user.id, MasteryTopic.topic_id == topic.id
            )
        )
    ).scalar_one_or_none()
    mastery_pct = float(mastery.mastery_pct) if mastery else 0.0
    sess = ChatSession(
        slug=short_slug(f"chat-{topic.slug}"),
        user_id=user.id,
        subject_id=topic.subject_id,
        topic_id=topic.id,
        trigger=ChatTrigger.PROACTIVE,
        status=ChatSessionStatus.ACTIVE,
        mastery_at_start=Decimal(f"{mastery_pct:.2f}"),
        mastery_estimate=Decimal(f"{mastery_pct:.2f}"),
        started_at=_now(),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    subj_row = (
        await db.execute(select(Subject).where(Subject.id == topic.subject_id))
    ).scalar_one_or_none()
    return _ChatSessionSummary(
        id=str(sess.id),
        topic=topic.name_en,
        preview="Just started",
        when="Now",
        status="active",
        subject=subj_row.code.value if subj_row else None,
    )


@fe_router.post(
    "/sessions/{session_id_or_slug}/end",
    response_model=_ChatSessionSummary,
)
async def fe_end_session(
    session_id_or_slug: str, user: CurrentUser, db: DbSession
) -> _ChatSessionSummary:
    sess = await _load_session(db, session_id_or_slug, user.id)
    if sess.status == ChatSessionStatus.ACTIVE:
        sess.status = ChatSessionStatus.ENDED
        sess.ended_at = _now()
        await db.commit()
        await db.refresh(sess)
    topic = (
        await db.execute(select(Topic).where(Topic.id == sess.topic_id))
    ).scalar_one_or_none() if sess.topic_id else None
    subj_row = (
        await db.execute(select(Subject).where(Subject.id == sess.subject_id))
    ).scalar_one_or_none() if sess.subject_id else None
    return _ChatSessionSummary(
        id=str(sess.id),
        topic=topic.name_en if topic else "General",
        preview="Session ended",
        when=_ago(sess.started_at),
        status=_status_label(sess),
        subject=subj_row.code.value if subj_row else None,
    )


@fe_router.post(
    "/sessions/{session_id_or_slug}/understood",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def fe_mark_understood(
    session_id_or_slug: str, user: CurrentUser, db: DbSession
) -> None:
    sess = await _load_session(db, session_id_or_slug, user.id)
    # Nudge the mastery estimate forward — a no-op if already high.
    new_pct = min(100.0, float(sess.mastery_estimate) + 10.0)
    sess.mastery_estimate = Decimal(f"{new_pct:.2f}")
    db.add(
        ChatMessage(
            session_id=sess.id,
            role=ChatMessageRole.SYSTEM,
            content="Student marked understood.",
            parts=[],
            token_count=0,
        )
    )
    await db.commit()


@fe_router.post("/sessions/{session_id_or_slug}/messages", response_model=_ChatMessageOut)
async def fe_send_message(
    session_id_or_slug: str,
    payload: dict,
    user: CurrentUser,
    db: DbSession,
) -> _ChatMessageOut:
    """Non-streaming reply for clients that don't want to consume SSE. Always
    available, but prefer the SSE endpoint at `/api/v1/chat-lesson/sessions/{id}/messages`
    for the real Gemini-powered tutor experience."""
    text = (payload.get("text") or payload.get("content") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")
    sess = await _load_session(db, session_id_or_slug, user.id)
    if sess.status != ChatSessionStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Session ended")

    db.add(
        ChatMessage(
            session_id=sess.id,
            role=ChatMessageRole.USER,
            content=text,
            parts=[],
            token_count=len(text.split()),
        )
    )
    reply = _socratic_reply(text)
    coach_msg = ChatMessage(
        session_id=sess.id,
        role=ChatMessageRole.COACH,
        content=reply,
        parts=[{"type": "token", "content": reply}],
        token_count=len(reply.split()),
    )
    db.add(coach_msg)
    await db.commit()
    await db.refresh(coach_msg)
    return _ChatMessageOut(
        id=str(coach_msg.id),
        role="coach",
        text=reply,
        createdAt=int(coach_msg.created_at.timestamp() * 1000),
    )


def _socratic_reply(user_text: str) -> str:
    lc = user_text.lower().strip()
    if not lc:
        return "Take your time. What part of the problem feels stuck?"
    if any(k in lc for k in ("yes", "yeah", "yep", "ok", "okay")):
        return "Good. Now apply D = b² − 4ac. What do you get with a = 1, b = -5, c = 6?"
    if any(k in lc for k in ("no", "don't", "idk", "not sure")):
        return "No problem — let's slow down. Start from ax² + bx + c = 0. What are a, b, c in your equation?"
    if "=" in lc or any(ch.isdigit() for ch in lc):
        return "Nice work. Try one more step: plug those values into the quadratic formula and tell me what you get for x."
    return "Interesting. Can you walk me through the next step you'd try, and why?"


# Re-export for main.py to register.
__all__ = ["router", "fe_router"]
