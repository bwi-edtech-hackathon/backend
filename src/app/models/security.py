"""Security models: refresh token blacklist for JWT rotation."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class RefreshTokenBlacklist(Base, TimestampMixin):
    """Stores JTIs of revoked / rotated refresh tokens."""

    __tablename__ = "refresh_token_blacklist"
    __table_args__ = (
        Index("ix_refresh_blacklist_expires", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
