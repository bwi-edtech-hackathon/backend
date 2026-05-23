"""Exams routes — STUBS for B1; full grading + adaptive engine in Batch 3.

Endpoints scheduled:
- POST   /api/v1/exams/diagnostic            Start adaptive diagnostic
- POST   /api/v1/exams/full-mock             Start full 150-min mock
- POST   /api/v1/exams/checkpoint            Start topic checkpoint (5–10 q)
- GET    /api/v1/exam-attempts/{id_or_slug}  Get current state (resume)
- PATCH  /api/v1/exam-attempts/{id}/autosave Auto-save answers every 30s
- POST   /api/v1/exam-attempts/{id}/answer   Submit a single answer
- POST   /api/v1/exam-attempts/{id}/submit   Submit exam for grading
- GET    /api/v1/exam-attempts/{id}/result   Get graded result (score, grade,
                                              topic heatmap, top-3 weakest)
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["exams"])


@router.get("/exams/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "exams", "status": "stub", "batch": 3}
