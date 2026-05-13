"""
Tier-based authorization helpers.

Usage::

    @router.get("/signals/{id}", dependencies=[Depends(require_tier("global"))])
    async def get_signal(...):
        ...

The tier is fetched lazily from Supabase (via core/auth.fetch_user_tier),
cached in Redis for 60 s per user to keep latency under 5 ms on a hot path.
"""

from __future__ import annotations

from typing import Callable

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status

from .auth import AuthenticatedUser, fetch_user_tier, get_current_user
from .config import Settings, get_settings

TIER_ORDER = {"free": 0, "global": 1, "pro": 2, "personalized": 3}
TIER_CACHE_TTL = 60  # seconds


async def _get_tier(user: AuthenticatedUser, request: Request, settings: Settings) -> str:
    cache: aioredis.Redis = request.app.state.redis
    cached = await cache.get(f"tier:{user.id}")
    if cached:
        return cached.decode() if isinstance(cached, bytes) else cached

    http = request.app.state.http
    tier = await fetch_user_tier(user.id, settings, http)
    await cache.setex(f"tier:{user.id}", TIER_CACHE_TTL, tier)
    return tier


def require_tier(minimum: str) -> Callable:
    """Build a FastAPI dependency that enforces a minimum tier."""
    if minimum not in TIER_ORDER:
        raise ValueError(f"unknown tier {minimum!r}")

    async def dep(
        request: Request,
        user: AuthenticatedUser = Depends(get_current_user),
        settings: Settings = Depends(get_settings),
    ) -> AuthenticatedUser:
        tier = await _get_tier(user, request, settings)
        request.state.tier = tier
        if TIER_ORDER[tier] < TIER_ORDER[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "tier_too_low",
                    "current_tier": tier,
                    "required_tier": minimum,
                },
            )
        return user

    return dep


async def current_tier(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> str:
    tier = await _get_tier(user, request, settings)
    request.state.tier = tier
    return tier
