import os
from typing import Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError

# ── Redis client (singleton, lazy-initialized) ────────────────────────────────
# We use a module-level variable so the connection is reused across requests.
# Lazy init means we don't connect at import time — only on first use.
_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"),
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def cache_get(key: str) -> Optional[str]:
    """
    Retrieve a value from Redis by key.
    Returns the string value if it exists, None on miss or Redis error.
    Fails open — if Redis is down, returns None (app falls back to DB).
    """

    try:
        client = await get_redis()
        return await client.get(key)
    except RedisError:
        # Log the error in a real app, but don't raise — we want to fail open.
        return None


async def cache_set(key: str, value: str, ttl: int = 300) -> bool:
    """
    Store a string value in Redis with a TTL in seconds.
    Returns True on success, False on Redis error.
    Always set TTL — unbounded cache keys are a memory leak waiting to happen.
    Default TTL = 300 seconds (5 minutes).
    """
    try:
        client = await get_redis()
        await client.setex(key, ttl, value)
        return True
    except RedisError:
        # Log the error in a real app, but don't raise — we want to fail open.
        return False


async def cache_delete(key: str) -> bool:
    """
    Delete a key from Redis (cache invalidation).
    Call this on any write operation that changes the cached data.
    Returns True on success, False on Redis error.
    """
    try:
        client = await get_redis()
        await client.delete(key)
        return True
    except RedisError:
        # Log the error in a real app, but don't raise — we want to fail open.
        return False


async def cache_delete_pattern(pattern: str) -> int:
    """
    Delete all keys matching a pattern (e.g. 'tenant:42:*').
    Uses SCAN — non-blocking, safe for production.
    Returns number of keys deleted.
    """
    try:
        client = await get_redis()
        keys = []

        async for k in client.scan_iter(match=pattern):
            keys.append(k)
        if keys:
            return await client.delete(*keys)
        return 0
    except RedisError:
        # Log the error in a real app, but don't raise — we want to fail open.
        return 0
