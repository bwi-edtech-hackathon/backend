"""Redis-backed matchmaking queue + battle state helpers.

Keys (per spec §5.6):
- mm:queue:{subject_id}:{tier}  ZSET  score=ELO, member=user_id (queued players)
- mm:wait:{user_id}             STRING  battle_id when matched
- battle:{battle_id}:state      HASH  battle live state
- battle:{battle_id}:players    SET   connected user_ids (WS sessions)
- pubsub:battle:{battle_id}     pub/sub channel for cross-connection broadcasts
- rate:battles:{user_id}:{date} STRING  daily counter (TTL 24h)
"""

from __future__ import annotations

import uuid
from datetime import date

from redis.asyncio import Redis

from app.modules.battle.elo import tier_for

QUEUE_KEY = "mm:queue:{subject_id}:{tier}"
WAIT_KEY = "mm:wait:{user_id}"
STATE_KEY = "battle:{battle_id}:state"
PLAYERS_KEY = "battle:{battle_id}:players"
PUBSUB_CHANNEL = "pubsub:battle:{battle_id}"
RATE_KEY = "rate:battles:{user_id}:{day}"

MATCHMAKING_TIMEOUT_S = 30
ELO_BAND = 150  # initial ELO band for matchmaking


def _queue_key(subject_id: uuid.UUID, rating: int) -> str:
    return QUEUE_KEY.format(subject_id=str(subject_id), tier=tier_for(rating))


async def enqueue_player(
    redis: Redis, subject_id: uuid.UUID, user_id: uuid.UUID, rating: int
) -> None:
    key = _queue_key(subject_id, rating)
    await redis.zadd(key, {str(user_id): rating})
    await redis.expire(key, MATCHMAKING_TIMEOUT_S * 3)


async def dequeue_player(redis: Redis, subject_id: uuid.UUID, user_id: uuid.UUID, rating: int) -> None:
    await redis.zrem(_queue_key(subject_id, rating), str(user_id))


async def find_opponent(
    redis: Redis, subject_id: uuid.UUID, user_id: uuid.UUID, rating: int, band: int = ELO_BAND
) -> uuid.UUID | None:
    """Pop one opponent in the ELO band. Returns None if none queued."""
    key = _queue_key(subject_id, rating)
    candidates = await redis.zrangebyscore(
        key, rating - band, rating + band, start=0, num=10
    )
    for raw in candidates:
        if raw != str(user_id):
            # Try to atomically claim
            removed = await redis.zrem(key, raw)
            if removed:
                return uuid.UUID(raw)
    return None


async def set_match(redis: Redis, user_id: uuid.UUID, battle_id: uuid.UUID) -> None:
    await redis.setex(WAIT_KEY.format(user_id=user_id), MATCHMAKING_TIMEOUT_S * 4, str(battle_id))


async def get_match(redis: Redis, user_id: uuid.UUID) -> uuid.UUID | None:
    val = await redis.get(WAIT_KEY.format(user_id=user_id))
    return uuid.UUID(val) if val else None


async def clear_match(redis: Redis, user_id: uuid.UUID) -> None:
    await redis.delete(WAIT_KEY.format(user_id=user_id))


# === Daily rate limit ===
async def can_play_ranked(redis: Redis, user_id: uuid.UUID, limit: int = 30) -> bool:
    key = RATE_KEY.format(user_id=user_id, day=date.today().isoformat())
    count = int(await redis.get(key) or 0)
    return count < limit


async def increment_battle_count(redis: Redis, user_id: uuid.UUID) -> int:
    key = RATE_KEY.format(user_id=user_id, day=date.today().isoformat())
    new_val = await redis.incr(key)
    if new_val == 1:
        await redis.expire(key, 86400)
    return new_val
