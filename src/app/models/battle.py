"""Battle models: Battle, BattleAnswer, EloRating."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin


class BattleMode(str, enum.Enum):
    QUICK_MATCH = "quick_match"   # ranked, ELO impact
    VS_AI = "vs_ai"               # ranked, ELO impact capped
    FRIEND = "friend"             # Phase 2 — schema present, endpoints deferred


class BattleStatus(str, enum.Enum):
    WAITING = "waiting"           # in matchmaking
    READY = "ready"               # both players joined, countdown
    ACTIVE = "active"             # mid-battle
    FINISHED = "finished"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"       # disconnect past grace period


class BotTier(str, enum.Enum):
    BRONZE = "BRONZE"     # 0.60 accuracy, 8–15s
    SILVER = "SILVER"     # 0.75 accuracy, 5–12s
    GOLD = "GOLD"         # 0.88 accuracy, 4–8s
    PLATINUM = "PLATINUM" # 0.95 accuracy, 3–6s


class Battle(Base, TimestampMixin):
    __tablename__ = "battles"
    __table_args__ = (
        Index("ix_battles_subject_status", "subject_id", "status"),
        Index("ix_battles_player_a", "player_a_id"),
        Index("ix_battles_player_b", "player_b_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[BattleMode] = mapped_column(Enum(BattleMode, name="battle_mode"), nullable=False)
    status: Mapped[BattleStatus] = mapped_column(
        Enum(BattleStatus, name="battle_status"), default=BattleStatus.WAITING, nullable=False
    )

    # Player A is always the initiator. Player B can be NULL for vs-AI battles.
    player_a_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    player_b_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    bot_tier: Mapped[BotTier | None] = mapped_column(Enum(BotTier, name="battle_bot_tier"), nullable=True)
    bot_name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # Uzbek pseudonym

    # ELO snapshot at battle start
    rating_a_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_b_start: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Frozen question set: [{question_id, index}]
    question_layout: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    score_a: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_b: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_a: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_b: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_a_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_b_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    winner_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    elo_delta_a: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elo_delta_b: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    answers: Mapped[list["BattleAnswer"]] = relationship(
        back_populates="battle", cascade="all,delete", order_by="BattleAnswer.question_index"
    )


class BattleAnswer(Base, TimestampMixin):
    __tablename__ = "battle_answers"
    __table_args__ = (
        UniqueConstraint("battle_id", "user_id", "question_index", name="uq_battle_answers_player_idx"),
        Index("ix_battle_answers_battle", "battle_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    battle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("battles.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = bot answer
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)

    answer: Mapped[dict | list | str | None] = mapped_column(JSONB, nullable=True)
    is_correct: Mapped[bool] = mapped_column(default=False, nullable=False)
    time_taken_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    base_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    speed_bonus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_bonus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    battle: Mapped[Battle] = relationship(back_populates="answers")


class EloRating(Base, TimestampMixin):
    """Per-user, per-subject ELO (matches design: math whiz can be history novice)."""

    __tablename__ = "elo_ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", name="uq_elo_user_subject"),
        Index("ix_elo_subject_rating", "subject_id", "rating"),  # for leaderboard
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    rating: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    battles_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    draws: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    current_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    best_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Provisional period (first 10 battles) uses K=40
    is_provisional: Mapped[bool] = mapped_column(default=True, nullable=False)
