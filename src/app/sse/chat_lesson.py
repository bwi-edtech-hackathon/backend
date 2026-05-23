"""Chat lesson SSE endpoint — STUB for B1; Gemini streaming in Batch 6.

Endpoint: POST /api/v1/chat-lesson/sessions/{session_id}/messages
Returns: text/event-stream

Event types (per spec §6.4):
  - token        {"content": "Let"}
  - math_inline  {"latex": "x^2"}
  - math_block   {"latex": "\\int_0^1 f(x) dx"}
  - diagram      {"mermaid": "graph TD; A-->B"}
  - done         {"messageId": "uuid", "tokenCount": 42}

In dev (no GEMINI_API_KEY): emits a deterministic stub sequence so frontends can
build against the protocol immediately.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.deps import CurrentUserId

router = APIRouter(prefix="/api/v1/chat-lesson", tags=["chat-lesson"])


async def _stub_stream(prompt: str) -> AsyncIterator[dict]:
    """Deterministic mock stream when Gemini is not configured."""
    parts = [
        ("token", {"content": "Let's "}),
        ("token", {"content": "look at "}),
        ("math_inline", {"latex": "x^2 - 5x + 6 = 0"}),
        ("token", {"content": " — what type of equation is this?"}),
        ("done", {"messageId": str(uuid.uuid4()), "tokenCount": 12, "stub": True}),
    ]
    for event, data in parts:
        await asyncio.sleep(0.15)
        yield {"event": event, "data": json.dumps(data)}


@router.post(
    "/sessions/{session_id}/messages",
    summary="Stream a coach response via SSE",
)
async def stream_message(
    session_id: str,
    user_id: CurrentUserId,
    payload: dict = Body(...),
) -> EventSourceResponse:
    content = payload.get("content", "")
    if settings.gemini_enabled:
        # Real Gemini streaming wired in Batch 6
        async def _real() -> AsyncIterator[dict]:
            yield {
                "event": "error",
                "data": json.dumps({
                    "code": "NOT_IMPLEMENTED",
                    "message": "Gemini streaming ships in Batch 6 — falling back to stub",
                }),
            }
            async for evt in _stub_stream(content):
                yield evt

        return EventSourceResponse(_real())

    return EventSourceResponse(_stub_stream(content))
