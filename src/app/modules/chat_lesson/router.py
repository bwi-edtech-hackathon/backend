"""Chat lesson routes — STUBS for B1; full Gemini SSE in Batch 6.

Endpoints scheduled (HTTP CRUD):
- POST /api/v1/chat-lesson/sessions               Create session (subject/topic, trigger)
- GET  /api/v1/chat-lesson/sessions               List user sessions
- GET  /api/v1/chat-lesson/sessions/{id_or_slug}  Session detail + message history
- POST /api/v1/chat-lesson/sessions/{id}/end      End session, freeze mastery_estimate
- POST /api/v1/chat-lesson/sessions/{id}/messages SSE — see /sse/chat_lesson.py

The actual streaming endpoint lives at /sse/chat-lesson/sessions/{id}/messages
and emits structured events: token | math_inline | math_block | diagram | done
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["chat-lesson"])


@router.get("/chat-lesson/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "chat_lesson", "status": "stub", "batch": 6}
