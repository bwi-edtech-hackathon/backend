"""Hourly premium expiry — STUB for B1.

Downgrade users whose premium_until is in the past back to their last paid plan
(or FREE if no active grants remain).
"""

from __future__ import annotations

import logging

from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.premium_expiry.expire_premium_users")
def expire_premium_users() -> dict:
    log.info("expire_premium_users: stub — Batch 8 will implement")
    return {"status": "stub", "users_downgraded": 0}
