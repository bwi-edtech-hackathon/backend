"""Weekly prize grant — STUB for B1; logic ships in Batch 8.

Every Monday 00:05 Tashkent (after weekly leaderboard freeze):
  1. For each subject, fetch top 10 of last week's weekly leaderboard
  2. Grant Premium (1 month) via PremiumGrant + bump user.plan to PREMIUM
     if not already
  3. Send push notification (Phase 2 — gated)
"""

from __future__ import annotations

import logging

from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.weekly_prize.grant_weekly_prizes")
def grant_weekly_prizes() -> dict:
    log.info("grant_weekly_prizes: stub — Batch 8 will implement")
    return {"status": "stub", "grants_issued": 0}
