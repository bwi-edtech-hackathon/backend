"""Billing routes — STUBS for B1; weekly prize Celery beat in Batch 8.

Endpoints scheduled:
- GET  /api/v1/billing/me/plan         Current plan + premium expiry
- GET  /api/v1/billing/me/grants       History of premium grants
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["billing"])


@router.get("/billing/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "billing", "status": "stub", "batch": 8}
