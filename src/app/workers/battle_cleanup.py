"""Battle cleanup — mark stale READY/ACTIVE battles as abandoned."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.db import async_session_factory
from app.models.battle import Battle, BattleStatus
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def _run() -> int:
    now = datetime.now(UTC)
    grace = timedelta(seconds=settings.battle_disconnect_grace_seconds)
    threshold = now - grace - timedelta(minutes=10)  # battle should finish in 10 min
    cleaned = 0
    async with async_session_factory() as db:
        stale = (
            await db.execute(
                select(Battle).where(
                    Battle.status.in_([BattleStatus.READY, BattleStatus.ACTIVE]),
                    Battle.started_at.is_not(None),
                    Battle.started_at < threshold,
                )
            )
        ).scalars().all()
        for b in stale:
            b.status = BattleStatus.ABANDONED
            b.finished_at = now
            cleaned += 1
        await db.commit()
    return cleaned


@celery_app.task(name="app.workers.battle_cleanup.cleanup_stale_battles")
def cleanup_stale_battles() -> dict:
    n = asyncio.run(_run())
    log.info("cleanup_stale_battles closed %d", n)
    return {"status": "ok", "battles_cleaned": n}
