"""Roadmap routes — STUBS for B1; rule-based generator in Batch 4.

Endpoints scheduled:
- GET  /api/v1/roadmap/{subject_id_or_slug}    Current roadmap (with milestone graph)
- POST /api/v1/roadmap/{subject_id_or_slug}/regenerate
                                                Trigger regeneration after exam attempt
- GET  /api/v1/roadmap/{subject}/milestones/{id} Milestone detail (topic explainer,
                                                  practice questions, checkpoint CTA)
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["roadmap"])


@router.get("/roadmap/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "roadmap", "status": "stub", "batch": 4}
