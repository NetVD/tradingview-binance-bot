"""
Per-user fixed-window rate limiter backed by Redis.

We keep a counter `rl:{user_id}:{minute_bucket}` with a 70 s TTL. If the
counter exceeds `RATE_LIMIT_PER_MINUTE` we return 429.

This is intentionally simple: a token bucket would be friendlier under
burst, but a fixed window is enough to stop runaway clients and is
trivially correct.
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status

from .auth import AuthenticatedUser, get_current_user
from .config import Settings, get_settings


async def enforce_rate_limit(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    cache: aioredis.Redis = request.app.state.redis
    bucket = int(time.time() // 60)
    key = f"rl:{user.id}:{bucket}"
    pipe = cache.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 70)
    count, _ = await pipe.execute()
    if count > settings.rate_limit_per_minute:
        retry_after = 60 - int(time.time() % 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "limit_per_minute": settings.rate_limit_per_minute},
            headers={"Retry-After": str(retry_after)},
        )
