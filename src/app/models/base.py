"""Common mixins for ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column


def pg_enum(py_enum, *, name: str):
    """Wrap a Python Enum for a Postgres enum column.

    Forces SQLAlchemy to send the enum *value* (e.g. "closed") instead of the
    default *name* (e.g. "CLOSED") — required because every DB enum in this
    schema stores lowercase values that don't match the Python attribute name.
    """

    return SAEnum(
        py_enum,
        name=name,
        values_callable=lambda obj: [e.value for e in obj],
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
