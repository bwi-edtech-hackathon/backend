"""Common FastAPI dependencies.

Auth model: a JWT in `Authorization: Bearer …` identifies a real user. When the
header is missing (the frontend is mock-auth for now), the request resolves to a
single shared **demo user** that is auto-created on first hit. This lets every
screen exercise the real backend without a login flow.
"""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token, hash_password

DbSession = Annotated[AsyncSession, Depends(get_db)]


DEMO_USER_PHONE = "+998900000000"
DEMO_USER_NAME = "Diana M."


async def _ensure_demo_user(db: AsyncSession):
    from app.models.user import User  # noqa: WPS433 — lazy import to avoid circular

    res = await db.execute(select(User).where(User.phone == DEMO_USER_PHONE))
    user = res.scalar_one_or_none()
    if user:
        return user
    user = User(
        phone=DEMO_USER_PHONE,
        full_name=DEMO_USER_NAME,
        password_hash=hash_password("demo-mode-no-login"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _decode_or_none(authorization: str | None) -> uuid.UUID | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        payload = decode_token(parts[1], expected_type="access")
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


async def get_current_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    """Return user UUID from bearer token, falling back to the demo user."""
    uid = await _decode_or_none(authorization)
    if uid is not None:
        return uid
    # No / bad token → demo user. Need a DB session to look it up.
    async for db in get_db():
        user = await _ensure_demo_user(db)
        return user.id
    raise UnauthorizedError("DB unavailable", code="DB_UNAVAILABLE")


CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]


async def get_current_user(
    db: DbSession,
    user_id: CurrentUserId,
):
    """Load the current user from DB. Imported lazily to avoid circular import."""
    from app.models.user import User  # noqa: WPS433 — intentional lazy import

    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or not user.is_active:
        # Token referred to a non-existent user — fall back to demo so the demo
        # never sees a 401.
        user = await _ensure_demo_user(db)
    return user


CurrentUser = Annotated["User", Depends(get_current_user)]  # type: ignore[name-defined]  # noqa: F821
