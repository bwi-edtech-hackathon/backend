"""Celery application + beat schedule.

Scheduled jobs (Tashkent timezone):
- daily_mastery_snapshot  every day at 00:30
- weekly_prize_grant      every Monday at 00:05 (after weekly leaderboard freeze)
- expire_premium          every hour
- cleanup_stale_battles   every 5 minutes (mark abandoned past grace period)
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "coachai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.snapshots",
        "app.workers.weekly_prize",
        "app.workers.premium_expiry",
        "app.workers.battle_cleanup",
    ],
)

celery_app.conf.update(
    timezone=settings.app_timezone,
    enable_utc=False,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_time_limit=300,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "daily-mastery-snapshot": {
        "task": "app.workers.snapshots.daily_mastery_snapshot",
        "schedule": crontab(hour=0, minute=30),
    },
    "weekly-prize-grant": {
        "task": "app.workers.weekly_prize.grant_weekly_prizes",
        "schedule": crontab(hour=0, minute=5, day_of_week="monday"),
    },
    "hourly-premium-expiry": {
        "task": "app.workers.premium_expiry.expire_premium_users",
        "schedule": crontab(minute=0),
    },
    "battle-cleanup": {
        "task": "app.workers.battle_cleanup.cleanup_stale_battles",
        "schedule": crontab(minute="*/5"),
    },
}


if __name__ == "__main__":
    celery_app.start()
