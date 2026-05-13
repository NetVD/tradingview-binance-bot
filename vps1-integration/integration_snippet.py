"""
Reference snippet showing exactly what to paste into the existing
gekko_agent.py once webhook_emitter.py has been dropped into the bot
project.

The actual variable names in your bot may differ (signal vs trade,
analysis vs gekko_result, etc.). Adapt the field mapping in
build_webhook_payload() to your own domain objects.

Once SKULLTRADING_INVENTORY.md is shared, this file can be tightened to
match the precise existing names.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

# from agents.webhook_emitter import emit_signal_to_app_vps   # uncomment in-place


# ---------------------------------------------------------------------
# 1. Build the payload that VPS-2 expects.
# ---------------------------------------------------------------------
# Schema (mirrors vps2-api/app/models/webhooks.py::SignalWebhook):
#
#   {
#     "signal_id": int,
#     "symbol": "BTCUSDT" | "XAUUSDT" | "XAGUSDT",
#     "direction": "LONG" | "SHORT",
#     "recommendation": "STRONG_GO" | "GO" | "NEUTRAL" | "AVOID",
#     "conviction": 1..10,
#     "entry_price": str | null,
#     "sl_price": str | null,
#     "tp_price": str | null,
#     "key_levels": {target, invalidation, support[], resistance[]} | null,
#     "gekko_basic": {recommendation, conviction, direction, key_levels, headline} | null,
#     "gekko_detailed": {thesis, reasoning, risks[], market_regime, tools_used[]} | null,
#     "tools_used": [str],
#     "score": str | null,
#     "market_regime": str | null,
#     "produced_at": ISO8601 UTC datetime
#   }
#
# All Decimal-like fields are serialized as strings to preserve precision.

def build_webhook_payload(signal: Any, analysis: Any) -> dict[str, Any]:
    """
    Adapt to your real domain types in gekko_agent.py.
    `signal` is your existing Signal row; `analysis` is the GekkoAnalysis it produced.
    """
    def _str_decimal(v: Decimal | float | int | None) -> str | None:
        if v is None:
            return None
        return str(Decimal(str(v)))

    return {
        "signal_id": int(signal.id),
        "symbol": signal.symbol,
        "direction": signal.direction,
        "recommendation": analysis.recommendation,
        "conviction": int(analysis.conviction),
        "entry_price": _str_decimal(getattr(signal, "entry_price", None)),
        "sl_price":    _str_decimal(getattr(signal, "sl_price", None)),
        "tp_price":    _str_decimal(getattr(signal, "tp_price", None)),
        "key_levels": getattr(analysis, "key_levels", None) and {
            "target":       _str_decimal(analysis.key_levels.get("target")),
            "invalidation": _str_decimal(analysis.key_levels.get("invalidation")),
            "support":      [_str_decimal(x) for x in analysis.key_levels.get("support", [])],
            "resistance":   [_str_decimal(x) for x in analysis.key_levels.get("resistance", [])],
        },
        "gekko_basic": {
            "recommendation": analysis.recommendation,
            "conviction":     int(analysis.conviction),
            "direction":      signal.direction,
            "headline":       getattr(analysis, "headline", None),
            "key_levels":     getattr(analysis, "key_levels", None),
        },
        "gekko_detailed": {
            "thesis":        getattr(analysis, "thesis", ""),
            "reasoning":     getattr(analysis, "reasoning", ""),
            "risks":         list(getattr(analysis, "risks", []) or []),
            "market_regime": getattr(analysis, "market_regime", None),
            "tools_used":    list(getattr(analysis, "tools_used", []) or []),
        },
        "tools_used":   list(getattr(analysis, "tools_used", []) or []),
        "score":        _str_decimal(getattr(signal, "score", None)),
        "market_regime": getattr(analysis, "market_regime", None),
        "produced_at":  (getattr(analysis, "produced_at", None) or datetime.now(tz=timezone.utc)).isoformat(),
    }


# ---------------------------------------------------------------------
# 2. Call from inside gekko_agent.py
# ---------------------------------------------------------------------
# In your existing flow, immediately after Gekko produces and persists
# an analysis, add:
#
#     if analysis.recommendation in ("STRONG_GO", "GO"):
#         try:
#             payload = build_webhook_payload(signal, analysis)
#             emit_signal_to_app_vps(signal_id=signal.id, payload=payload)
#         except Exception:
#             logger.exception("webhook payload build failed; bot continues")
#
# The emitter itself is fire-and-forget on a background thread — it cannot
# break your personal trading pipeline even if VPS-2 is offline.
