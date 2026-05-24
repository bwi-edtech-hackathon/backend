"""User model."""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, pg_enum


class UserLanguage(str, enum.Enum):
    UZ = "uz"
    RU = "ru"
    EN = "en"


class Plan(str, enum.Enum):
    FREE = "free"
    STANDARD = "standard"
    PREMIUM = "premium"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[UserLanguage] = mapped_column(
        pg_enum(UserLanguage, name="user_language"), default=UserLanguage.UZ, nullable=False
    )

    # Region (vloyat) — free text per spec, no FK
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Exam preparation goal
    exam_target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_grade: Mapped[str | None] = mapped_column(String(8), nullable=True)  # e.g. "B+"

    # Plan
    plan: Mapped[Plan] = mapped_column(
        pg_enum(Plan, name="user_plan"), default=Plan.FREE, nullable=False
    )
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Gamification (denormalized for dashboard)
    streak_days: Mapped[int] = mapped_column(default=0, nullable=False)
    last_active_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<User {self.id} phone={self.phone}>"
