"""Progress routes — STUBS for B1; analytics dashboard wired in Batch 4.

Endpoints scheduled:
- GET /api/v1/progress/dashboard          One-shot payload for /home screen
                                          (per-subject: rasch, elo, mastery%,
                                          streak, predicted_grade, exam_target)
- GET /api/v1/progress/mastery            Topic-level mastery (heatmap source)
- GET /api/v1/progress/snapshots          8-week trend points
- GET /api/v1/progress/predicted-grade    Linear extrapolation to exam date
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["progress"])


@router.get("/progress/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "progress", "status": "stub", "batch": 4}
