"""Battle cleanup — STUB for B1.

Mark stale battles abandoned if both players disconnected past the 30s grace
window (settings.battle_disconnect_grace_seconds).
"""

from __future__ import annotations

import logging

from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.battle_cleanup.cleanup_stale_battles")
def cleanup_stale_battles() -> dict:
    log.info("cleanup_stale_battles: stub — Batch 5 will implement")
    return {"status": "stub", "battles_cleaned": 0}
