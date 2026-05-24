"""WebSocket endpoints."""

from fastapi import APIRouter

from app.ws.battles import router as battles_router
from app.ws.chat_lesson import router as chat_lesson_router

router = APIRouter()
router.include_router(battles_router)
router.include_router(chat_lesson_router)

__all__ = ["router"]
