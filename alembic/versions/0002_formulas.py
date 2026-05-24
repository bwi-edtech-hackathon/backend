"""formulas table + chat_messages.formula_ids

Revision ID: 0002_formulas
Revises: 0001_initial
Create Date: 2026-05-24

Adds a `formulas` table seeded per subject/topic so the chat coach pulls
reference formulas from the DB instead of from the hardcoded `_TOPIC_HINTS`
map, and the right-rail formula sheet pulls from the same source. Records
which formula UUIDs Gemini cited on each coach reply via a JSONB column on
`chat_messages`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_formulas"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Use the postgres dialect ENUM so we can suppress the implicit CREATE TYPE
# during `op.create_table` (alembic emits it before the CREATE TABLE), and
# emit our own idempotent CREATE TYPE up front via a DO-block — that way
# the migration can be re-run after a partial failure without exploding on
# the duplicate type.
FORMULA_KIND = postgresql.ENUM(
    "formula", "reference", name="formula_kind", create_type=False
)


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE formula_kind AS ENUM ('formula', 'reference'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    )

    op.create_table(
        "formulas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subject_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("group_title", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("expression", sa.Text, nullable=False),
        sa.Column("latex", sa.Text, nullable=True),
        sa.Column("href", sa.String(500), nullable=True),
        sa.Column("kind", FORMULA_KIND, nullable=False, server_default="formula"),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "keywords",
            postgresql.JSONB,
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_formulas_slug"),
    )
    op.create_index("ix_formulas_slug", "formulas", ["slug"])
    op.create_index("ix_formulas_subject_group", "formulas", ["subject_id", "group_title"])
    op.create_index("ix_formulas_topic", "formulas", ["topic_id"])

    op.add_column(
        "chat_messages",
        sa.Column(
            "formula_ids",
            postgresql.JSONB,
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "formula_ids")
    op.drop_index("ix_formulas_topic", table_name="formulas")
    op.drop_index("ix_formulas_subject_group", table_name="formulas")
    op.drop_index("ix_formulas_slug", table_name="formulas")
    op.drop_table("formulas")
    FORMULA_KIND.drop(op.get_bind(), checkfirst=True)
