"""Password hashing and JWT issuance/verification."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]

# bcrypt has a hard 72-byte input limit. We pre-truncate (industry standard).
_BCRYPT_MAX_BYTES = 72


def _normalize_password(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(_normalize_password(plain), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_normalize_password(plain), hashed.encode("utf-8"))
    except Exception:
        return False


def _token_ttl(token_type: TokenType) -> timedelta:
    if token_type == "access":
        return timedelta(minutes=settings.jwt_access_ttl_minutes)
    return timedelta(days=settings.jwt_refresh_ttl_days)


def issue_token(
    subject: str | uuid.UUID,
    token_type: TokenType = "access",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Issue a signed JWT. Subject is the user's UUID as string."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + _token_ttl(token_type)).timestamp()),
        "type": token_type,
        "jti": str(uuid.uuid4()),
        "iss": "coachai",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decode and validate a JWT. Raises jwt exceptions on failure."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub", "type"]},
    )
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(
            f"expected {expected_type} token, got {payload.get('type')}"
        )
    return payload


def issue_token_pair(subject: str | uuid.UUID) -> dict[str, str | int]:
    """Return both access + refresh tokens with metadata."""
    return {
        "access_token": issue_token(subject, "access"),
        "refresh_token": issue_token(subject, "refresh"),
        "token_type": "Bearer",
        "expires_in": settings.jwt_access_ttl_minutes * 60,
    }
