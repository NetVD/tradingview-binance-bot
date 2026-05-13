from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.rate_limit import enforce_rate_limit
from app.core.tier_auth import require_tier
from app.models.signals import GekkoBasic, GekkoDetailed
from app.services import cache

router = APIRouter(
    prefix="/api/v2/gekko",
    tags=["gekko"],
    dependencies=[Depends(enforce_rate_limit)],
)


@router.get(
    "/{signal_id}/basic",
    response_model=GekkoBasic,
    dependencies=[Depends(require_tier("global"))],
)
async def get_gekko_basic(signal_id: int, request: Request) -> GekkoBasic:
    detail = await cache.get_signal(request.app.state.db, signal_id)
    if detail is None or detail.gekko_basic is None:
        raise HTTPException(status_code=404, detail="gekko analysis not found")
    return detail.gekko_basic


@router.get(
    "/{signal_id}/detailed",
    response_model=GekkoDetailed,
    dependencies=[Depends(require_tier("pro"))],
)
async def get_gekko_detailed(signal_id: int, request: Request) -> GekkoDetailed:
    detail = await cache.get_signal(request.app.state.db, signal_id)
    if detail is None or detail.gekko_detailed is None:
        raise HTTPException(status_code=404, detail="gekko detailed analysis not found")
    return detail.gekko_detailed
