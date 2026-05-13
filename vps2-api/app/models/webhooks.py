from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .signals import Direction, GekkoBasic, GekkoDetailed, KeyLevels, Recommendation, Symbol


class SignalWebhook(BaseModel):
    """
    Payload posted by VPS-1 to POST /internal/signal-webhook whenever Gekko
    produces a STRONG_GO or GO. The schema is owned by VPS-1; any additive
    change there must keep this model deserializing.
    """

    signal_id: int = Field(description="vps1 signal id")
    symbol: Symbol
    direction: Direction
    recommendation: Recommendation
    conviction: int = Field(ge=1, le=10)
    entry_price: Decimal | None = None
    sl_price: Decimal | None = None
    tp_price: Decimal | None = None
    key_levels: KeyLevels | None = None
    gekko_basic: GekkoBasic | None = None
    gekko_detailed: GekkoDetailed | None = None
    tools_used: list[str] = Field(default_factory=list)
    score: Decimal | None = None
    market_regime: str | None = None
    produced_at: datetime
