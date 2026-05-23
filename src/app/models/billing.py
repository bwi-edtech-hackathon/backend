"""Billing model: PremiumGrant — supports weekly prize automation."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class PremiumSource(str, enum.Enum):
    WEEKLY_PRIZE = "weekly_prize"   # top 10 weekly leaderboard
    PURCHASE = "purchase"           # paid (Phase 2)
    PROMO = "promo"                 # manual admin grant
    REFERRAL = "referral"           # Phase 3


class PremiumGrant(Base, TimestampMixin):
    __tablename__ = "premium_grants"
    __table_args__ = (Index("ix_premium_grants_user_expires", "user_id", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[PremiumSource] = mapped_column(
        Enum(PremiumSource, name="premium_source"), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
