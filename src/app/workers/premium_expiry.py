"""Hourly premium expiry — downgrades users whose premium_until has passed."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import async_session_factory
from app.models.billing import PremiumGrant
from app.models.user import Plan, User
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def _run() -> int:
    now = datetime.now(UTC)
    downgraded = 0
    async with async_session_factory() as db:
        users = (
            await db.execute(
                select(User).where(
                    User.plan == Plan.PREMIUM,
                    User.premium_until.is_not(None),
                    User.premium_until < now,
                )
            )
        ).scalars().all()
        for user in users:
            # Look for any still-active grant
            active = (
                await db.execute(
                    select(PremiumGrant)
                    .where(
                        PremiumGrant.user_id == user.id,
                        PremiumGrant.expires_at > now,
                    )
                    .order_by(PremiumGrant.expires_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if active:
                user.premium_until = active.expires_at
                continue
            user.plan = Plan.FREE
            user.premium_until = None
            downgraded += 1
        await db.commit()
    return downgraded


@celery_app.task(name="app.workers.premium_expiry.expire_premium_users")
def expire_premium_users() -> dict:
    n = asyncio.run(_run())
    log.info("expire_premium_users downgraded %d", n)
    return {"status": "ok", "users_downgraded": n}
