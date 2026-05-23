"""Async Redis client (singleton pool)."""

from collections.abc import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=50,
        )
    return _pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency: yields an async Redis client."""
    client = Redis(connection_pool=get_pool())
    try:
        yield client
    finally:
        await client.close()


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
