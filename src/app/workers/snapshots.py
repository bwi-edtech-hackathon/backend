"""Daily mastery snapshot task — STUB for B1; logic ships in Batch 4.

For every active user × subject:
  1. Sum weighted_earned / weighted_total → rasch_score estimate (0–100 scale)
  2. Build {topic_id: pct} from MasteryTopic rows
  3. Read ELO from EloRating
  4. Upsert into mastery_snapshots (snapshot_date = today Tashkent date)
"""

from __future__ import annotations

import logging

from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.snapshots.daily_mastery_snapshot")
def daily_mastery_snapshot() -> dict:
    log.info("daily_mastery_snapshot: stub — Batch 4 will implement")
    return {"status": "stub", "snapshots_written": 0}
