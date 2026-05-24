"""Reference formulas (and humanities-subject reference links) seeded per
subject. Replaces the hardcoded `_FORMULAS_BY_SUBJECT` dict and the chat
`_TOPIC_HINTS` map so Gemini can be told the canonical set up front and cite
the rows it actually used."""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, pg_enum
from app.models.catalog import Subject, Topic


class FormulaKind(str, enum.Enum):
    FORMULA = "formula"
    REFERENCE = "reference"


class Formula(Base, TimestampMixin):
    __tablename__ = "formulas"
    __table_args__ = (
        Index("ix_formulas_subject_group", "subject_id", "group_title"),
        Index("ix_formulas_topic", "topic_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Topic anchor is optional — many formulas (e.g. quadratic) span topics
    # and should be cited regardless of the currently active topic.
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
    )

    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    group_title: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # `expression` keeps the Unicode rendering used by the right-rail formula
    # sheet (e.g. "D = b² − 4ac"). `latex` keeps the LaTeX form fed to Gemini
    # so its responses use the same notation.
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    latex: Mapped[str | None] = mapped_column(Text, nullable=True)
    href: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kind: Mapped[FormulaKind] = mapped_column(
        pg_enum(FormulaKind, name="formula_kind"),
        default=FormulaKind.FORMULA,
        nullable=False,
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Free-text keywords used to match the formula to a chat topic name when
    # no explicit topic_id link exists.
    keywords: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    subject: Mapped[Subject] = relationship()
    topic: Mapped[Topic | None] = relationship()
