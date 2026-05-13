from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request

from app.core.auth import get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.core.tier_auth import require_tier
from app.models.signals import Symbol

router = APIRouter(prefix="/api/v2", tags=["tools"], dependencies=[Depends(enforce_rate_limit)])


@router.get("/leverage-calc", dependencies=[Depends(get_current_user)])
async def leverage_calc(
    request: Request,
    margin_usdt: float = Query(..., gt=0),
    entry_price: float = Query(..., gt=0),
    sl_price: float = Query(..., gt=0),
    target_loss_usdt: float = Query(..., gt=0),
) -> dict[str, Any]:
    """Free tool: tier 'free' allowed."""
    return await request.app.state.vps1.leverage_calc(
        {
            "margin_usdt": margin_usdt,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "target_loss_usdt": target_loss_usdt,
        }
    )


@router.get("/crypto-score/{symbol}", dependencies=[Depends(require_tier("pro"))])
async def crypto_score(symbol: Symbol, request: Request) -> dict[str, Any]:
    return await request.app.state.vps1.get_crypto_score(symbol)


@router.post("/backtest", dependencies=[Depends(require_tier("pro"))])
async def backtest(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return await request.app.state.vps1.backtest(body)
