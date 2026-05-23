"""Progress models: MasteryTopic, MasterySnapshot, Roadmap."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class MasteryTopic(Base, TimestampMixin):
    """Per-topic, per-user mastery rollup (updated on every exam/battle answer)."""

    __tablename__ = "mastery_topics"
    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", name="uq_mastery_topics_user_topic"),
        Index("ix_mastery_topics_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    mastery_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Sum of (question.difficulty * points) actually earned — for weighted %
    weighted_earned: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"), nullable=False)
    weighted_total: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"), nullable=False)

    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MasterySnapshot(Base, TimestampMixin):
    """Daily snapshot per user × subject — drives 8-week trend chart + predicted grade."""

    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "subject_id", "snapshot_date",
            name="uq_mastery_snapshots_user_subj_date",
        ),
        Index("ix_mastery_snapshots_user_subj_date", "user_id", "subject_id", "snapshot_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    rasch_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0.00"), nullable=False)
    grade: Mapped[str | None] = mapped_column(nullable=True)

    # {topic_id_str: mastery_pct} — full snapshot for heatmap replay
    topic_mastery: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ELO at this snapshot
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)


class Roadmap(Base, TimestampMixin):
    """Rule-based topic plan per user × subject."""

    __tablename__ = "roadmaps"
    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", name="uq_roadmaps_user_subj"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    # Milestones: [{topic_id, order, status (locked/active/done), est_minutes, week_bucket}]
    milestones: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
