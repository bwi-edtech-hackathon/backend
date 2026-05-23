"""initial schema — all tables for CoachAI MVP

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Enum helpers
USER_LANGUAGE = sa.Enum("uz", "ru", "en", name="user_language")
USER_PLAN = sa.Enum("free", "standard", "premium", name="user_plan")
SUBJECT_CODE = sa.Enum(
    "MATH", "PHYS", "CHEM", "BIO", "HIST", "GEOG", "UZB_LIT", "RUS_LIT",
    name="subject_code",
)
QUESTION_TYPE = sa.Enum(
    "closed", "matching", "multi_select", "open_a", "open_b", "essay",
    name="question_type",
)
EXAM_KIND = sa.Enum("diagnostic", "full_mock", "checkpoint", name="exam_kind")
EXAM_STATUS = sa.Enum(
    "in_progress", "submitted", "graded", "abandoned", name="exam_status"
)
EXAM_GRADE = sa.Enum("A+", "A", "B+", "B", "C+", "C", "F", name="exam_grade")
CHAT_TRIGGER = sa.Enum("proactive", "reactive", name="chat_trigger")
CHAT_SESSION_STATUS = sa.Enum("active", "ended", "abandoned", name="chat_session_status")
CHAT_MESSAGE_ROLE = sa.Enum("user", "coach", "system", name="chat_message_role")
BATTLE_MODE = sa.Enum("quick_match", "vs_ai", "friend", name="battle_mode")
BATTLE_STATUS = sa.Enum(
    "waiting", "ready", "active", "finished", "cancelled", "abandoned",
    name="battle_status",
)
BATTLE_BOT_TIER = sa.Enum(
    "BRONZE", "SILVER", "GOLD", "PLATINUM", name="battle_bot_tier"
)
LEADERBOARD_SCOPE = sa.Enum(
    "global", "weekly", "regional", "school", name="leaderboard_scope"
)
PREMIUM_SOURCE = sa.Enum(
    "weekly_prize", "purchase", "promo", "referral", name="premium_source"
)


def upgrade() -> None:
    # === Schools (no FK) ===
    op.create_table(
        "schools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("region", sa.String(80), nullable=False),
        sa.Column("city", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_schools_region_name", "schools", ["region", "name"])

    # === Users ===
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("language", USER_LANGUAGE, nullable=False, server_default="uz"),
        sa.Column("region", sa.String(80), nullable=True),
        sa.Column(
            "school_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schools.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("exam_target_date", sa.Date, nullable=True),
        sa.Column("target_grade", sa.String(8), nullable=True),
        sa.Column("plan", USER_PLAN, nullable=False, server_default="free"),
        sa.Column("premium_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("streak_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_active_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_school_id", "users", ["school_id"])

    # === Subjects ===
    op.create_table(
        "subjects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", SUBJECT_CODE, nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name_uz", sa.String(120), nullable=False),
        sa.Column("name_ru", sa.String(120), nullable=False),
        sa.Column("name_en", sa.String(120), nullable=False),
        sa.Column("has_essay", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("format_notes", sa.Text, nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_subjects_code"),
        sa.UniqueConstraint("slug", name="uq_subjects_slug"),
    )
    op.create_index("ix_subjects_slug", "subjects", ["slug"])

    # === Topics ===
    op.create_table(
        "topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("code", sa.String(40), nullable=True),
        sa.Column("depth", sa.Integer, nullable=False, server_default="2"),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("name_uz", sa.String(160), nullable=False),
        sa.Column("name_ru", sa.String(160), nullable=False),
        sa.Column("name_en", sa.String(160), nullable=False),
        sa.Column("weight", sa.Numeric(4, 3), nullable=False, server_default="0.500"),
        sa.Column("prerequisites", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("subject_id", "slug", name="uq_topics_subject_slug"),
        sa.CheckConstraint("depth >= 1 AND depth <= 3", name="ck_topics_depth_range"),
    )
    op.create_index("ix_topics_subject_parent", "topics", ["subject_id", "parent_id"])

    # === Questions ===
    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("type", QUESTION_TYPE, nullable=False),
        sa.Column("body_uz", sa.Text, nullable=False),
        sa.Column("body_ru", sa.Text, nullable=False),
        sa.Column("body_en", sa.Text, nullable=False),
        sa.Column("options", postgresql.JSONB, nullable=True),
        sa.Column("correct_answer", postgresql.JSONB, nullable=False),
        sa.Column("accepted_patterns", postgresql.JSONB, nullable=True),
        sa.Column("points", sa.Numeric(4, 2), nullable=False, server_default="2.20"),
        sa.Column("difficulty", sa.Numeric(4, 3), nullable=False, server_default="0.500"),
        sa.Column("suitable_for_battle", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("source_tier", sa.Integer, nullable=False, server_default="3"),
        sa.Column("source_note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_questions_slug"),
    )
    op.create_index("ix_questions_slug", "questions", ["slug"])
    op.create_index("ix_questions_subject_topic", "questions", ["subject_id", "topic_id"])
    op.create_index("ix_questions_battle", "questions", ["subject_id", "suitable_for_battle"])

    # === Exam templates ===
    op.create_table(
        "exam_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("kind", EXAM_KIND, nullable=False),
        sa.Column("title_uz", sa.String(160), nullable=False),
        sa.Column("title_ru", sa.String(160), nullable=False),
        sa.Column("title_en", sa.String(160), nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False, server_default="150"),
        sa.Column("sections", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("pass_threshold", sa.Numeric(5, 2), nullable=False, server_default="46.00"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_exam_templates_slug"),
    )

    # === Exam attempts ===
    op.create_table(
        "exam_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exam_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", EXAM_KIND, nullable=False),
        sa.Column("status", EXAM_STATUS, nullable=False, server_default="in_progress"),
        sa.Column("question_layout", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("rasch_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("grade", EXAM_GRADE, nullable=True),
        sa.Column("topic_breakdown", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("weakest_topics", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_exam_attempts_slug"),
    )
    op.create_index("ix_exam_attempts_slug", "exam_attempts", ["slug"])
    op.create_index("ix_exam_attempts_user_status", "exam_attempts", ["user_id", "status"])

    # === Exam answers ===
    op.create_table(
        "exam_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question_index", sa.Integer, nullable=False),
        sa.Column("answer", postgresql.JSONB, nullable=True),
        sa.Column("is_correct", sa.Boolean, nullable=True),
        sa.Column("points_awarded", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("time_taken_ms", sa.Integer, nullable=True),
        sa.Column("flagged", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("grading_meta", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("attempt_id", "question_index", name="uq_exam_answers_idx"),
    )

    # === Mastery topics ===
    op.create_table(
        "mastery_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mastery_pct", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("attempts_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("weighted_earned", sa.Numeric(8, 2), nullable=False, server_default="0.00"),
        sa.Column("weighted_total", sa.Numeric(8, 2), nullable=False, server_default="0.00"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "topic_id", name="uq_mastery_topics_user_topic"),
    )
    op.create_index("ix_mastery_topics_user", "mastery_topics", ["user_id"])

    # === Mastery snapshots ===
    op.create_table(
        "mastery_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("rasch_score", sa.Numeric(6, 2), nullable=False, server_default="0.00"),
        sa.Column("grade", sa.String, nullable=True),
        sa.Column("topic_mastery", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("elo", sa.Integer, nullable=False, server_default="1200"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "subject_id", "snapshot_date",
                            name="uq_mastery_snapshots_user_subj_date"),
    )
    op.create_index("ix_mastery_snapshots_user_subj_date", "mastery_snapshots",
                    ["user_id", "subject_id", "snapshot_date"])

    # === Roadmaps ===
    op.create_table(
        "roadmaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("milestones", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "subject_id", name="uq_roadmaps_user_subj"),
    )

    # === Chat sessions ===
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("trigger", CHAT_TRIGGER, nullable=False, server_default="proactive"),
        sa.Column("status", CHAT_SESSION_STATUS, nullable=False, server_default="active"),
        sa.Column("mastery_at_start", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("mastery_estimate", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_chat_sessions_slug"),
    )
    op.create_index("ix_chat_sessions_slug", "chat_sessions", ["slug"])
    op.create_index("ix_chat_sessions_user_active", "chat_sessions", ["user_id", "status"])

    # === Chat messages ===
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", CHAT_MESSAGE_ROLE, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("parts", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])

    # === Battles ===
    op.create_table(
        "battles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mode", BATTLE_MODE, nullable=False),
        sa.Column("status", BATTLE_STATUS, nullable=False, server_default="waiting"),
        sa.Column("player_a_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("player_b_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("bot_tier", BATTLE_BOT_TIER, nullable=True),
        sa.Column("bot_name", sa.String(80), nullable=True),
        sa.Column("rating_a_start", sa.Integer, nullable=True),
        sa.Column("rating_b_start", sa.Integer, nullable=True),
        sa.Column("question_layout", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("question_count", sa.Integer, nullable=False, server_default="10"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score_a", sa.Integer, nullable=False, server_default="0"),
        sa.Column("score_b", sa.Integer, nullable=False, server_default="0"),
        sa.Column("correct_a", sa.Integer, nullable=False, server_default="0"),
        sa.Column("correct_b", sa.Integer, nullable=False, server_default="0"),
        sa.Column("time_a_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("time_b_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("winner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("elo_delta_a", sa.Integer, nullable=False, server_default="0"),
        sa.Column("elo_delta_b", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_battles_slug"),
    )
    op.create_index("ix_battles_slug", "battles", ["slug"])
    op.create_index("ix_battles_subject_status", "battles", ["subject_id", "status"])
    op.create_index("ix_battles_player_a", "battles", ["player_a_id"])
    op.create_index("ix_battles_player_b", "battles", ["player_b_id"])

    # === Battle answers ===
    op.create_table(
        "battle_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("battle_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("battles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question_index", sa.Integer, nullable=False),
        sa.Column("answer", postgresql.JSONB, nullable=True),
        sa.Column("is_correct", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("time_taken_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("base_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("speed_bonus", sa.Integer, nullable=False, server_default="0"),
        sa.Column("streak_bonus", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_points", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("battle_id", "user_id", "question_index",
                            name="uq_battle_answers_player_idx"),
    )
    op.create_index("ix_battle_answers_battle", "battle_answers", ["battle_id"])

    # === ELO ratings ===
    op.create_table(
        "elo_ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer, nullable=False, server_default="1200"),
        sa.Column("battles_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("draws", sa.Integer, nullable=False, server_default="0"),
        sa.Column("current_streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("best_streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_provisional", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "subject_id", name="uq_elo_user_subject"),
    )
    op.create_index("ix_elo_subject_rating", "elo_ratings", ["subject_id", "rating"])

    # === Leaderboard entries ===
    op.create_table(
        "leaderboard_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", LEADERBOARD_SCOPE, nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.Date, nullable=True),
        sa.Column("period_end", sa.Date, nullable=True),
        sa.Column("region", sa.String(80), nullable=True),
        sa.Column("school_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("schools.id", ondelete="SET NULL"), nullable=True),
        sa.Column("score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rank", sa.Integer, nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope", "subject_id", "period_start", "user_id",
                            name="uq_lb_entries_scope_subj_period_user"),
    )
    op.create_index("ix_lb_scope_subject_rank", "leaderboard_entries",
                    ["scope", "subject_id", "rank"])
    op.create_index("ix_lb_scope_period", "leaderboard_entries",
                    ["scope", "period_start", "period_end"])

    # === Premium grants ===
    op.create_table(
        "premium_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", PREMIUM_SOURCE, nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_premium_grants_user_expires", "premium_grants",
                    ["user_id", "expires_at"])

    # === Refresh token blacklist ===
    op.create_table(
        "refresh_token_blacklist",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("jti", name="uq_refresh_blacklist_jti"),
    )
    op.create_index("ix_refresh_blacklist_jti", "refresh_token_blacklist", ["jti"])
    op.create_index("ix_refresh_blacklist_expires", "refresh_token_blacklist", ["expires_at"])


def downgrade() -> None:
    # Drop in reverse FK order
    op.drop_table("refresh_token_blacklist")
    op.drop_table("premium_grants")
    op.drop_table("leaderboard_entries")
    op.drop_table("elo_ratings")
    op.drop_table("battle_answers")
    op.drop_table("battles")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("roadmaps")
    op.drop_table("mastery_snapshots")
    op.drop_table("mastery_topics")
    op.drop_table("exam_answers")
    op.drop_table("exam_attempts")
    op.drop_table("exam_templates")
    op.drop_table("questions")
    op.drop_table("topics")
    op.drop_table("subjects")
    op.drop_table("users")
    op.drop_table("schools")

    # Drop enums
    for enum_obj in [
        PREMIUM_SOURCE, LEADERBOARD_SCOPE, BATTLE_BOT_TIER, BATTLE_STATUS, BATTLE_MODE,
        CHAT_MESSAGE_ROLE, CHAT_SESSION_STATUS, CHAT_TRIGGER,
        EXAM_GRADE, EXAM_STATUS, EXAM_KIND,
        QUESTION_TYPE, SUBJECT_CODE,
        USER_PLAN, USER_LANGUAGE,
    ]:
        enum_obj.drop(op.get_bind(), checkfirst=True)
