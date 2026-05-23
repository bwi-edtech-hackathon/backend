"""Common FastAPI dependencies."""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise UnauthorizedError("Missing Authorization header", code="MISSING_AUTH")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedError("Invalid Authorization header", code="INVALID_AUTH_HEADER")
    return parts[1]


async def get_current_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    """Extract and verify the access token; return user UUID."""
    token = await _extract_bearer(authorization)
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.ExpiredSignatureError as e:
        raise UnauthorizedError("Token expired", code="TOKEN_EXPIRED") from e
    except jwt.InvalidTokenError as e:
        raise UnauthorizedError("Invalid token", code="INVALID_TOKEN") from e
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise UnauthorizedError("Malformed token subject", code="INVALID_TOKEN") from e


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
        raise UnauthorizedError("User not found or inactive", code="USER_INACTIVE")
    return user


CurrentUser = Annotated["User", Depends(get_current_user)]  # type: ignore[name-defined]  # noqa: F821
