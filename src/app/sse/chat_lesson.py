"""Chat lesson SSE endpoint — real Gemini streaming with structured event parsing.

Endpoint: POST /sse/chat-lesson/sessions/{session_id_or_slug}/messages
Returns: text/event-stream

Event types (per spec §6.4 / §8.3):
  - token        {"content": "Let's"}
  - math_inline  {"latex": "x^2"}
  - math_block   {"latex": "\\int_0^1 f(x) dx"}
  - math_pill    {"latex": "x^2 - 5x + 6 = 0"}  // bordered pill formula
  - diagram      {"mermaid": "graph TD; A-->B"}
  - done         {"messageId": "uuid", "tokenCount": int}
  - error        {"code": "...", "message": "..."}

When GEMINI_API_KEY is set, streams from Gemini with a Socratic system prompt
and live-parses LaTeX / mermaid blocks out of the token stream.
When the key is absent, falls back to a deterministic mock stream.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUserId
from app.models.catalog import Subject, Topic
from app.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus

router = APIRouter(prefix="/api/v1/chat-lesson", tags=["chat-lesson-stream"])


SYSTEM_PROMPT = """You are a patient, knowledgeable Socratic tutor for Uzbekistan's
Milliy Sertifikat exam preparation. Subject: {subject}. Topic: {topic}.
Student's current mastery estimate: {mastery_pct}%. Student's language: {language}.

CRITICAL RULES:
1. NEVER lecture. Always ask questions to lead the student to the answer.
2. Take the smallest possible step. If the student is stuck, ask an easier question.
3. Use the student's language ({language}). If they switch, follow them.
4. Render math with LaTeX inside $...$ for inline, $$...$$ for blocks.
5. After ~5 successful exchanges, propose a verification problem.
6. End the session when the student demonstrates mastery.

NEVER:
- Give the answer directly
- Praise without verifying understanding
- Switch topics mid-session
- Solve their homework or practice questions verbatim
"""

INLINE_MATH = re.compile(r"\$([^$]+?)\$")
BLOCK_MATH = re.compile(r"\$\$([\s\S]+?)\$\$")
MERMAID_BLOCK = re.compile(r"```mermaid\n([\s\S]+?)```")


async def _load_context(session_id_or_slug: str, user_id: uuid.UUID):
    async for db in get_db():
        stmt = select(ChatSession)
        try:
            sid = uuid.UUID(session_id_or_slug)
            stmt = stmt.where(ChatSession.id == sid)
        except ValueError:
            stmt = stmt.where(ChatSession.slug == session_id_or_slug)
        sess = (await db.execute(stmt)).scalar_one_or_none()
        if not sess or sess.user_id != user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.status != ChatSessionStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="Session is not active")

        subject = (
            await db.execute(select(Subject).where(Subject.id == sess.subject_id))
        ).scalar_one()
        topic = None
        if sess.topic_id:
            topic = (
                await db.execute(select(Topic).where(Topic.id == sess.topic_id))
            ).scalar_one_or_none()

        history = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == sess.id)
                .order_by(ChatMessage.created_at)
            )
        ).scalars().all()
        return sess, subject, topic, list(history)
    raise HTTPException(status_code=500, detail="DB unavailable")


async def _save_message(
    session_id: uuid.UUID,
    role: ChatMessageRole,
    content: str,
    parts: list,
    token_count: int,
) -> uuid.UUID:
    async for db in get_db():
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            parts=parts,
            token_count=token_count,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg.id
    return uuid.uuid4()


def _parse_structured(buf: str) -> tuple[list[tuple[str, dict]], str]:
    """Extract complete math/mermaid blocks from buffer. Return (events, remainder)."""
    events: list[tuple[str, dict]] = []
    remainder = buf

    # Block math first (greedy)
    while True:
        m = BLOCK_MATH.search(remainder)
        if not m:
            break
        if m.start() > 0:
            events.append(("token", {"content": remainder[: m.start()]}))
        events.append(("math_block", {"latex": m.group(1).strip()}))
        remainder = remainder[m.end() :]

    # Mermaid diagrams
    while True:
        m = MERMAID_BLOCK.search(remainder)
        if not m:
            break
        if m.start() > 0:
            events.append(("token", {"content": remainder[: m.start()]}))
        events.append(("diagram", {"mermaid": m.group(1).strip()}))
        remainder = remainder[m.end() :]

    # Inline math
    while True:
        m = INLINE_MATH.search(remainder)
        if not m:
            break
        if m.start() > 0:
            events.append(("token", {"content": remainder[: m.start()]}))
        events.append(("math_inline", {"latex": m.group(1).strip()}))
        remainder = remainder[m.end() :]

    return events, remainder


async def _gemini_stream(
    prompt: str, system: str, history: list[ChatMessage]
) -> AsyncIterator[str]:
    """Yield raw text chunks from Gemini."""
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name=settings.gemini_model,
        system_instruction=system,
    )
    chat_history = []
    for m in history:
        role = "user" if m.role == ChatMessageRole.USER else "model"
        chat_history.append({"role": role, "parts": [m.content]})

    chat = model.start_chat(history=chat_history)
    response = await asyncio.to_thread(chat.send_message, prompt, stream=True)
    for chunk in response:
        text = getattr(chunk, "text", "") or ""
        if text:
            yield text


async def _stub_stream() -> AsyncIterator[str]:
    parts = [
        "Let's take a look — what type of equation is ",
        "$x^2 - 5x + 6 = 0$",
        "? Take a moment and ",
        "tell me the form you recognise.",
    ]
    for p in parts:
        await asyncio.sleep(0.15)
        yield p


@router.post("/sessions/{session_id_or_slug}/messages")
async def stream_message(
    session_id_or_slug: str,
    user_id: CurrentUserId,
    payload: dict = Body(...),
) -> EventSourceResponse:
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")

    sess, subject, topic, history = await _load_context(session_id_or_slug, user_id)

    # Persist the user message immediately
    await _save_message(
        sess.id, ChatMessageRole.USER, content, parts=[], token_count=len(content.split())
    )

    system_prompt = SYSTEM_PROMPT.format(
        subject=subject.name_en,
        topic=topic.name_en if topic else "general",
        mastery_pct=float(sess.mastery_estimate),
        language={"uz": "Uzbek", "ru": "Russian", "en": "English"}.get("en", "Uzbek"),
    )

    async def _generator() -> AsyncIterator[dict]:
        full_text = ""
        emitted_parts: list[dict] = []
        buffer = ""
        token_count = 0

        try:
            if settings.gemini_enabled:
                text_iter = _gemini_stream(content, system_prompt, history)
            else:
                text_iter = _stub_stream()

            async for chunk in text_iter:
                full_text += chunk
                buffer += chunk
                events, remainder = _parse_structured(buffer)
                if events:
                    for evt, data in events:
                        emitted_parts.append({"type": evt, **data})
                        token_count += len(str(data).split())
                        yield {"event": evt, "data": json.dumps(data)}
                    buffer = remainder
                else:
                    # Flush any safe (non-dollar, non-backtick) prefix as tokens
                    safe_idx = len(buffer)
                    for i, ch in enumerate(buffer):
                        if ch in "$`":
                            safe_idx = i
                            break
                    if safe_idx > 0:
                        text = buffer[:safe_idx]
                        emitted_parts.append({"type": "token", "content": text})
                        token_count += len(text.split())
                        yield {"event": "token", "data": json.dumps({"content": text})}
                        buffer = buffer[safe_idx:]

            # Flush remainder
            if buffer.strip():
                emitted_parts.append({"type": "token", "content": buffer})
                token_count += len(buffer.split())
                yield {"event": "token", "data": json.dumps({"content": buffer})}

            msg_id = await _save_message(
                sess.id,
                ChatMessageRole.COACH,
                full_text,
                emitted_parts,
                token_count,
            )

            yield {
                "event": "done",
                "data": json.dumps(
                    {"messageId": str(msg_id), "tokenCount": token_count}
                ),
            }
        except Exception as e:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json.dumps({"code": "STREAM_ERROR", "message": str(e)}),
            }

    return EventSourceResponse(_generator())
