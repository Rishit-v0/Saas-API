import os
import time

import redis.asyncio as aioredis

# import redis.asyncio as redis
from fastapi import Request, status  # HTTPException,
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse  # Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter using Redis.

    Strategy: For each client (identified by IP), store a sorted set in Redis
    where each member is a request timestamp. To check the limit:
    1. Remove timestamps older than the window
    2. Count remaining timestamps
    3. If count >= limit, reject. Otherwise, add current timestamp and allow.

    This is the "sliding window log" algorithm — accurate but uses more memory
    than the simpler "fixed window counter" approach.
    """

    def __init__(
        self,
        app,
        request_per_window: int = 60,
        window_seconds: int = 60,
        exclude_paths: list = [],
    ):
        super().__init__(app)
        self.request_per_window = request_per_window
        self.window_seconds = window_seconds
        self.exclude_paths = exclude_paths or ["/", "/docs", "/openapi.json", "/health"]
        self.redis = None  # Will be initialized in startup event

    async def get_redis(self):
        if self.redis is None:
            self.redis = await aioredis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
                encoding="utf-8",
            )
        return self.redis

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for exempt paths
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        client_ip = request.headers.get("X-Forwarded-For", request.client.host)

        redis_key = f"rate_limit:{client_ip}"
        try:

            redis_client = await self.get_redis()
            now = int(time.time())
            window_start = now - self.window_seconds

            # Sliding window using Redis sorted set:
            # - Score = timestamp, Member = unique request ID (timestamp as string)
            # Remove requests outside the current window
            await redis_client.zremrangebyscore(redis_key, 0, window_start)

            # Count requests in the current window
            request_count = await redis_client.zcard(redis_key)

            if request_count >= self.request_per_window:
                oldest = await redis_client.zrange(redis_key, 0, 0, withscores=True)
                retry_after = (
                    self.window_seconds - (now - oldest[0][1])
                    if oldest
                    else self.window_seconds
                )

                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded. Try again later.",
                        "retry_after_seconds": retry_after,
                        "limit": self.request_per_window,
                        "window_seconds": self.window_seconds,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            await redis_client.zadd(redis_key, {str(now): now})

            await redis_client.expire(
                redis_key, self.window_seconds * 2
            )  # Set expiration to prevent memory bloat

        except Exception:
            pass

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.request_per_window)
        response.headers["X-RateLimit-Remaining"] = str(self.window_seconds)
        return response
