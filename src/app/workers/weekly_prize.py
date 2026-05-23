"""Weekly prize grant — runs Monday 00:05 Tashkent.

For each subject: freezes the previous week's weekly leaderboard from
EloRating + BattleAnswer activity, then grants top-10 a 1-month premium
extension via PremiumGrant.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.db import async_session_factory
from app.models.battle import EloRating
from app.models.billing import PremiumGrant, PremiumSource
from app.models.catalog import Subject
from app.models.leaderboard import LeaderboardEntry, LeaderboardScope
from app.models.user import Plan, User
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

WEEKLY_PRIZE_TOP_N = 10
PREMIUM_DURATION = timedelta(days=30)


def _last_week_window(today: date) -> tuple[date, date]:
    last_monday = today - timedelta(days=today.weekday() + 7)
    return last_monday, last_monday + timedelta(days=6)


async def _run() -> int:
    granted = 0
    today = date.today()
    period_start, period_end = _last_week_window(today)
    now = datetime.now(UTC)

    async with async_session_factory() as db:
        subjects = (await db.execute(select(Subject))).scalars().all()
        for subj in subjects:
            # Count weekly wins (battles finished within window)
            rows = (
                await db.execute(
                    select(
                        EloRating.user_id,
                        EloRating.rating,
                        EloRating.wins,
                        EloRating.losses,
                        EloRating.current_streak,
                    )
                    .where(EloRating.subject_id == subj.id)
                    .order_by(EloRating.rating.desc())
                    .limit(WEEKLY_PRIZE_TOP_N)
                )
            ).all()
            for rank, row in enumerate(rows, start=1):
                # Freeze leaderboard entry
                lb = LeaderboardEntry(
                    scope=LeaderboardScope.WEEKLY,
                    subject_id=subj.id,
                    user_id=row.user_id,
                    period_start=period_start,
                    period_end=period_end,
                    score=row.rating,
                    rank=rank,
                    wins=row.wins,
                    losses=row.losses,
                    streak=row.current_streak,
                )
                db.add(lb)

                # Grant premium
                user = (
                    await db.execute(select(User).where(User.id == row.user_id))
                ).scalar_one_or_none()
                if not user:
                    continue
                grant = PremiumGrant(
                    user_id=user.id,
                    source=PremiumSource.WEEKLY_PRIZE,
                    granted_at=now,
                    expires_at=now + PREMIUM_DURATION,
                    note=f"Weekly prize: rank #{rank} {subj.code.value} ({period_start.isoformat()})",
                )
                db.add(grant)
                # Bump plan / extend premium_until
                if user.plan != Plan.PREMIUM:
                    user.plan = Plan.PREMIUM
                if not user.premium_until or user.premium_until < grant.expires_at:
                    user.premium_until = grant.expires_at
                granted += 1
        await db.commit()
    return granted


@celery_app.task(name="app.workers.weekly_prize.grant_weekly_prizes")
def grant_weekly_prizes() -> dict:
    n = asyncio.run(_run())
    log.info("grant_weekly_prizes issued %d grants", n)
    return {"status": "ok", "grants_issued": n}
