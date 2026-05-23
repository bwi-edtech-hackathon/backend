"""Leaderboard models: School, LeaderboardEntry."""

import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class LeaderboardScope(str, enum.Enum):
    GLOBAL = "global"       # all users, never resets
    WEEKLY = "weekly"       # all users, reset Mon 00:00 Tashkent
    REGIONAL = "regional"   # by vloyat, reset monthly
    SCHOOL = "school"       # by school, reset monthly
    # FRIENDS = "friends"   # DROPPED for MVP (no friendship system)


class School(Base, TimestampMixin):
    __tablename__ = "schools"
    __table_args__ = (Index("ix_schools_region_name", "region", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    region: Mapped[str] = mapped_column(String(80), nullable=False)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)


class LeaderboardEntry(Base, TimestampMixin):
    """Denormalized leaderboard cache. Authoritative ranking source.

    For Phase 1 we read/write this on every battle finish; in Phase 2 swap
    to Redis ZSET as the hot read path with this table as the cold store.
    """

    __tablename__ = "leaderboard_entries"
    __table_args__ = (
        UniqueConstraint(
            "scope", "subject_id", "period_start", "user_id",
            name="uq_lb_entries_scope_subj_period_user",
        ),
        Index("ix_lb_scope_subject_rank", "scope", "subject_id", "rank"),
        Index("ix_lb_scope_period", "scope", "period_start", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[LeaderboardScope] = mapped_column(
        Enum(LeaderboardScope, name="leaderboard_scope"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Period scoping: NULL for GLOBAL; set for WEEKLY/REGIONAL/SCHOOL
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # For REGIONAL/SCHOOL filtering
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("schools.id", ondelete="SET NULL"), nullable=True
    )

    # Score = ELO for global; weekly points for weekly
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Display denormalization
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
