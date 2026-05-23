"""Chat lesson models: ChatSession, ChatMessage."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin


class ChatTrigger(str, enum.Enum):
    PROACTIVE = "proactive"   # user opened Chat Lesson tab
    REACTIVE = "reactive"     # failed checkpoint twice


class ChatMessageRole(str, enum.Enum):
    USER = "user"
    COACH = "coach"
    SYSTEM = "system"


class ChatSessionStatus(str, enum.Enum):
    ACTIVE = "active"
    ENDED = "ended"
    ABANDONED = "abandoned"


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("ix_chat_sessions_user_active", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )

    trigger: Mapped[ChatTrigger] = mapped_column(
        Enum(ChatTrigger, name="chat_trigger"), default=ChatTrigger.PROACTIVE, nullable=False
    )
    status: Mapped[ChatSessionStatus] = mapped_column(
        Enum(ChatSessionStatus, name="chat_session_status"), default=ChatSessionStatus.ACTIVE, nullable=False
    )

    # Mastery estimate at session start vs current — for progress bar in header
    mastery_at_start: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)
    mastery_estimate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all,delete", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatMessageRole] = mapped_column(
        Enum(ChatMessageRole, name="chat_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured parts emitted by streaming (SSE events): token | math_inline | math_block | diagram
    parts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
