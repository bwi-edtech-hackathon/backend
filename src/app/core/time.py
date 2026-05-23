"""Timezone-aware time helpers (Tashkent for business logic, UTC for storage)."""

from datetime import datetime, timezone

import pytz

from app.core.config import settings

TASHKENT_TZ = pytz.timezone(settings.app_timezone)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def tashkent_now() -> datetime:
    return datetime.now(TASHKENT_TZ)


def to_tashkent(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TASHKENT_TZ)
