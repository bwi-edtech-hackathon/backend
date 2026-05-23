"""Battle HTTP routes — matchmaking, vs-AI, recent battles, stats, live-count."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import desc, func, or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.exceptions import RateLimitError
from app.core.redis import get_redis
from app.models.battle import (
    Battle,
    BattleAnswer,
    BattleMode,
    BattleStatus,
    BotTier,
)
from app.models.catalog import Subject
from app.modules.battle import matchmaking
from app.modules.battle.bots import pick_bot_name, starting_rating
from app.modules.battle.elo import next_tier_threshold, tier_for
from app.modules.battle.service import create_battle_record, ensure_elo_row, pick_battle_questions

router = APIRouter(prefix="/api/v1/battles", tags=["battle"])


# === Schemas ===
class QuickMatchIn(BaseModel):
    subject_id: uuid.UUID
    difficulty_tier: str | None = None  # informational; matchmaking uses ELO band


class QuickMatchOut(BaseModel):
    status: str  # SEARCHING | MATCHED
    battle_id: uuid.UUID | None
    battle_slug: str | None
    queue_position: int | None
    your_elo: int


class VsAiIn(BaseModel):
    subject_id: uuid.UUID
    bot_tier: str = "SILVER"


class BattleOut(BaseModel):
    id: uuid.UUID
    slug: str
    mode: str
    status: str
    subject_id: uuid.UUID
    player_a_id: uuid.UUID
    player_b_id: uuid.UUID | None
    bot_tier: str | None
    bot_name: str | None
    score_a: int
    score_b: int
    correct_a: int
    correct_b: int
    winner_id: uuid.UUID | None
    elo_delta_a: int
    elo_delta_b: int
    started_at: datetime | None
    finished_at: datetime | None
    question_count: int


class StatsOut(BaseModel):
    subject_id: uuid.UUID
    elo: int
    tier: str
    next_tier_at: int | None
    battles: int
    wins: int
    losses: int
    draws: int
    current_streak: int
    best_streak: int
    is_provisional: bool


class EloHistoryPoint(BaseModel):
    finished_at: datetime
    new_elo: int
    delta: int
    opponent_id: uuid.UUID | None
    won: bool


# === Helpers ===
def _battle_to_out(b: Battle) -> BattleOut:
    return BattleOut(
        id=b.id,
        slug=b.slug,
        mode=b.mode.value,
        status=b.status.value,
        subject_id=b.subject_id,
        player_a_id=b.player_a_id,
        player_b_id=b.player_b_id,
        bot_tier=b.bot_tier.value if b.bot_tier else None,
        bot_name=b.bot_name,
        score_a=b.score_a,
        score_b=b.score_b,
        correct_a=b.correct_a,
        correct_b=b.correct_b,
        winner_id=b.winner_id,
        elo_delta_a=b.elo_delta_a,
        elo_delta_b=b.elo_delta_b,
        started_at=b.started_at,
        finished_at=b.finished_at,
        question_count=b.question_count,
    )


# === Endpoints ===
@router.post("/quick-match", response_model=QuickMatchOut)
async def quick_match(
    payload: QuickMatchIn,
    user: CurrentUser,
    db: DbSession,
    redis: Redis = Depends(get_redis),
) -> QuickMatchOut:
    if not await matchmaking.can_play_ranked(redis, user.id):
        raise RateLimitError("Daily ranked battle limit reached", code="BATTLE_DAILY_LIMIT")

    subj = (
        await db.execute(select(Subject).where(Subject.id == payload.subject_id))
    ).scalar_one_or_none()
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")

    my_elo = await ensure_elo_row(db, user.id, subj.id)
    rating = my_elo.rating

    # Look for queued opponent first
    opp_id = await matchmaking.find_opponent(redis, subj.id, user.id, rating)
    if opp_id:
        opp_elo = await ensure_elo_row(db, opp_id, subj.id)
        questions = await pick_battle_questions(db, subj.id)
        if not questions:
            raise HTTPException(
                status_code=503, detail="No battle-suitable questions available"
            )
        battle = await create_battle_record(
            db,
            subject_id=subj.id,
            mode=BattleMode.QUICK_MATCH,
            player_a_id=opp_id,
            player_b_id=user.id,
            rating_a=opp_elo.rating,
            rating_b=rating,
            bot_tier=None,
            bot_name=None,
            questions=questions,
        )
        await matchmaking.set_match(redis, opp_id, battle.id)
        await matchmaking.set_match(redis, user.id, battle.id)
        return QuickMatchOut(
            status="MATCHED",
            battle_id=battle.id,
            battle_slug=battle.slug,
            queue_position=None,
            your_elo=rating,
        )

    # No opponent: enqueue myself
    await matchmaking.enqueue_player(redis, subj.id, user.id, rating)
    queue_size = await redis.zcard(
        matchmaking._queue_key(subj.id, rating)  # noqa: SLF001
    )
    return QuickMatchOut(
        status="SEARCHING",
        battle_id=None,
        battle_slug=None,
        queue_position=queue_size,
        your_elo=rating,
    )


@router.get("/quick-match/poll", response_model=QuickMatchOut)
async def poll_match(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
    redis: Redis = Depends(get_redis),
) -> QuickMatchOut:
    """Frontend polls this while waiting; returns MATCHED + battle_id when found."""
    bid = await matchmaking.get_match(redis, user.id)
    if bid:
        b = (
            await db.execute(select(Battle).where(Battle.id == bid))
        ).scalar_one_or_none()
        if b:
            return QuickMatchOut(
                status="MATCHED",
                battle_id=b.id,
                battle_slug=b.slug,
                queue_position=None,
                your_elo=(await ensure_elo_row(db, user.id, subject_id)).rating,
            )
    elo = await ensure_elo_row(db, user.id, subject_id)
    return QuickMatchOut(
        status="SEARCHING",
        battle_id=None,
        battle_slug=None,
        queue_position=None,
        your_elo=elo.rating,
    )


@router.delete("/quick-match", status_code=status.HTTP_204_NO_CONTENT)
async def leave_queue(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
    redis: Redis = Depends(get_redis),
) -> None:
    my_elo = await ensure_elo_row(db, user.id, subject_id)
    await matchmaking.dequeue_player(redis, subject_id, user.id, my_elo.rating)
    await matchmaking.clear_match(redis, user.id)


@router.post("/vs-ai", response_model=BattleOut, status_code=status.HTTP_201_CREATED)
async def start_vs_ai(
    payload: VsAiIn,
    user: CurrentUser,
    db: DbSession,
    redis: Redis = Depends(get_redis),
) -> BattleOut:
    if not await matchmaking.can_play_ranked(redis, user.id):
        raise RateLimitError("Daily ranked battle limit reached", code="BATTLE_DAILY_LIMIT")
    try:
        tier = BotTier(payload.bot_tier.upper())
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid bot tier") from e
    subj = (
        await db.execute(select(Subject).where(Subject.id == payload.subject_id))
    ).scalar_one_or_none()
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")

    my_elo = await ensure_elo_row(db, user.id, subj.id)
    questions = await pick_battle_questions(db, subj.id)
    if not questions:
        raise HTTPException(
            status_code=503, detail="No battle-suitable questions available"
        )
    battle = await create_battle_record(
        db,
        subject_id=subj.id,
        mode=BattleMode.VS_AI,
        player_a_id=user.id,
        player_b_id=None,
        rating_a=my_elo.rating,
        rating_b=starting_rating(tier),
        bot_tier=tier,
        bot_name=pick_bot_name(),
        questions=questions,
    )
    await matchmaking.set_match(redis, user.id, battle.id)
    return _battle_to_out(battle)


@router.get("/recent", response_model=list[BattleOut])
async def recent_battles(
    user: CurrentUser, db: DbSession, limit: int = Query(10, ge=1, le=50)
) -> list[BattleOut]:
    rows = (
        await db.execute(
            select(Battle)
            .where(
                or_(Battle.player_a_id == user.id, Battle.player_b_id == user.id),
                Battle.status == BattleStatus.FINISHED,
            )
            .order_by(desc(Battle.finished_at))
            .limit(limit)
        )
    ).scalars().all()
    return [_battle_to_out(b) for b in rows]


@router.get("/live-count")
async def live_count(db: DbSession) -> dict:
    n = (
        await db.execute(
            select(func.count(Battle.id)).where(
                Battle.status.in_([BattleStatus.READY, BattleStatus.ACTIVE])
            )
        )
    ).scalar_one()
    return {"in_progress": int(n or 0)}


@router.get("/stats", response_model=StatsOut)
async def my_stats(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
) -> StatsOut:
    elo = await ensure_elo_row(db, user.id, subject_id)
    return StatsOut(
        subject_id=subject_id,
        elo=elo.rating,
        tier=tier_for(elo.rating),
        next_tier_at=next_tier_threshold(elo.rating),
        battles=elo.battles_count,
        wins=elo.wins,
        losses=elo.losses,
        draws=elo.draws,
        current_streak=elo.current_streak,
        best_streak=elo.best_streak,
        is_provisional=elo.is_provisional,
    )


@router.get("/elo-history", response_model=list[EloHistoryPoint])
async def elo_history(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
    limit: int = Query(30, ge=1, le=200),
) -> list[EloHistoryPoint]:
    rows = (
        await db.execute(
            select(Battle)
            .where(
                or_(Battle.player_a_id == user.id, Battle.player_b_id == user.id),
                Battle.subject_id == subject_id,
                Battle.status == BattleStatus.FINISHED,
            )
            .order_by(desc(Battle.finished_at))
            .limit(limit)
        )
    ).scalars().all()
    out: list[EloHistoryPoint] = []
    for b in rows:
        if b.player_a_id == user.id:
            delta = b.elo_delta_a
            opp = b.player_b_id
            rating = (b.rating_a_start or 1200) + delta
        else:
            delta = b.elo_delta_b
            opp = b.player_a_id
            rating = (b.rating_b_start or 1200) + delta
        won = b.winner_id == user.id
        out.append(
            EloHistoryPoint(
                finished_at=b.finished_at or b.started_at or datetime.utcnow(),
                new_elo=rating,
                delta=delta,
                opponent_id=opp,
                won=won,
            )
        )
    # API expects oldest-first
    return list(reversed(out))


@router.get("/{battle_id_or_slug}", response_model=BattleOut)
async def battle_detail(
    battle_id_or_slug: str, user: CurrentUser, db: DbSession
) -> BattleOut:
    stmt = select(Battle)
    try:
        bid = uuid.UUID(battle_id_or_slug)
        stmt = stmt.where(Battle.id == bid)
    except ValueError:
        stmt = stmt.where(Battle.slug == battle_id_or_slug)
    b = (await db.execute(stmt)).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Battle not found")
    if user.id not in (b.player_a_id, b.player_b_id):
        raise HTTPException(status_code=403, detail="Not a participant")
    return _battle_to_out(b)


@router.get("/{battle_id_or_slug}/answers")
async def battle_answers(
    battle_id_or_slug: str, user: CurrentUser, db: DbSession
) -> list[dict]:
    stmt = select(Battle)
    try:
        bid = uuid.UUID(battle_id_or_slug)
        stmt = stmt.where(Battle.id == bid)
    except ValueError:
        stmt = stmt.where(Battle.slug == battle_id_or_slug)
    b = (await db.execute(stmt)).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Battle not found")
    if user.id not in (b.player_a_id, b.player_b_id):
        raise HTTPException(status_code=403, detail="Not a participant")

    rows = (
        await db.execute(
            select(BattleAnswer)
            .where(BattleAnswer.battle_id == b.id)
            .order_by(BattleAnswer.question_index, BattleAnswer.user_id)
        )
    ).scalars().all()
    return [
        {
            "question_index": a.question_index,
            "user_id": str(a.user_id) if a.user_id else None,
            "answer": a.answer,
            "is_correct": a.is_correct,
            "time_taken_ms": a.time_taken_ms,
            "total_points": a.total_points,
        }
        for a in rows
    ]


@router.get("/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "battle", "status": "ok"}
