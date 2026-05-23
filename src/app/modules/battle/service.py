"""Battle service — pure helpers shared by HTTP routes and WS handler."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slugs import short_slug
from app.models.battle import Battle, BattleMode, BattleStatus, BotTier, EloRating
from app.models.catalog import Question

BATTLE_QUESTION_COUNT = 10


async def ensure_elo_row(
    db: AsyncSession, user_id: uuid.UUID, subject_id: uuid.UUID
) -> EloRating:
    row = (
        await db.execute(
            select(EloRating).where(
                EloRating.user_id == user_id, EloRating.subject_id == subject_id
            )
        )
    ).scalar_one_or_none()
    if not row:
        row = EloRating(user_id=user_id, subject_id=subject_id)
        db.add(row)
        await db.flush()
    return row


async def pick_battle_questions(
    db: AsyncSession, subject_id: uuid.UUID, count: int = BATTLE_QUESTION_COUNT
) -> list[Question]:
    rows = (
        await db.execute(
            select(Question)
            .where(
                Question.subject_id == subject_id,
                Question.suitable_for_battle.is_(True),
            )
            .order_by(Question.difficulty)
            .limit(count * 3)
        )
    ).scalars().all()
    if not rows:
        # Fallback: any closed-type question of this subject
        rows = (
            await db.execute(
                select(Question)
                .where(Question.subject_id == subject_id)
                .limit(count * 3)
            )
        ).scalars().all()
    if not rows:
        return []
    rng = random.Random()
    sample = rng.sample(list(rows), min(count, len(rows)))
    return sample


async def create_battle_record(
    db: AsyncSession,
    subject_id: uuid.UUID,
    mode: BattleMode,
    player_a_id: uuid.UUID,
    player_b_id: uuid.UUID | None,
    rating_a: int,
    rating_b: int | None,
    bot_tier: BotTier | None,
    bot_name: str | None,
    questions: list[Question],
) -> Battle:
    layout = [
        {
            "index": i,
            "question_id": str(q.id),
            "topic_id": str(q.topic_id),
            "points": float(q.points),
            "difficulty": float(q.difficulty),
        }
        for i, q in enumerate(questions)
    ]
    battle = Battle(
        slug=short_slug(f"{mode.value}-{subject_id}"),
        subject_id=subject_id,
        mode=mode,
        status=BattleStatus.READY,
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        bot_tier=bot_tier,
        bot_name=bot_name,
        rating_a_start=rating_a,
        rating_b_start=rating_b,
        question_layout=layout,
        question_count=len(layout),
        started_at=datetime.now(UTC),
    )
    db.add(battle)
    await db.flush()
    await db.commit()
    await db.refresh(battle)
    return battle
