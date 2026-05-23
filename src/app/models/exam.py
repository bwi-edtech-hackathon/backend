"""Exam models: ExamTemplate, ExamAttempt, ExamAnswer."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin


class ExamKind(str, enum.Enum):
    DIAGNOSTIC = "diagnostic"      # 30-min adaptive
    FULL_MOCK = "full_mock"        # 150-min, 55 sub-answers
    CHECKPOINT = "checkpoint"      # 5–10 questions per topic


class ExamStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    GRADED = "graded"
    ABANDONED = "abandoned"


class Grade(str, enum.Enum):
    A_PLUS = "A+"   # 70+
    A = "A"         # 65–69.9
    B_PLUS = "B+"   # 60–64.9
    B = "B"         # 55–59.9
    C_PLUS = "C+"   # 50–54.9
    C = "C"         # 46–49.9
    FAIL = "F"      # below 46


class ExamTemplate(Base, TimestampMixin):
    """Reusable exam blueprint (e.g. 'MATH full mock v1')."""

    __tablename__ = "exam_templates"
    __table_args__ = (UniqueConstraint("slug", name="uq_exam_templates_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[ExamKind] = mapped_column(Enum(ExamKind, name="exam_kind"), nullable=False)

    title_uz: Mapped[str] = mapped_column(String(160), nullable=False)
    title_ru: Mapped[str] = mapped_column(String(160), nullable=False)
    title_en: Mapped[str] = mapped_column(String(160), nullable=False)

    duration_minutes: Mapped[int] = mapped_column(Integer, default=150, nullable=False)
    # Sections shape: [{"name": "A", "q_count": 35, "types": ["closed"]},
    #                  {"name": "B", "q_count": 10, "types": ["open_a"], "subparts": 2}]
    sections: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    pass_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("46.00"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExamAttempt(Base, TimestampMixin):
    __tablename__ = "exam_attempts"
    __table_args__ = (
        Index("ix_exam_attempts_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exam_templates.id", ondelete="SET NULL"), nullable=True
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )

    kind: Mapped[ExamKind] = mapped_column(Enum(ExamKind, name="exam_kind"), nullable=False)
    status: Mapped[ExamStatus] = mapped_column(
        Enum(ExamStatus, name="exam_status"), default=ExamStatus.IN_PROGRESS, nullable=False
    )

    # Frozen question list at start of exam: [{question_id, section, index, points}]
    question_layout: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Scoring
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    rasch_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    grade: Mapped[Grade | None] = mapped_column(Enum(Grade, name="exam_grade"), nullable=True)

    # Per-topic mastery snapshot at submit (JSON: {topic_id: pct})
    topic_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Top-3 weak topics for "things to work on" UI
    weakest_topics: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    answers: Mapped[list["ExamAnswer"]] = relationship(
        back_populates="attempt", cascade="all,delete", order_by="ExamAnswer.question_index"
    )


class ExamAnswer(Base, TimestampMixin):
    __tablename__ = "exam_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_index", name="uq_exam_answers_idx"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Submitted answer — shape mirrors Question.correct_answer
    answer: Mapped[dict | list | str | None] = mapped_column(JSONB, nullable=True)

    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    points_awarded: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)
    time_taken_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # For open_b/essay: LLM grade reasoning + confidence
    grading_meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    attempt: Mapped[ExamAttempt] = relationship(back_populates="answers")
