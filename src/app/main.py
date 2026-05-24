"""CoachAI backend — FastAPI entry point.

Wires every module router under /api/v1 plus real-time channels under /ws and /sse.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app import __version__
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.redis import close_redis
from app.modules.battle import router as battle_router
from app.modules.billing import router as billing_router
from app.modules.catalog import router as catalog_router
from app.modules.chat_lesson import fe_router as chat_lesson_fe_router
from app.modules.chat_lesson import router as chat_lesson_router
from app.modules.exams import router as exams_router
from app.modules.iam import router as iam_router
from app.modules.leaderboards import router as leaderboards_router
from app.modules.progress import router as progress_router
from app.modules.roadmap import router as roadmap_router
from app.sse import router as sse_router
from app.ws import router as ws_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    yield
    # Shutdown
    await close_redis()


app = FastAPI(
    title="CoachAI Backend",
    description=(
        "BMBA Milliy Sertifikat exam prep platform. "
        "Mock exams, AI tutor (Gemini SSE), real-time battles (WS), "
        "leaderboards, and personalized progress."
    ),
    version=__version__,
    default_response_class=ORJSONResponse,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# === Middleware ===
# Note: "*" is incompatible with allow_credentials=True per the CORS spec, so we
# translate wildcard mode into a regex match that echoes the request origin.
_cors_origins = settings.cors_origins_list
_cors_kwargs: dict = (
    {"allow_origin_regex": ".*"} if _cors_origins == ["*"] else {"allow_origins": _cors_origins}
)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
    **_cors_kwargs,
)

# === Exception handlers ===
register_exception_handlers(app)


# === Health ===
@app.get("/health", tags=["meta"], summary="Liveness probe")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "version": __version__,
    }


@app.get("/", tags=["meta"], include_in_schema=False)
async def root() -> dict:
    return {
        "name": "CoachAI Backend",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }


# === Routers ===
app.include_router(iam_router)
app.include_router(catalog_router)
app.include_router(exams_router)
app.include_router(progress_router)
app.include_router(roadmap_router)
app.include_router(chat_lesson_router)
app.include_router(chat_lesson_fe_router)
app.include_router(battle_router)
app.include_router(leaderboards_router)
app.include_router(billing_router)

# Real-time
app.include_router(ws_router)
app.include_router(sse_router)
