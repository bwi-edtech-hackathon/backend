"""Catalog models: Subject, Topic (hierarchical), Question."""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin


class SubjectCode(str, enum.Enum):
    MATH = "MATH"
    PHYS = "PHYS"
    CHEM = "CHEM"
    BIO = "BIO"
    HIST = "HIST"
    GEOG = "GEOG"
    UZB_LIT = "UZB_LIT"
    RUS_LIT = "RUS_LIT"


class QuestionType(str, enum.Enum):
    CLOSED = "closed"           # A/B/C/D — single correct
    MATCHING = "matching"       # spec, deferred grading
    MULTI_SELECT = "multi_select"  # spec, deferred grading
    OPEN_A = "open_a"           # short answer (regex/fuzzy)
    OPEN_B = "open_b"           # written 1–3 sentences (LLM-graded, Phase 2)
    ESSAY = "essay"             # language subjects only (Phase 2)


class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[SubjectCode] = mapped_column(
        Enum(SubjectCode, name="subject_code"), unique=True, nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)

    name_uz: Mapped[str] = mapped_column(String(120), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)

    has_essay: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    format_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    topics: Mapped[list["Topic"]] = relationship(back_populates="subject", cascade="all,delete")
    questions: Mapped[list["Question"]] = relationship(back_populates="subject")


class Topic(Base, TimestampMixin):
    """Hierarchical: depth=1 domain, depth=2 topic, depth=3 subtopic."""

    __tablename__ = "topics"
    __table_args__ = (
        Index("ix_topics_subject_parent", "subject_id", "parent_id"),
        UniqueConstraint("subject_id", "slug", name="uq_topics_subject_slug"),
        CheckConstraint("depth >= 1 AND depth <= 3", name="ck_topics_depth_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=True
    )

    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    name_uz: Mapped[str] = mapped_column(String(160), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)

    # Weight from BMBA spec (0..1) — used by mastery + roadmap impact ranking
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.500"), nullable=False)

    # List of prerequisite topic UUIDs (DAG) — JSONB array of strings
    prerequisites: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    parent: Mapped["Topic | None"] = relationship(remote_side="Topic.id", backref="children")


class Question(Base, TimestampMixin):
    __tablename__ = "questions"
    __table_args__ = (
        Index("ix_questions_subject_topic", "subject_id", "topic_id"),
        Index("ix_questions_battle", "subject_id", "suitable_for_battle"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)

    type: Mapped[QuestionType] = mapped_column(
        Enum(QuestionType, name="question_type"), nullable=False
    )

    # Body in 3 languages (Markdown + KaTeX)
    body_uz: Mapped[str] = mapped_column(Text, nullable=False)
    body_ru: Mapped[str] = mapped_column(Text, nullable=False)
    body_en: Mapped[str] = mapped_column(Text, nullable=False)

    # Options (for closed/matching/multi) — keyed JSON: {"A": {uz, ru, en}, ...}
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Correct answer — schema varies by type:
    #   closed: "B"
    #   open_a: ["3", "три", "uch", "3.0"]
    #   matching: {"1": "c", "2": "a", "3": "b"}
    #   multi_select: ["A", "C", "D"]
    correct_answer: Mapped[dict | list | str] = mapped_column(JSONB, nullable=False)

    # Acceptable variants for open_a (regex patterns)
    accepted_patterns: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    points: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("2.20"), nullable=False)
    difficulty: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.500"), nullable=False)

    suitable_for_battle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Content sourcing tier: 1=official sample, 2=SME, 3=AI+review, 4=crowdsourced
    source_tier: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    source_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    subject: Mapped[Subject] = relationship(back_populates="questions")
    topic: Mapped[Topic] = relationship()
