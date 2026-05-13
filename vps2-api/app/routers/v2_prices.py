from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.auth import get_current_user
from app.core.rate_limit import enforce_rate_limit
from app.models.signals import PriceQuote, Symbol

router = APIRouter(
    prefix="/api/v2/prices",
    tags=["prices"],
    dependencies=[Depends(get_current_user), Depends(enforce_rate_limit)],
)


@router.get("/{symbol}", response_model=PriceQuote)
async def get_price(symbol: Symbol, request: Request) -> PriceQuote:
    """
    Real-time quote for one of our tracked symbols.

    Free tier is allowed: the iOS dashboard shows prices on the home tab
    even for non-subscribers, as a hook.
    """
    raw = await request.app.state.vps1.get_price(symbol)
    return PriceQuote.model_validate(raw)
