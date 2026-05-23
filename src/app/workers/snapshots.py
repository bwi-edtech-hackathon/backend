"""Daily mastery snapshot task.

For every user × subject with any MasteryTopic rows:
  1. Sum weighted_earned / weighted_total → rasch_score estimate
  2. Build {topic_id: pct} from MasteryTopic rows
  3. Read ELO from EloRating
  4. Upsert into mastery_snapshots (snapshot_date = today Tashkent date)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import async_session_factory
from app.models.battle import EloRating
from app.models.progress import MasterySnapshot, MasteryTopic
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


def _grade_for(score: float) -> str:
    if score >= 70:
        return "A+"
    if score >= 65:
        return "A"
    if score >= 60:
        return "B+"
    if score >= 55:
        return "B"
    if score >= 50:
        return "C+"
    if score >= 46:
        return "C"
    return "F"


async def _run() -> int:
    today = date.today()
    written = 0
    async with async_session_factory() as db:
        rows = (
            await db.execute(select(MasteryTopic))
        ).scalars().all()
        # Group by (user_id, subject_id)
        by_pair: dict[tuple, list[MasteryTopic]] = {}
        for m in rows:
            by_pair.setdefault((m.user_id, m.subject_id), []).append(m)

        for (user_id, subject_id), topics in by_pair.items():
            weighted_earned = sum(float(t.weighted_earned) for t in topics)
            weighted_total = sum(float(t.weighted_total) for t in topics) or 1.0
            rasch_score = min(100.0, weighted_earned / weighted_total * 100.0)
            topic_map = {str(t.topic_id): float(t.mastery_pct) for t in topics}

            elo_row = (
                await db.execute(
                    select(EloRating).where(
                        EloRating.user_id == user_id,
                        EloRating.subject_id == subject_id,
                    )
                )
            ).scalar_one_or_none()
            elo = elo_row.rating if elo_row else 1200

            stmt = pg_insert(MasterySnapshot).values(
                user_id=user_id,
                subject_id=subject_id,
                snapshot_date=today,
                rasch_score=Decimal(f"{rasch_score:.2f}"),
                grade=_grade_for(rasch_score),
                topic_mastery=topic_map,
                elo=elo,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "subject_id", "snapshot_date"],
                set_={
                    "rasch_score": stmt.excluded.rasch_score,
                    "grade": stmt.excluded.grade,
                    "topic_mastery": stmt.excluded.topic_mastery,
                    "elo": stmt.excluded.elo,
                },
            )
            await db.execute(stmt)
            written += 1
        await db.commit()
    return written


@celery_app.task(name="app.workers.snapshots.daily_mastery_snapshot")
def daily_mastery_snapshot() -> dict:
    n = asyncio.run(_run())
    log.info("daily_mastery_snapshot wrote %d snapshots", n)
    return {"status": "ok", "snapshots_written": n}
