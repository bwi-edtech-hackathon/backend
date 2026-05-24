"""Battle WebSocket — live duel protocol.

Endpoint: wss://api.coachai.uz/ws/battles/{battle_id_or_slug}?token=<access_jwt>

State machine per spec §6.3:
   READY (both connected) -> countdown -> ACTIVE (per-question loop) -> FINISHED

Server-authoritative: each question is locked open for ≤30s. The server reveals
the next question after both players submit, or when the timer expires.

Server→client events:
    battle_ready | countdown | question | opponent_progress | question_result
    | battle_complete | error

Client→server events:
    answer | ping | forfeit
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.db import get_db
from app.core.deps import _ensure_demo_user
from app.core.redis import get_redis
from app.core.security import decode_token
from app.models.battle import (
    Battle,
    BattleAnswer,
    BattleMode,
    BattleStatus,
    BotTier,
    EloRating,
)
from app.models.catalog import Question
from app.models.user import User
from app.modules.battle.bots import BattleBot
from app.modules.battle.elo import apply_elo
from app.modules.battle.matchmaking import increment_battle_count

router = APIRouter()

PER_QUESTION_SECONDS = 30
COUNTDOWN_SECONDS = 3
DISCONNECT_GRACE_S = 30


# === In-memory connection registry ===
class _BattleRoom:
    def __init__(self, battle_id: uuid.UUID):
        self.battle_id = battle_id
        self.connections: dict[uuid.UUID, WebSocket] = {}
        self.answers: dict[int, dict[uuid.UUID, dict]] = {}
        self.scores: dict[uuid.UUID, int] = {}
        self.streaks: dict[uuid.UUID, int] = {}
        self.current_index: int = -1
        self.lock = asyncio.Lock()
        self.next_question_event: asyncio.Event = asyncio.Event()
        self.completed: bool = False

    async def broadcast(self, payload: dict, exclude: uuid.UUID | None = None) -> None:
        dead: list[uuid.UUID] = []
        for uid, ws in self.connections.items():
            if exclude and uid == exclude:
                continue
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:  # noqa: BLE001
                dead.append(uid)
        for uid in dead:
            self.connections.pop(uid, None)

    async def send_to(self, user_id: uuid.UUID, payload: dict) -> None:
        ws = self.connections.get(user_id)
        if ws:
            with suppress(Exception):
                await ws.send_text(json.dumps(payload))


_ROOMS: dict[uuid.UUID, _BattleRoom] = {}


def _get_room(battle_id: uuid.UUID) -> _BattleRoom:
    room = _ROOMS.get(battle_id)
    if not room:
        room = _BattleRoom(battle_id)
        _ROOMS[battle_id] = room
    return room


# === Scoring per spec §4.6.2 ===
BASE_POINTS = 100
SPEED_BONUS_MAX = 60  # max(0, 30 - sec) * 2
STREAK_BONUS = 20


def _score(is_correct: bool, time_taken_ms: int, streak: int) -> tuple[int, int, int, int]:
    if not is_correct:
        return 0, 0, 0, 0
    seconds = time_taken_ms / 1000.0
    speed = max(0, int((PER_QUESTION_SECONDS - seconds) * 2))
    streak_b = STREAK_BONUS if streak >= 3 else 0
    total = BASE_POINTS + speed + streak_b
    return BASE_POINTS, speed, streak_b, total


def _check_correct(question: Question, submitted) -> bool:
    if submitted is None:
        return False
    from app.modules.exams.grader import grade_answer

    ok, _ = grade_answer(question, submitted)
    return ok


# === Helpers ===
async def _load_battle(battle_id_or_slug: str) -> Battle | None:
    async for db in get_db():
        stmt = select(Battle)
        try:
            bid = uuid.UUID(battle_id_or_slug)
            stmt = stmt.where(Battle.id == bid)
        except ValueError:
            stmt = stmt.where(Battle.slug == battle_id_or_slug)
        return (await db.execute(stmt)).scalar_one_or_none()
    return None


async def _load_questions(question_ids: list[uuid.UUID]) -> dict[uuid.UUID, Question]:
    async for db in get_db():
        rows = (
            await db.execute(select(Question).where(Question.id.in_(question_ids)))
        ).scalars().all()
        return {q.id: q for q in rows}
    return {}


async def _opponent_summary(opponent_id: uuid.UUID | None, battle: Battle) -> dict:
    if opponent_id is None:
        return {
            "name": battle.bot_name or "AI Bot",
            "avatar": None,
            "elo": battle.rating_b_start or 1200,
            "is_bot": True,
        }
    async for db in get_db():
        user = (
            await db.execute(select(User).where(User.id == opponent_id))
        ).scalar_one_or_none()
        elo = (
            await db.execute(
                select(EloRating).where(
                    EloRating.user_id == opponent_id,
                    EloRating.subject_id == battle.subject_id,
                )
            )
        ).scalar_one_or_none()
        return {
            "name": user.full_name if user else "Opponent",
            "avatar": None,
            "elo": elo.rating if elo else 1200,
            "is_bot": False,
        }
    return {"name": "Opponent", "elo": 1200, "is_bot": False}


def _wrong_options(question: Question, correct: str) -> list[str]:
    if question.options and isinstance(question.options, dict):
        keys = [k for k in question.options.keys() if str(k).upper() != str(correct).upper()]
        return keys
    return []


async def _persist_answers_and_finalize(battle_id: uuid.UUID, room: _BattleRoom) -> dict:
    """Commit BattleAnswer rows, update Battle scores, apply ELO."""
    async for db in get_db():
        battle = (
            await db.execute(select(Battle).where(Battle.id == battle_id))
        ).scalar_one()

        for idx, per_user in room.answers.items():
            layout = next(
                (lay for lay in battle.question_layout if lay["index"] == idx), None
            )
            if not layout:
                continue
            qid = uuid.UUID(layout["question_id"])
            for uid, ans in per_user.items():
                # Skip if already in DB
                existing = (
                    await db.execute(
                        select(BattleAnswer).where(
                            BattleAnswer.battle_id == battle.id,
                            BattleAnswer.user_id == uid if uid != battle.player_a_id or uid != battle.player_b_id else None,
                            BattleAnswer.question_index == idx,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    continue
                row = BattleAnswer(
                    battle_id=battle.id,
                    user_id=uid if uid not in (None,) else None,
                    question_id=qid,
                    question_index=idx,
                    answer=ans.get("answer"),
                    is_correct=ans.get("is_correct", False),
                    time_taken_ms=ans.get("time_taken_ms", 0),
                    base_points=ans.get("base_points", 0),
                    speed_bonus=ans.get("speed_bonus", 0),
                    streak_bonus=ans.get("streak_bonus", 0),
                    total_points=ans.get("total_points", 0),
                )
                db.add(row)

        # Aggregate scores
        a_id = battle.player_a_id
        b_id = battle.player_b_id  # may be None for vs-AI
        score_a = room.scores.get(a_id, 0)
        score_b = (
            room.scores.get(b_id, 0) if b_id else room.scores.get(uuid.UUID(int=0), 0)
        )
        correct_a = sum(
            1
            for idx in room.answers
            if room.answers[idx].get(a_id, {}).get("is_correct")
        )
        correct_b = sum(
            1
            for idx in room.answers
            if (
                room.answers[idx].get(b_id, {}).get("is_correct")
                if b_id
                else room.answers[idx].get(uuid.UUID(int=0), {}).get("is_correct")
            )
        )

        battle.score_a = score_a
        battle.score_b = score_b
        battle.correct_a = correct_a
        battle.correct_b = correct_b
        battle.status = BattleStatus.FINISHED
        battle.finished_at = datetime.now(UTC)

        # Winner
        if score_a > score_b:
            winner_id = a_id
        elif score_b > score_a:
            winner_id = b_id
        else:
            winner_id = None
        battle.winner_id = winner_id

        # ELO update
        if battle.mode in (BattleMode.QUICK_MATCH, BattleMode.VS_AI):
            elo_a = (
                await db.execute(
                    select(EloRating).where(
                        EloRating.user_id == a_id,
                        EloRating.subject_id == battle.subject_id,
                    )
                )
            ).scalar_one_or_none()
            if not elo_a:
                elo_a = EloRating(user_id=a_id, subject_id=battle.subject_id)
                db.add(elo_a)
                await db.flush()
            rating_a = elo_a.rating
            battles_a = elo_a.battles_count

            if b_id:
                elo_b = (
                    await db.execute(
                        select(EloRating).where(
                            EloRating.user_id == b_id,
                            EloRating.subject_id == battle.subject_id,
                        )
                    )
                ).scalar_one_or_none()
                if not elo_b:
                    elo_b = EloRating(user_id=b_id, subject_id=battle.subject_id)
                    db.add(elo_b)
                    await db.flush()
                rating_b = elo_b.rating
                battles_b = elo_b.battles_count
            else:
                # vs-AI: synthetic opponent
                elo_b = None
                rating_b = battle.rating_b_start or 1200
                battles_b = 50  # treat bot as established

            actual_a = 1.0 if winner_id == a_id else (0.5 if winner_id is None else 0.0)
            update = apply_elo(rating_a, rating_b, actual_a, battles_a, battles_b)

            # Cap vs-AI ELO delta
            if battle.mode == BattleMode.VS_AI:
                update.delta_a = max(min(update.delta_a, 12), -12)

            elo_a.rating = rating_a + update.delta_a
            elo_a.battles_count += 1
            if winner_id == a_id:
                elo_a.wins += 1
                elo_a.current_streak += 1
                elo_a.best_streak = max(elo_a.best_streak, elo_a.current_streak)
            elif winner_id is None:
                elo_a.draws += 1
                elo_a.current_streak = 0
            else:
                elo_a.losses += 1
                elo_a.current_streak = 0
            if elo_a.battles_count >= 10:
                elo_a.is_provisional = False
            battle.elo_delta_a = update.delta_a

            if elo_b:
                elo_b.rating = rating_b + update.delta_b
                elo_b.battles_count += 1
                if winner_id == b_id:
                    elo_b.wins += 1
                    elo_b.current_streak += 1
                    elo_b.best_streak = max(elo_b.best_streak, elo_b.current_streak)
                elif winner_id is None:
                    elo_b.draws += 1
                    elo_b.current_streak = 0
                else:
                    elo_b.losses += 1
                    elo_b.current_streak = 0
                if elo_b.battles_count >= 10:
                    elo_b.is_provisional = False
                battle.elo_delta_b = update.delta_b
            else:
                battle.elo_delta_b = -update.delta_a  # symmetric for display

        await db.commit()
        return {
            "winner_id": str(winner_id) if winner_id else None,
            "score_a": score_a,
            "score_b": score_b,
            "elo_delta_a": battle.elo_delta_a,
            "elo_delta_b": battle.elo_delta_b,
        }
    return {}


# === Driver task — runs once per battle ===
async def _run_battle_loop(battle_id: uuid.UUID, battle: Battle):
    room = _get_room(battle_id)
    redis = None
    async for r in get_redis():
        redis = r
        break

    qmap = await _load_questions(
        [uuid.UUID(lay["question_id"]) for lay in battle.question_layout]
    )

    # Init scores
    room.scores[battle.player_a_id] = 0
    room.streaks[battle.player_a_id] = 0
    if battle.player_b_id:
        room.scores[battle.player_b_id] = 0
        room.streaks[battle.player_b_id] = 0

    # Wait briefly for both players to connect (for vs-AI just the human)
    expected = 2 if battle.player_b_id else 1
    waited = 0
    while len(room.connections) < expected and waited < 15:
        await asyncio.sleep(0.5)
        waited += 0.5

    # battle_ready
    a_summary = await _opponent_summary(battle.player_b_id, battle)
    b_summary = await _opponent_summary(battle.player_a_id, battle)
    await room.send_to(
        battle.player_a_id,
        {
            "type": "battle_ready",
            "battle_id": str(battle.id),
            "opponent": a_summary,
            "question_count": battle.question_count,
        },
    )
    if battle.player_b_id:
        await room.send_to(
            battle.player_b_id,
            {
                "type": "battle_ready",
                "battle_id": str(battle.id),
                "opponent": b_summary,
                "question_count": battle.question_count,
            },
        )

    # Countdown
    for s in range(COUNTDOWN_SECONDS, 0, -1):
        await room.broadcast({"type": "countdown", "seconds_remaining": s})
        await asyncio.sleep(1.0)

    # Spawn bot task for vs-AI
    bot_task: asyncio.Task | None = None
    if battle.mode == BattleMode.VS_AI and battle.bot_tier:
        bot = BattleBot(BotTier(battle.bot_tier.value))

        async def _bot_player():
            for layout in battle.question_layout:
                idx = layout["index"]
                qid = uuid.UUID(layout["question_id"])
                q = qmap.get(qid)
                if not q:
                    continue
                correct = str(q.correct_answer) if isinstance(q.correct_answer, str) else ""
                wrong = _wrong_options(q, correct)
                bot_answer = await bot.answer(
                    correct_answer=correct,
                    wrong_options=wrong,
                    difficulty=q.difficulty,
                )
                # Sleep up to bot's time
                bot_time_s = min(PER_QUESTION_SECONDS - 1, bot_answer.time_ms / 1000.0)
                await asyncio.sleep(bot_time_s)
                # Register the bot answer
                room.answers.setdefault(idx, {})
                bot_uid = uuid.UUID(int=0)  # sentinel for bot
                streak = room.streaks.get(bot_uid, 0)
                base, speed, sb, total = _score(
                    bot_answer.is_correct, bot_answer.time_ms, streak + (1 if bot_answer.is_correct else 0)
                )
                if bot_answer.is_correct:
                    room.streaks[bot_uid] = streak + 1
                else:
                    room.streaks[bot_uid] = 0
                room.scores[bot_uid] = room.scores.get(bot_uid, 0) + total
                room.answers[idx][bot_uid] = {
                    "answer": bot_answer.answer,
                    "is_correct": bot_answer.is_correct,
                    "time_taken_ms": bot_answer.time_ms,
                    "base_points": base,
                    "speed_bonus": speed,
                    "streak_bonus": sb,
                    "total_points": total,
                }
                # Notify human of opponent_progress
                await room.send_to(
                    battle.player_a_id,
                    {
                        "type": "opponent_progress",
                        "current_question": idx + 1,
                        "score": room.scores.get(bot_uid, 0),
                    },
                )
                # Wait for the question slot to advance
                while room.current_index == idx and not room.completed:
                    await asyncio.sleep(0.2)
                if room.completed:
                    return

        bot_task = asyncio.create_task(_bot_player())

    # Per-question loop
    for layout in battle.question_layout:
        if room.completed:
            break
        idx = layout["index"]
        room.current_index = idx
        room.next_question_event = asyncio.Event()
        qid = uuid.UUID(layout["question_id"])
        q = qmap.get(qid)
        if not q:
            continue
        await room.broadcast(
            {
                "type": "question",
                "index": idx,
                "total": battle.question_count,
                "question": {
                    "id": str(q.id),
                    "type": q.type.value,
                    "body_uz": q.body_uz,
                    "body_ru": q.body_ru,
                    "body_en": q.body_en,
                    "options": q.options,
                    "topic_id": str(q.topic_id),
                },
                "time_limit_seconds": PER_QUESTION_SECONDS,
            }
        )
        question_start = asyncio.get_event_loop().time()

        # Wait for both players to answer OR timeout
        async def _both_answered(_idx: int = idx) -> bool:
            per = room.answers.get(_idx, {})
            need = {battle.player_a_id}
            if battle.player_b_id:
                need.add(battle.player_b_id)
            else:
                need.add(uuid.UUID(int=0))  # bot
            return need.issubset(per.keys())

        try:
            while not await _both_answered():
                if asyncio.get_event_loop().time() - question_start > PER_QUESTION_SECONDS:
                    break
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            break

        # Reveal results
        per_q = room.answers.get(idx, {})
        bot_sentinel = uuid.UUID(int=0)
        correct_str = str(q.correct_answer)

        for viewer in (battle.player_a_id, battle.player_b_id):
            if viewer is None:
                continue
            opp = (
                battle.player_b_id if viewer == battle.player_a_id else battle.player_a_id
            ) or bot_sentinel
            mine = per_q.get(viewer) or {}
            theirs = per_q.get(opp) or {}
            await room.send_to(
                viewer,
                {
                    "type": "question_result",
                    "your_correct": bool(mine.get("is_correct", False)),
                    "opponent_correct": bool(theirs.get("is_correct", False)),
                    "your_score": room.scores.get(viewer, 0),
                    "opponent_score": room.scores.get(opp, 0),
                    "correct_answer": correct_str,
                },
            )

        room.next_question_event.set()
        await asyncio.sleep(2)

    # Persist + finalise
    summary = await _persist_answers_and_finalize(battle.id, room)
    room.completed = True
    if bot_task:
        bot_task.cancel()
        with suppress(BaseException):
            await bot_task

    # battle_complete to each
    for uid in [battle.player_a_id] + ([battle.player_b_id] if battle.player_b_id else []):
        your_total = room.scores.get(uid, 0)
        opp_uid = (
            battle.player_b_id if uid == battle.player_a_id else battle.player_a_id
        )
        if opp_uid is None:
            opp_uid = uuid.UUID(int=0)
        opp_total = room.scores.get(opp_uid, 0)
        elo_delta = (
            summary.get("elo_delta_a", 0)
            if uid == battle.player_a_id
            else summary.get("elo_delta_b", 0)
        )
        await room.send_to(
            uid,
            {
                "type": "battle_complete",
                "winner_id": summary.get("winner_id"),
                "your_total": your_total,
                "opponent_total": opp_total,
                "elo_delta": elo_delta,
            },
        )

    # Bump daily ranked counter
    if battle.mode in (BattleMode.QUICK_MATCH, BattleMode.VS_AI) and redis:
        await increment_battle_count(redis, battle.player_a_id)
        if battle.player_b_id:
            await increment_battle_count(redis, battle.player_b_id)

    # Cleanup
    _ROOMS.pop(battle.id, None)


_BATTLE_DRIVERS: dict[uuid.UUID, asyncio.Task] = {}


async def _ensure_driver(battle: Battle) -> None:
    if battle.id in _BATTLE_DRIVERS and not _BATTLE_DRIVERS[battle.id].done():
        return
    _BATTLE_DRIVERS[battle.id] = asyncio.create_task(_run_battle_loop(battle.id, battle))


# === WebSocket endpoint ===
@router.websocket("/ws/battles/{battle_id_or_slug}")
async def battle_ws(
    websocket: WebSocket,
    battle_id_or_slug: str,
    token: str | None = Query(default=None),
) -> None:
    """Live duel channel. `token` is optional in demo mode — without it the
    socket binds to the shared demo user (must also be `player_a_id` of the
    battle, which create_session ensures)."""

    user_id: uuid.UUID | None = None
    if token:
        try:
            payload = decode_token(token, expected_type="access")
            user_id = uuid.UUID(payload["sub"])
        except (jwt.InvalidTokenError, KeyError, ValueError):
            user_id = None
    if user_id is None:
        # Demo fallback — bind to the demo user.
        async for db in get_db():
            demo = await _ensure_demo_user(db)
            user_id = demo.id
            break

    battle = await _load_battle(battle_id_or_slug)
    if not battle:
        await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA, reason="battle_not_found")
        return
    if user_id not in (battle.player_a_id, battle.player_b_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="not_participant")
        return
    if battle.status == BattleStatus.FINISHED:
        await websocket.close(code=status.WS_1000_NORMAL_CLOSURE, reason="already_finished")
        return

    await websocket.accept()
    room = _get_room(battle.id)
    room.connections[user_id] = websocket
    await _ensure_driver(battle)

    # Per-question questions cache for grading
    qmap = await _load_questions(
        [uuid.UUID(lay["question_id"]) for lay in battle.question_layout]
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({"type": "error", "code": "INVALID_JSON", "message": "bad payload"})
                )
                continue

            mtype = msg.get("type")
            if mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            if mtype == "forfeit":
                room.completed = True
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE, reason="forfeit")
                break
            if mtype == "answer":
                idx = msg.get("question_index")
                ans = msg.get("answer")
                time_taken = int(msg.get("time_taken_ms", 0))
                if idx is None or idx != room.current_index:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "code": "QUESTION_INDEX_MISMATCH",
                                "message": "Answer for a different question",
                            }
                        )
                    )
                    continue
                layout = next(
                    (lay for lay in battle.question_layout if lay["index"] == idx), None
                )
                if not layout:
                    continue
                q = qmap.get(uuid.UUID(layout["question_id"]))
                if not q:
                    continue
                room.answers.setdefault(idx, {})
                if user_id in room.answers[idx]:
                    continue  # already answered
                is_correct = _check_correct(q, ans)
                streak = room.streaks.get(user_id, 0)
                base, speed, sb, total = _score(
                    is_correct, time_taken, streak + (1 if is_correct else 0)
                )
                if is_correct:
                    room.streaks[user_id] = streak + 1
                else:
                    room.streaks[user_id] = 0
                room.scores[user_id] = room.scores.get(user_id, 0) + total
                room.answers[idx][user_id] = {
                    "answer": ans,
                    "is_correct": is_correct,
                    "time_taken_ms": time_taken,
                    "base_points": base,
                    "speed_bonus": speed,
                    "streak_bonus": sb,
                    "total_points": total,
                }
                # Notify opponent of progress
                opp_id = (
                    battle.player_b_id
                    if user_id == battle.player_a_id
                    else battle.player_a_id
                )
                if opp_id:
                    await room.send_to(
                        opp_id,
                        {
                            "type": "opponent_progress",
                            "current_question": idx + 1,
                            "score": room.scores.get(user_id, 0),
                        },
                    )
                continue

            await websocket.send_text(
                json.dumps({"type": "error", "code": "UNKNOWN_TYPE", "message": mtype})
            )
    except WebSocketDisconnect:
        # Grace-period: caller can reconnect within DISCONNECT_GRACE_S
        room.connections.pop(user_id, None)
        # If the driver task is still running, it will keep going. If both
        # players disconnect, the driver will eventually finish via timeout.
        return
