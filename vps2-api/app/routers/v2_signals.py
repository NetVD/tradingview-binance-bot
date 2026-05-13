from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.core.tier_auth import TIER_ORDER, current_tier, require_tier
from app.models.signals import Direction, Recommendation, SignalDetail, SignalSummary, Symbol
from app.services import cache

router = APIRouter(
    prefix="/api/v2/signals",
    tags=["signals"],
    dependencies=[Depends(enforce_rate_limit)],
)


@router.get(
    "",
    response_model=list[SignalSummary],
    dependencies=[Depends(require_tier("global"))],
)
async def list_signals(
    request: Request,
    symbol: Symbol | None = Query(default=None),
    recommendation: Recommendation | None = Query(default=None),
    direction: Direction | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    tier: str = Depends(current_tier),
) -> list[SignalSummary]:
    """
    Latest signals visible to this user.

    Tier rules:
      - global  : signals from the last 24 h
      - pro+    : signals from the last 7 days (the full cache window)
    """
    if tier == "global":
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    else:
        since = None

    results = await cache.list_signals(request.app.state.db, symbol, since, limit)
    if recommendation:
        results = [s for s in results if s.recommendation == recommendation]
    if direction:
        results = [s for s in results if s.direction == direction]
    return results


@router.get(
    "/{signal_id}",
    response_model=SignalDetail,
    dependencies=[Depends(require_tier("global"))],
)
async def get_signal(
    signal_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    tier: str = Depends(current_tier),
) -> SignalDetail:
    detail = await cache.get_signal(request.app.state.db, signal_id)
    if detail is None:
        # Fall back to VPS-1 (cache miss / signal older than our retention)
        raw = await request.app.state.vps1.get_signal_detail(signal_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="signal not found")
        detail = SignalDetail.model_validate(raw)

    # Strip pro-only fields for global-tier users.
    if TIER_ORDER[tier] < TIER_ORDER["pro"]:
        detail = detail.model_copy(update={"gekko_detailed": None, "tools_used": None})

    return detail
