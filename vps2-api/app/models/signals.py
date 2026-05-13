from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Symbol = Literal["BTCUSDT", "XAUUSDT", "XAGUSDT"]
Direction = Literal["LONG", "SHORT"]
Recommendation = Literal["STRONG_GO", "GO", "NEUTRAL", "AVOID"]


class KeyLevels(BaseModel):
    target: Decimal | None = None
    invalidation: Decimal | None = None
    support: list[Decimal] = Field(default_factory=list)
    resistance: list[Decimal] = Field(default_factory=list)


class GekkoBasic(BaseModel):
    recommendation: Recommendation
    conviction: int = Field(ge=1, le=10)
    direction: Direction
    key_levels: KeyLevels | None = None
    headline: str | None = None


class GekkoDetailed(BaseModel):
    thesis: str
    reasoning: str
    risks: list[str] = Field(default_factory=list)
    market_regime: str | None = None
    tools_used: list[str] = Field(default_factory=list)


class SignalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="vps1_signal_id")
    symbol: Symbol
    direction: Direction
    recommendation: Recommendation
    conviction: int
    entry_price: Decimal | None = None
    sl_price: Decimal | None = None
    tp_price: Decimal | None = None
    received_at: datetime


class SignalDetail(SignalSummary):
    key_levels: KeyLevels | None = None
    gekko_basic: GekkoBasic | None = None
    gekko_detailed: GekkoDetailed | None = None
    tools_used: list[str] | None = None
    score: Decimal | None = None
    market_regime: str | None = None


class PriceQuote(BaseModel):
    symbol: Symbol
    last_price: Decimal
    change_24h_pct: Decimal | None = None
    volume_24h: Decimal | None = None
    timestamp: datetime


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    vps1_reachable: bool
    db_reachable: bool
    redis_reachable: bool


class ErrorResponse(BaseModel):
    error: str
    detail: Any | None = None
