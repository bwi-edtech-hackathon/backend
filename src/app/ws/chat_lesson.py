"""Chat lesson WebSocket — Gemini streaming via WS instead of SSE.

Endpoint: wss://api.coachai.uz/ws/chat-lesson/sessions/{session_id_or_slug}?token=<access_jwt>

Wire protocol (server → client, one JSON object per frame):
    {"event": "token",        "data": {"content": "..."}}
    {"event": "math_inline",  "data": {"latex": "..."}}
    {"event": "math_block",   "data": {"latex": "..."}}
    {"event": "diagram",      "data": {"mermaid": "..."}}
    {"event": "done",         "data": {"messageId": "uuid", "tokenCount": int}}
    {"event": "error",        "data": {"code": "...", "message": "..."}}

Client → server:
    {"type": "message", "content": "user's typed text"}     — only one per socket
    {"type": "ping"}                                         — keepalive (server replies "pong")

The reply-streaming logic is shared with the SSE endpoint in app/sse/chat_lesson.py
so behaviour stays in sync: same Gemini prompt, same structured-event parser,
same persistence. The only difference is the transport.
"""

from __future__ import annotations

import json
import uuid

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import _ensure_demo_user
from app.core.security import decode_token
from app.models.chat import ChatMessageRole
from app.sse.chat_lesson import (
    SYSTEM_PROMPT,
    _build_context_turns,
    _gemini_stream,
    _load_context,
    _parse_structured,
    _save_message,
    _stub_stream,
)

router = APIRouter()


async def _resolve_user_id(token: str | None) -> uuid.UUID:
    """Same auth fallback the battles WS uses: bearer token first, demo user
    second — keeps demo mode functional without forcing a real login."""
    if token:
        try:
            payload = decode_token(token, expected_type="access")
            return uuid.UUID(payload["sub"])
        except (jwt.InvalidTokenError, KeyError, ValueError):
            pass
    async for db in get_db():
        demo = await _ensure_demo_user(db)
        return demo.id
    raise RuntimeError("DB unavailable for demo user lookup")


async def _send_event(ws: WebSocket, event: str, data: dict) -> None:
    if ws.client_state == WebSocketState.CONNECTED:
        await ws.send_text(json.dumps({"event": event, "data": data}))


@router.websocket("/ws/chat-lesson/sessions/{session_id_or_slug}")
async def chat_lesson_ws(
    websocket: WebSocket,
    session_id_or_slug: str,
    token: str | None = Query(default=None),
) -> None:
    await websocket.accept()

    try:
        user_id = await _resolve_user_id(token)
    except Exception as e:  # noqa: BLE001
        await _send_event(
            websocket,
            "error",
            {"code": "AUTH_FAILED", "message": str(e)},
        )
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    try:
        sess, subject, topic, history, weak_topics = await _load_context(
            session_id_or_slug, user_id
        )
    except Exception as e:  # noqa: BLE001
        # _load_context raises HTTPException for 404/409 — surface as an error
        # event so the frontend can show a toast instead of just closing silently.
        await _send_event(
            websocket,
            "error",
            {"code": "SESSION_UNAVAILABLE", "message": str(getattr(e, "detail", e))},
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    system_prompt = SYSTEM_PROMPT.format(language="Uzbek")
    context_turns = _build_context_turns(
        subject=subject,
        topic=topic,
        mastery_pct=float(sess.mastery_estimate),
        weak_topics=weak_topics,
    )

    try:
        # The protocol expects exactly one user message per socket — keep
        # reading until we either get one or the client disconnects (allows
        # pings before the real message).
        content: str | None = None
        while content is None:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_event(
                    websocket,
                    "error",
                    {"code": "INVALID_JSON", "message": "bad payload"},
                )
                continue
            mtype = msg.get("type")
            if mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            if mtype != "message":
                await _send_event(
                    websocket,
                    "error",
                    {"code": "UNKNOWN_TYPE", "message": f"expected type=message, got {mtype!r}"},
                )
                continue
            content = (msg.get("content") or "").strip()
            if not content:
                await _send_event(
                    websocket,
                    "error",
                    {"code": "EMPTY_MESSAGE", "message": "content is required"},
                )
                content = None
                continue

        # Persist the user turn immediately so a mid-stream disconnect doesn't
        # lose what they typed.
        await _save_message(
            sess.id,
            ChatMessageRole.USER,
            content,
            parts=[],
            token_count=len(content.split()),
        )

        full_text = ""
        emitted_parts: list[dict] = []
        buffer = ""
        token_count = 0

        if settings.gemini_enabled:
            text_iter = _gemini_stream(content, system_prompt, history, context_turns)
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
                    await _send_event(websocket, evt, data)
                buffer = remainder
            else:
                # Flush the longest prefix that can't possibly start a math/
                # diagram block, so the user sees plain text appear immediately
                # instead of waiting for the whole reply.
                safe_idx = len(buffer)
                for i, ch in enumerate(buffer):
                    if ch in "$`":
                        safe_idx = i
                        break
                if safe_idx > 0:
                    text = buffer[:safe_idx]
                    emitted_parts.append({"type": "token", "content": text})
                    token_count += len(text.split())
                    await _send_event(websocket, "token", {"content": text})
                    buffer = buffer[safe_idx:]

        if buffer.strip():
            emitted_parts.append({"type": "token", "content": buffer})
            token_count += len(buffer.split())
            await _send_event(websocket, "token", {"content": buffer})

        msg_id = await _save_message(
            sess.id,
            ChatMessageRole.COACH,
            full_text,
            emitted_parts,
            token_count,
        )

        await _send_event(
            websocket,
            "done",
            {"messageId": str(msg_id), "tokenCount": token_count},
        )
    except WebSocketDisconnect:
        return
    except Exception as e:  # noqa: BLE001
        await _send_event(
            websocket,
            "error",
            {"code": "STREAM_ERROR", "message": str(e)},
        )
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
