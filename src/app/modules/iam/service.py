"""IAM business logic — register / login / refresh."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    decode_token,
    hash_password,
    issue_token_pair,
    verify_password,
)
from app.models.security import RefreshTokenBlacklist
from app.models.user import User
from app.modules.iam.schemas import LoginIn, RegisterIn, UserUpdate


async def register_user(db: AsyncSession, data: RegisterIn) -> User:
    # Reject duplicate phone / email
    res = await db.execute(select(User).where(User.phone == data.phone))
    if res.scalar_one_or_none():
        raise ConflictError(
            "Phone already registered", code="PHONE_TAKEN"
        )
    if data.email:
        res = await db.execute(select(User).where(User.email == data.email))
        if res.scalar_one_or_none():
            raise ConflictError("Email already registered", code="EMAIL_TAKEN")

    user = User(
        phone=data.phone,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        language=data.language,
        region=data.region,
        target_grade=data.target_grade,
        exam_target_date=data.exam_target_date,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, data: LoginIn) -> User:
    res = await db.execute(select(User).where(User.phone == data.phone))
    user = res.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("Invalid phone or password", code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise UnauthorizedError("Account disabled", code="USER_INACTIVE")
    return user


def issue_pair(user: User) -> dict:
    return issue_token_pair(user.id)


async def rotate_refresh(db: AsyncSession, refresh_token: str) -> dict:
    """Validate refresh token, blacklist its JTI, issue new pair."""
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except jwt.ExpiredSignatureError as e:
        raise UnauthorizedError("Refresh token expired", code="REFRESH_EXPIRED") from e
    except jwt.InvalidTokenError as e:
        raise UnauthorizedError("Invalid refresh token", code="INVALID_REFRESH") from e

    jti = payload.get("jti")
    if not jti:
        raise UnauthorizedError("Malformed refresh token", code="INVALID_REFRESH")

    # Check blacklist
    res = await db.execute(
        select(RefreshTokenBlacklist).where(RefreshTokenBlacklist.jti == jti)
    )
    if res.scalar_one_or_none():
        raise UnauthorizedError("Refresh token already used", code="REFRESH_REUSED")

    # Blacklist this JTI
    user_id = uuid.UUID(payload["sub"])
    db.add(
        RefreshTokenBlacklist(
            jti=jti,
            user_id=user_id,
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            reason="rotated",
        )
    )
    await db.commit()

    # Issue new pair
    return issue_token_pair(user_id)


async def update_profile(db: AsyncSession, user: User, patch: UserUpdate) -> User:
    data = patch.model_dump(exclude_unset=True)

    if "email" in data and data["email"]:
        # Check email conflict
        res = await db.execute(
            select(User).where(User.email == data["email"], User.id != user.id)
        )
        if res.scalar_one_or_none():
            raise ConflictError("Email already registered", code="EMAIL_TAKEN")

    for k, v in data.items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return user
