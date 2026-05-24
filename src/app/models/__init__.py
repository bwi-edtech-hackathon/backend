"""ORM models — import every model here so Alembic can autodiscover them."""

from app.core.db import Base
from app.models.base import TimestampMixin
from app.models.battle import Battle, BattleAnswer, BattleMode, BattleStatus, BotTier, EloRating
from app.models.billing import PremiumGrant, PremiumSource
from app.models.catalog import Question, QuestionType, Subject, SubjectCode, Topic
from app.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatTrigger
from app.models.exam import ExamAnswer, ExamAttempt, ExamKind, ExamStatus, ExamTemplate, Grade
from app.models.formula import Formula, FormulaKind
from app.models.leaderboard import LeaderboardEntry, LeaderboardScope, School
from app.models.progress import MasterySnapshot, MasteryTopic, Roadmap
from app.models.security import RefreshTokenBlacklist
from app.models.user import Plan, User, UserLanguage

__all__ = [
    "Base",
    "TimestampMixin",
    # User
    "User",
    "Plan",
    "UserLanguage",
    # Catalog
    "Subject",
    "SubjectCode",
    "Topic",
    "Question",
    "QuestionType",
    # Exam
    "ExamTemplate",
    "ExamAttempt",
    "ExamAnswer",
    "ExamKind",
    "ExamStatus",
    "Grade",
    # Progress
    "MasteryTopic",
    "MasterySnapshot",
    "Roadmap",
    # Chat
    "ChatSession",
    "ChatMessage",
    "ChatTrigger",
    "ChatMessageRole",
    # Formulas
    "Formula",
    "FormulaKind",
    # Battle
    "Battle",
    "BattleAnswer",
    "BattleMode",
    "BattleStatus",
    "BotTier",
    "EloRating",
    # Leaderboard
    "LeaderboardEntry",
    "LeaderboardScope",
    "School",
    # Billing
    "PremiumGrant",
    "PremiumSource",
    # Security
    "RefreshTokenBlacklist",
]
