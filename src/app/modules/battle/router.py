"""Battle HTTP routes — matchmaking, vs-AI, recent battles, stats, live-count.

In addition to the original v1 surface, this module exposes a frontend-shaped
layer under `/api/battle/sessions` that mirrors the React client's
`BattleSession` / `BattleSummary` types and accepts string subject codes."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
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
from app.models.catalog import Question, Subject, SubjectCode, Topic
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


# ════════════════════════════════════════════════════════════════════════════
# Frontend-shaped layer — POST /api/battles/sessions, GET .../{id}, /result
# ════════════════════════════════════════════════════════════════════════════


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class _OptionView(_CamelModel):
    letter: str
    text: str


class _BattleQuestionOut(_CamelModel):
    """Matches frontend `BattleQuestion`."""

    id: str
    index: int
    topic: str
    prompt: str
    expression: str | None = None
    options: list[_OptionView]
    correct_letter: str = Field(alias="correctLetter")
    weight: float


class _BattleOpponentOut(_CamelModel):
    id: str
    name: str
    elo: int
    avatar_hue: int = Field(alias="avatarHue")


class BattleSessionOut(_CamelModel):
    """Matches frontend `BattleSession`."""

    id: str
    subject: str
    mode: str
    per_question_ms: int = Field(alias="perQuestionMs")
    total_questions: int = Field(alias="totalQuestions")
    opponent: _BattleOpponentOut
    questions: list[_BattleQuestionOut]


class StartSessionIn(BaseModel):
    subject: str | None = None
    subject_id: uuid.UUID | None = None
    mode: str = "ai"           # "ranked" | "ai" | "friend"
    bot_tier: str = "SILVER"
    opponent_id: uuid.UUID | None = None
    opponent_name: str | None = None


class BattleAnswerIn(_CamelModel):
    question_index: int = Field(alias="qIndex")
    letter: str | None = None
    answer: str | None = None
    time_ms: int = Field(default=0, alias="timeMs")


class BattleAnswerOut(_CamelModel):
    correct: bool


class BattleBreakdownItem(_CamelModel):
    q_index: int = Field(alias="qIndex")
    topic: str
    your_letter: str | None = Field(default=None, alias="yourLetter")
    your_correct: bool = Field(alias="yourCorrect")
    your_time_ms: int = Field(alias="yourTimeMs")
    opponent_letter: str | None = Field(default=None, alias="opponentLetter")
    opponent_correct: bool = Field(alias="opponentCorrect")
    opponent_time_ms: int = Field(alias="opponentTimeMs")


class BattleSummaryOut(_CamelModel):
    """Matches frontend `BattleSummary`."""

    session_id: str = Field(alias="sessionId")
    subject: str
    opponent: _BattleOpponentOut
    outcome: str       # "won" | "lost" | "draw"
    your_score: int = Field(alias="yourScore")
    opponent_score: int = Field(alias="opponentScore")
    your_correct: int = Field(alias="yourCorrect")
    opponent_correct: int = Field(alias="opponentCorrect")
    total_questions: int = Field(alias="totalQuestions")
    elo_delta: int = Field(alias="eloDelta")
    streak: int
    breakdown: list[BattleBreakdownItem]


async def _resolve_subject(db, code_or_id_payload) -> Subject:
    if getattr(code_or_id_payload, "subject_id", None):
        s = (
            await db.execute(
                select(Subject).where(Subject.id == code_or_id_payload.subject_id)
            )
        ).scalar_one_or_none()
    elif getattr(code_or_id_payload, "subject", None):
        try:
            code = SubjectCode(code_or_id_payload.subject.upper())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Unknown subject code") from e
        s = (
            await db.execute(select(Subject).where(Subject.code == code))
        ).scalar_one_or_none()
    else:
        raise HTTPException(status_code=400, detail="subject required")
    if not s:
        raise HTTPException(status_code=404, detail="Subject not found")
    return s


def _hue_for(name: str) -> int:
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    return h % 360


def _option_views(q: Question) -> list[_OptionView]:
    if not q.options:
        return []
    out: list[_OptionView] = []
    for letter in ("A", "B", "C", "D"):
        opt = q.options.get(letter)
        if opt is None:
            continue
        text = opt.get("en") if isinstance(opt, dict) else str(opt)
        out.append(_OptionView(letter=letter, text=text or ""))
    return out


def _correct_letter(q: Question) -> str:
    if isinstance(q.correct_answer, str):
        return q.correct_answer.upper()
    if isinstance(q.correct_answer, list) and q.correct_answer:
        return str(q.correct_answer[0]).upper()
    return "A"


async def _battle_session_view(db, battle: Battle) -> BattleSessionOut:
    subj = (
        await db.execute(select(Subject).where(Subject.id == battle.subject_id))
    ).scalar_one()
    qids = [uuid.UUID(lay["question_id"]) for lay in battle.question_layout]
    qrows = (
        await db.execute(select(Question).where(Question.id.in_(qids)))
    ).scalars().all()
    qmap = {q.id: q for q in qrows}
    topic_ids = {q.topic_id for q in qrows}
    topics = (
        await db.execute(select(Topic).where(Topic.id.in_(topic_ids)))
    ).scalars().all()
    tmap = {t.id: t for t in topics}

    qviews: list[_BattleQuestionOut] = []
    for layout in battle.question_layout:
        qid = uuid.UUID(layout["question_id"])
        q = qmap.get(qid)
        if not q:
            continue
        t = tmap.get(q.topic_id)
        qviews.append(
            _BattleQuestionOut(
                id=str(q.id),
                index=layout["index"],
                topic=t.name_en if t else "",
                prompt=q.body_en,
                expression=None,
                options=_option_views(q),
                correctLetter=_correct_letter(q),
                weight=float(q.points),
            )
        )
    qviews.sort(key=lambda v: v.index)

    bot_name = battle.bot_name or "Opponent"
    return BattleSessionOut(
        id=str(battle.id),
        subject=subj.code.value,
        mode="ai" if battle.mode == BattleMode.VS_AI else "ranked",
        perQuestionMs=30_000,
        totalQuestions=battle.question_count,
        opponent=_BattleOpponentOut(
            id=str(battle.player_b_id) if battle.player_b_id else f"ai-{battle.bot_tier.value.lower() if battle.bot_tier else 'silver'}",
            name=bot_name,
            elo=battle.rating_b_start or 1500,
            avatarHue=_hue_for(bot_name),
        ),
        questions=qviews,
    )


@router.post(
    "/sessions",
    response_model=BattleSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: StartSessionIn, user: CurrentUser, db: DbSession
) -> BattleSessionOut:
    """Create a new battle and return the full frontend-shaped session.

    For ranked/friend modes against another human, the WS-driven quick-match
    flow at `/quick-match` is preferred; this endpoint creates a vs-AI battle
    so the frontend can show a complete BattleSession upfront."""
    subj = await _resolve_subject(db, payload)
    my_elo = await ensure_elo_row(db, user.id, subj.id)
    try:
        tier = BotTier((payload.bot_tier or "SILVER").upper())
    except ValueError:
        tier = BotTier.SILVER
    questions = await pick_battle_questions(db, subj.id)
    if not questions:
        raise HTTPException(
            status_code=503,
            detail="No battle-suitable questions seeded — run scripts/seed_questions.py",
        )
    bot_name = payload.opponent_name or pick_bot_name()
    battle = await create_battle_record(
        db,
        subject_id=subj.id,
        mode=BattleMode.VS_AI,
        player_a_id=user.id,
        player_b_id=None,
        rating_a=my_elo.rating,
        rating_b=starting_rating(tier),
        bot_tier=tier,
        bot_name=bot_name,
        questions=questions,
    )
    return await _battle_session_view(db, battle)


async def _load_battle_for_user(
    db, battle_id_or_slug: str, user_id: uuid.UUID
) -> Battle:
    stmt = select(Battle)
    try:
        bid = uuid.UUID(battle_id_or_slug)
        stmt = stmt.where(Battle.id == bid)
    except ValueError:
        stmt = stmt.where(Battle.slug == battle_id_or_slug)
    b = (await db.execute(stmt)).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Battle not found")
    if user_id not in (b.player_a_id, b.player_b_id):
        raise HTTPException(status_code=403, detail="Not a participant")
    return b


# Literal sub-paths first so they don't collide with /sessions/{id}.


class _LiveBattleOut(_CamelModel):
    id: str
    a: dict
    b: dict
    question: int
    total: int


class _BattleHistoryItem(_CamelModel):
    id: str
    opponent_name: str = Field(alias="opponentName")
    subject: str
    score: str
    won: bool
    delta: int
    ago: str
    result: str


def _ago(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        now = datetime.utcnow()
    else:
        from datetime import UTC as _UTC

        now = datetime.now(_UTC)
    delta = now - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


@router.get("/sessions/history", response_model=list[_BattleHistoryItem])
async def battle_history(
    user: CurrentUser, db: DbSession, limit: int = Query(10, ge=1, le=50)
) -> list[_BattleHistoryItem]:
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
    subj_ids = {b.subject_id for b in rows}
    subjects = (
        await db.execute(select(Subject).where(Subject.id.in_(subj_ids)))
    ).scalars().all()
    smap = {s.id: s for s in subjects}
    out: list[_BattleHistoryItem] = []
    for b in rows:
        you_a = b.player_a_id == user.id
        you_score = b.score_a if you_a else b.score_b
        opp_score = b.score_b if you_a else b.score_a
        you_correct = b.correct_a if you_a else b.correct_b
        opp_correct = b.correct_b if you_a else b.correct_a
        won = b.winner_id == user.id
        delta = b.elo_delta_a if you_a else b.elo_delta_b
        out.append(
            _BattleHistoryItem(
                id=str(b.id),
                opponentName=b.bot_name or "Opponent",
                subject=smap[b.subject_id].code.value if b.subject_id in smap else "MATH",
                score=f"{you_score}–{opp_score}",
                won=won,
                delta=delta,
                ago=_ago(b.finished_at),
                result=f"{you_correct}–{opp_correct}",
            )
        )
    return out


@router.get("/sessions/live", response_model=list[_LiveBattleOut])
async def live_battles(db: DbSession) -> list[_LiveBattleOut]:
    rows = (
        await db.execute(
            select(Battle).where(
                Battle.status.in_([BattleStatus.READY, BattleStatus.ACTIVE])
            ).limit(20)
        )
    ).scalars().all()
    out: list[_LiveBattleOut] = []
    for b in rows:
        out.append(
            _LiveBattleOut(
                id=str(b.id),
                a={"name": "Player A", "elo": b.rating_a_start or 1500},
                b={"name": b.bot_name or "Opponent", "elo": b.rating_b_start or 1500},
                question=1,
                total=b.question_count,
            )
        )
    return out


@router.get("/sessions/{battle_id_or_slug}", response_model=BattleSessionOut)
async def get_session(
    battle_id_or_slug: str, user: CurrentUser, db: DbSession
) -> BattleSessionOut:
    battle = await _load_battle_for_user(db, battle_id_or_slug, user.id)
    return await _battle_session_view(db, battle)


@router.post(
    "/sessions/{battle_id_or_slug}/answer", response_model=BattleAnswerOut
)
async def submit_answer(
    battle_id_or_slug: str,
    payload: BattleAnswerIn,
    user: CurrentUser,
    db: DbSession,
) -> BattleAnswerOut:
    """HTTP-based answer submission for the demo BattleActive flow. The live
    WS protocol is also available at `/ws/battles/{id}`."""
    battle = await _load_battle_for_user(db, battle_id_or_slug, user.id)
    if battle.status == BattleStatus.FINISHED:
        raise HTTPException(status_code=409, detail="Battle already finished")
    layout = next(
        (lay for lay in battle.question_layout if lay["index"] == payload.question_index),
        None,
    )
    if not layout:
        raise HTTPException(status_code=400, detail="Invalid question index")
    q = (
        await db.execute(
            select(Question).where(Question.id == uuid.UUID(layout["question_id"]))
        )
    ).scalar_one()
    submitted = payload.letter or payload.answer
    from app.modules.exams.grader import grade_answer

    is_correct, _pts = grade_answer(q, submitted)

    # Score per spec §4.6.2
    seconds = (payload.time_ms or 0) / 1000.0
    speed = max(0, int((30 - seconds) * 2))
    base = 100 if is_correct else 0
    total = base + (speed if is_correct else 0)

    existing = (
        await db.execute(
            select(BattleAnswer).where(
                BattleAnswer.battle_id == battle.id,
                BattleAnswer.user_id == user.id,
                BattleAnswer.question_index == payload.question_index,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.answer = submitted
        existing.is_correct = is_correct
        existing.time_taken_ms = payload.time_ms or 0
        existing.base_points = base
        existing.speed_bonus = speed if is_correct else 0
        existing.streak_bonus = 0
        existing.total_points = total
    else:
        db.add(
            BattleAnswer(
                battle_id=battle.id,
                user_id=user.id,
                question_id=q.id,
                question_index=payload.question_index,
                answer=submitted,
                is_correct=is_correct,
                time_taken_ms=payload.time_ms or 0,
                base_points=base,
                speed_bonus=speed if is_correct else 0,
                streak_bonus=0,
                total_points=total,
            )
        )
    await db.commit()
    return BattleAnswerOut(correct=is_correct)


def _simulate_bot_breakdown(
    questions: list[Question], your_breakdown: list[BattleAnswerIn] | None = None
):
    """Deterministic bot answers (Silver tier ~75% accuracy) so the result page
    has something to render."""
    import random as _r

    rng = _r.Random(42)
    rows: list[dict] = []
    for i, q in enumerate(questions):
        correct = _correct_letter(q)
        bot_right = rng.random() < 0.75
        if bot_right:
            bot_letter = correct
        else:
            wrong = [l for l in ("A", "B", "C", "D") if l != correct]
            bot_letter = rng.choice(wrong)
        rows.append(
            {
                "qIndex": i,
                "letter": bot_letter,
                "correct": bot_letter == correct,
                "time_ms": 2_800 + rng.randint(0, 4_000),
            }
        )
    return rows


@router.post(
    "/sessions/{battle_id_or_slug}/finish", response_model=BattleSummaryOut
)
async def finish_session(
    battle_id_or_slug: str, user: CurrentUser, db: DbSession
) -> BattleSummaryOut:
    """Finalize a vs-AI battle: simulate the bot, compute the summary, persist
    scores + ELO."""
    battle = await _load_battle_for_user(db, battle_id_or_slug, user.id)
    if battle.status == BattleStatus.FINISHED:
        return await _build_summary(db, battle, user)

    # Load questions in layout order
    qids = [uuid.UUID(lay["question_id"]) for lay in battle.question_layout]
    qrows = (
        await db.execute(select(Question).where(Question.id.in_(qids)))
    ).scalars().all()
    qmap = {q.id: q for q in qrows}
    ordered_qs = [
        qmap[uuid.UUID(lay["question_id"])]
        for lay in battle.question_layout
        if uuid.UUID(lay["question_id"]) in qmap
    ]

    # Your answers (already persisted via /answer)
    your_answers = (
        await db.execute(
            select(BattleAnswer).where(
                BattleAnswer.battle_id == battle.id,
                BattleAnswer.user_id == user.id,
            )
        )
    ).scalars().all()
    your_by_idx = {a.question_index: a for a in your_answers}

    # Simulate bot
    bot_rows = _simulate_bot_breakdown(ordered_qs)
    for row in bot_rows:
        q = ordered_qs[row["qIndex"]]
        existing = (
            await db.execute(
                select(BattleAnswer).where(
                    BattleAnswer.battle_id == battle.id,
                    BattleAnswer.user_id.is_(None),
                    BattleAnswer.question_index == row["qIndex"],
                )
            )
        ).scalar_one_or_none()
        speed = max(0, int((30 - row["time_ms"] / 1000.0) * 2))
        base = 100 if row["correct"] else 0
        total = base + (speed if row["correct"] else 0)
        if existing:
            continue
        db.add(
            BattleAnswer(
                battle_id=battle.id,
                user_id=None,
                question_id=q.id,
                question_index=row["qIndex"],
                answer=row["letter"],
                is_correct=row["correct"],
                time_taken_ms=row["time_ms"],
                base_points=base,
                speed_bonus=speed if row["correct"] else 0,
                streak_bonus=0,
                total_points=total,
            )
        )

    # Aggregate
    your_total = sum(a.total_points for a in your_answers)
    your_correct = sum(1 for a in your_answers if a.is_correct)
    bot_total = sum(r["correct"] * (100 + max(0, int((30 - r["time_ms"] / 1000.0) * 2))) for r in bot_rows)
    bot_correct = sum(1 for r in bot_rows if r["correct"])

    battle.score_a = your_total
    battle.score_b = bot_total
    battle.correct_a = your_correct
    battle.correct_b = bot_correct
    battle.status = BattleStatus.FINISHED
    battle.finished_at = datetime.utcnow()
    if your_total > bot_total:
        battle.winner_id = user.id
    elif bot_total > your_total:
        battle.winner_id = None  # bot
    else:
        battle.winner_id = None

    # ELO update (capped vs AI)
    from app.modules.battle.elo import apply_elo

    my_elo = await ensure_elo_row(db, user.id, battle.subject_id)
    rating_a = my_elo.rating
    rating_b = battle.rating_b_start or 1500
    actual_a = 1.0 if your_total > bot_total else (0.5 if your_total == bot_total else 0.0)
    update = apply_elo(rating_a, rating_b, actual_a, my_elo.battles_count, 50)
    update.delta_a = max(min(update.delta_a, 12), -12)
    my_elo.rating = rating_a + update.delta_a
    my_elo.battles_count += 1
    if your_total > bot_total:
        my_elo.wins += 1
        my_elo.current_streak += 1
        my_elo.best_streak = max(my_elo.best_streak, my_elo.current_streak)
    elif your_total < bot_total:
        my_elo.losses += 1
        my_elo.current_streak = 0
    else:
        my_elo.draws += 1
        my_elo.current_streak = 0
    if my_elo.battles_count >= 10:
        my_elo.is_provisional = False
    battle.elo_delta_a = update.delta_a
    battle.elo_delta_b = -update.delta_a

    await db.commit()
    return await _build_summary(db, battle, user, your_by_idx=your_by_idx, bot_rows=bot_rows, qrows=ordered_qs)


async def _build_summary(
    db,
    battle: Battle,
    user,
    your_by_idx: dict | None = None,
    bot_rows: list | None = None,
    qrows: list | None = None,
) -> BattleSummaryOut:
    session_view = await _battle_session_view(db, battle)
    if your_by_idx is None:
        rows = (
            await db.execute(
                select(BattleAnswer).where(BattleAnswer.battle_id == battle.id)
            )
        ).scalars().all()
        your_by_idx = {a.question_index: a for a in rows if a.user_id == user.id}
        bot_by_idx = {a.question_index: a for a in rows if a.user_id is None}
    else:
        bot_by_idx = {}
        if bot_rows:
            for r in bot_rows:
                bot_by_idx[r["qIndex"]] = type("Row", (), {
                    "answer": r["letter"],
                    "is_correct": r["correct"],
                    "time_taken_ms": r["time_ms"],
                })()
    breakdown: list[BattleBreakdownItem] = []
    for q in session_view.questions:
        ya = your_by_idx.get(q.index)
        ba = bot_by_idx.get(q.index)
        breakdown.append(
            BattleBreakdownItem(
                qIndex=q.index,
                topic=q.topic,
                yourLetter=(ya.answer if ya and isinstance(ya.answer, str) else None),
                yourCorrect=bool(getattr(ya, "is_correct", False)),
                yourTimeMs=int(getattr(ya, "time_taken_ms", 0) or 0),
                opponentLetter=(ba.answer if ba and isinstance(ba.answer, str) else None),
                opponentCorrect=bool(getattr(ba, "is_correct", False)),
                opponentTimeMs=int(getattr(ba, "time_taken_ms", 0) or 0),
            )
        )
    if battle.winner_id == user.id:
        outcome = "won"
    elif battle.score_a == battle.score_b:
        outcome = "draw"
    else:
        outcome = "lost"
    my_elo = await ensure_elo_row(db, user.id, battle.subject_id)
    return BattleSummaryOut(
        sessionId=str(battle.id),
        subject=session_view.subject,
        opponent=session_view.opponent,
        outcome=outcome,
        yourScore=battle.score_a,
        opponentScore=battle.score_b,
        yourCorrect=battle.correct_a,
        opponentCorrect=battle.correct_b,
        totalQuestions=battle.question_count,
        eloDelta=battle.elo_delta_a,
        streak=my_elo.current_streak,
        breakdown=breakdown,
    )


@router.get(
    "/sessions/{battle_id_or_slug}/result", response_model=BattleSummaryOut
)
async def get_session_result(
    battle_id_or_slug: str, user: CurrentUser, db: DbSession
) -> BattleSummaryOut:
    battle = await _load_battle_for_user(db, battle_id_or_slug, user.id)
    if battle.status != BattleStatus.FINISHED:
        # Auto-finish so the frontend's result polling never deadlocks.
        return await finish_session(battle_id_or_slug, user, db)
    return await _build_summary(db, battle, user)


