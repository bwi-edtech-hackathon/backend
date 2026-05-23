"""Leaderboard routes — 4 scopes + user rank context.

GLOBAL/REGIONAL/SCHOOL read live from EloRating. WEEKLY reads from
LeaderboardEntry (frozen by Celery beat every Monday).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from app.core.deps import CurrentUser, DbSession
from app.models.battle import EloRating
from app.models.leaderboard import LeaderboardEntry, LeaderboardScope
from app.models.user import User

router = APIRouter(prefix="/api/v1/leaderboards", tags=["leaderboards"])


# === Schemas ===
class LeaderRow(BaseModel):
    rank: int
    user_id: uuid.UUID
    display_name: str
    region: str | None
    school_id: uuid.UUID | None
    score: int
    wins: int
    losses: int
    streak: int


class LeaderboardOut(BaseModel):
    scope: str
    subject_id: uuid.UUID
    period_start: date | None
    period_end: date | None
    top: list[LeaderRow]
    me: LeaderRow | None
    me_context: list[LeaderRow]


class MeRankOut(BaseModel):
    subject_id: uuid.UUID
    global_rank: int | None
    weekly_rank: int | None
    regional_rank: int | None
    school_rank: int | None
    elo: int


# === Helpers ===
def _week_period(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def _month_period(today: date) -> tuple[date, date]:
    first = today.replace(day=1)
    if first.month == 12:
        next_first = first.replace(year=first.year + 1, month=1)
    else:
        next_first = first.replace(month=first.month + 1)
    return first, next_first - timedelta(days=1)


async def _live_rank_by_elo(
    db,
    subject_id: uuid.UUID,
    region: str | None = None,
    school_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[LeaderRow]:
    stmt = (
        select(EloRating, User)
        .join(User, User.id == EloRating.user_id)
        .where(EloRating.subject_id == subject_id, User.is_active.is_(True))
    )
    if region:
        stmt = stmt.where(User.region == region)
    if school_id:
        stmt = stmt.where(User.school_id == school_id)
    stmt = stmt.order_by(desc(EloRating.rating), EloRating.battles_count.desc()).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [
        LeaderRow(
            rank=i + 1,
            user_id=u.id,
            display_name=u.full_name,
            region=u.region,
            school_id=u.school_id,
            score=e.rating,
            wins=e.wins,
            losses=e.losses,
            streak=e.current_streak,
        )
        for i, (e, u) in enumerate(rows)
    ]


async def _live_rank_of_user(
    db,
    subject_id: uuid.UUID,
    user: User,
    region: str | None = None,
    school_id: uuid.UUID | None = None,
) -> tuple[int | None, LeaderRow | None]:
    elo_row = (
        await db.execute(
            select(EloRating).where(
                EloRating.user_id == user.id, EloRating.subject_id == subject_id
            )
        )
    ).scalar_one_or_none()
    if not elo_row:
        return None, None

    count_stmt = (
        select(func.count(EloRating.id))
        .join(User, User.id == EloRating.user_id)
        .where(
            EloRating.subject_id == subject_id,
            User.is_active.is_(True),
            EloRating.rating > elo_row.rating,
        )
    )
    if region:
        count_stmt = count_stmt.where(User.region == region)
    if school_id:
        count_stmt = count_stmt.where(User.school_id == school_id)
    higher = (await db.execute(count_stmt)).scalar_one()
    my_rank = higher + 1
    me_row = LeaderRow(
        rank=my_rank,
        user_id=user.id,
        display_name=user.full_name,
        region=user.region,
        school_id=user.school_id,
        score=elo_row.rating,
        wins=elo_row.wins,
        losses=elo_row.losses,
        streak=elo_row.current_streak,
    )
    return my_rank, me_row


async def _context_window(
    db,
    subject_id: uuid.UUID,
    target_rating: int,
    region: str | None = None,
    school_id: uuid.UUID | None = None,
    radius: int = 5,
) -> list[LeaderRow]:
    above = (
        await db.execute(
            select(EloRating, User)
            .join(User, User.id == EloRating.user_id)
            .where(
                EloRating.subject_id == subject_id,
                EloRating.rating >= target_rating,
                User.is_active.is_(True),
                *(
                    [User.region == region] if region else []
                ),
                *(
                    [User.school_id == school_id] if school_id else []
                ),
            )
            .order_by(EloRating.rating)
            .limit(radius + 1)
        )
    ).all()
    below = (
        await db.execute(
            select(EloRating, User)
            .join(User, User.id == EloRating.user_id)
            .where(
                EloRating.subject_id == subject_id,
                EloRating.rating < target_rating,
                User.is_active.is_(True),
                *(
                    [User.region == region] if region else []
                ),
                *(
                    [User.school_id == school_id] if school_id else []
                ),
            )
            .order_by(desc(EloRating.rating))
            .limit(radius)
        )
    ).all()
    combined = list(reversed(above)) + list(below)
    return [
        LeaderRow(
            rank=0,  # context — not absolute
            user_id=u.id,
            display_name=u.full_name,
            region=u.region,
            school_id=u.school_id,
            score=e.rating,
            wins=e.wins,
            losses=e.losses,
            streak=e.current_streak,
        )
        for e, u in combined
    ]


# === Endpoints ===
@router.get("/global", response_model=LeaderboardOut)
async def global_lb(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
) -> LeaderboardOut:
    top = await _live_rank_by_elo(db, subject_id, limit=100)
    my_rank, me = await _live_rank_of_user(db, subject_id, user)
    ctx = (
        await _context_window(db, subject_id, me.score) if me else []
    )
    return LeaderboardOut(
        scope="global",
        subject_id=subject_id,
        period_start=None,
        period_end=None,
        top=top,
        me=me,
        me_context=ctx,
    )


@router.get("/weekly", response_model=LeaderboardOut)
async def weekly_lb(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
) -> LeaderboardOut:
    period_start, period_end = _week_period(date.today())
    stmt = (
        select(LeaderboardEntry, User)
        .join(User, User.id == LeaderboardEntry.user_id)
        .where(
            LeaderboardEntry.scope == LeaderboardScope.WEEKLY,
            LeaderboardEntry.subject_id == subject_id,
            LeaderboardEntry.period_start == period_start,
        )
        .order_by(LeaderboardEntry.rank)
        .limit(100)
    )
    rows = (await db.execute(stmt)).all()
    top = [
        LeaderRow(
            rank=e.rank,
            user_id=u.id,
            display_name=u.full_name,
            region=u.region,
            school_id=u.school_id,
            score=e.score,
            wins=e.wins,
            losses=e.losses,
            streak=e.streak,
        )
        for e, u in rows
    ]
    my_entry = (
        await db.execute(
            select(LeaderboardEntry).where(
                LeaderboardEntry.user_id == user.id,
                LeaderboardEntry.subject_id == subject_id,
                LeaderboardEntry.scope == LeaderboardScope.WEEKLY,
                LeaderboardEntry.period_start == period_start,
            )
        )
    ).scalar_one_or_none()
    me = (
        LeaderRow(
            rank=my_entry.rank,
            user_id=user.id,
            display_name=user.full_name,
            region=user.region,
            school_id=user.school_id,
            score=my_entry.score,
            wins=my_entry.wins,
            losses=my_entry.losses,
            streak=my_entry.streak,
        )
        if my_entry
        else None
    )
    return LeaderboardOut(
        scope="weekly",
        subject_id=subject_id,
        period_start=period_start,
        period_end=period_end,
        top=top,
        me=me,
        me_context=[],
    )


@router.get("/regional", response_model=LeaderboardOut)
async def regional_lb(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
) -> LeaderboardOut:
    if not user.region:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User region not set",
        )
    top = await _live_rank_by_elo(db, subject_id, region=user.region, limit=100)
    my_rank, me = await _live_rank_of_user(db, subject_id, user, region=user.region)
    ctx = (
        await _context_window(db, subject_id, me.score, region=user.region)
        if me
        else []
    )
    period_start, period_end = _month_period(date.today())
    return LeaderboardOut(
        scope="regional",
        subject_id=subject_id,
        period_start=period_start,
        period_end=period_end,
        top=top,
        me=me,
        me_context=ctx,
    )


@router.get("/school", response_model=LeaderboardOut)
async def school_lb(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
) -> LeaderboardOut:
    if not user.school_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User school not set",
        )
    top = await _live_rank_by_elo(db, subject_id, school_id=user.school_id, limit=100)
    my_rank, me = await _live_rank_of_user(
        db, subject_id, user, school_id=user.school_id
    )
    ctx = (
        await _context_window(db, subject_id, me.score, school_id=user.school_id)
        if me
        else []
    )
    period_start, period_end = _month_period(date.today())
    return LeaderboardOut(
        scope="school",
        subject_id=subject_id,
        period_start=period_start,
        period_end=period_end,
        top=top,
        me=me,
        me_context=ctx,
    )


@router.get("/me", response_model=MeRankOut, summary="My rank across all scopes")
async def my_ranks(
    user: CurrentUser,
    db: DbSession,
    subject_id: uuid.UUID = Query(...),
) -> MeRankOut:
    elo_row = (
        await db.execute(
            select(EloRating).where(
                EloRating.user_id == user.id, EloRating.subject_id == subject_id
            )
        )
    ).scalar_one_or_none()
    elo = elo_row.rating if elo_row else 1200

    global_rank, _ = await _live_rank_of_user(db, subject_id, user)
    regional_rank: int | None = None
    if user.region:
        regional_rank, _ = await _live_rank_of_user(
            db, subject_id, user, region=user.region
        )
    school_rank: int | None = None
    if user.school_id:
        school_rank, _ = await _live_rank_of_user(
            db, subject_id, user, school_id=user.school_id
        )

    period_start, _ = _week_period(date.today())
    weekly_entry = (
        await db.execute(
            select(LeaderboardEntry).where(
                LeaderboardEntry.user_id == user.id,
                LeaderboardEntry.subject_id == subject_id,
                LeaderboardEntry.scope == LeaderboardScope.WEEKLY,
                LeaderboardEntry.period_start == period_start,
            )
        )
    ).scalar_one_or_none()

    return MeRankOut(
        subject_id=subject_id,
        global_rank=global_rank,
        weekly_rank=weekly_entry.rank if weekly_entry else None,
        regional_rank=regional_rank,
        school_rank=school_rank,
        elo=elo,
    )


@router.get("/health", include_in_schema=False)
async def _module_health() -> dict:
    return {"module": "leaderboards", "status": "ok"}
