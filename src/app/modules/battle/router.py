"""Battle routes — STUBS for B1; matchmaking + WS handler in Batch 5.

Endpoints scheduled:
- POST   /api/v1/battles/quick-match       Enter matchmaking queue (returns
                                            {status: 'searching', poll_url})
- DELETE /api/v1/battles/quick-match       Leave queue
- POST   /api/v1/battles/vs-ai             Start AI battle immediately
                                            (body: {subject_id, bot_tier})
- GET    /api/v1/battles/recent            User's last 10 battles
- GET    /api/v1/battles/live-count        # of active battles right now
                                            (powers "248 battles in progress" widget)
- GET    /api/v1/battles/{id_or_slug}      Battle detail (post-game)
- GET    /api/v1/battles/stats             User's per-subject battle stats
- GET    /api/v1/battles/elo-history       ELO over time (per subject)

Real-time:
- WS  /ws/battles/{battle_id}?token=...    See app/ws/battles.py
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["battle"])


@router.get("/battles/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "battle", "status": "stub", "batch": 5}
