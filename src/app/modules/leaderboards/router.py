"""Leaderboard routes — STUBS for B1; ranking queries in Batch 7.

Endpoints scheduled (4 scopes, Friends dropped per C1=A):
- GET /api/v1/leaderboards/global?subject_id=...    Top 100 + user rank ±5
- GET /api/v1/leaderboards/weekly?subject_id=...    This week's top 100
- GET /api/v1/leaderboards/regional?subject_id=...  User's vloyat
- GET /api/v1/leaderboards/school?subject_id=...    User's school
- GET /api/v1/leaderboards/me?subject_id=...        User's rank in all scopes
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["leaderboards"])


@router.get("/leaderboards/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "leaderboards", "status": "stub", "batch": 7}
