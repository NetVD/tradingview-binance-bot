"""
signal_cache CRUD against the local VPS-2 Postgres.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import asyncpg

from app.models.signals import SignalDetail, SignalSummary
from app.models.webhooks import SignalWebhook

_SIGNAL_COLUMNS = """
    vps1_signal_id AS id,
    symbol,
    direction,
    recommendation,
    conviction,
    entry_price,
    sl_price,
    tp_price,
    key_levels,
    gekko_basic,
    gekko_detailed,
    tools_used,
    score,
    market_regime,
    received_at
"""


def _decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


async def upsert_signal(pool: asyncpg.Pool, payload: SignalWebhook) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO signal_cache (
                vps1_signal_id, symbol, direction, recommendation, conviction,
                entry_price, sl_price, tp_price,
                key_levels, gekko_basic, gekko_detailed, tools_used,
                score, market_regime, received_at, expires_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8,
                $9, $10, $11, $12,
                $13, $14, $15, $15 + INTERVAL '7 days'
            )
            ON CONFLICT (vps1_signal_id) DO UPDATE SET
                recommendation = EXCLUDED.recommendation,
                conviction     = EXCLUDED.conviction,
                entry_price    = EXCLUDED.entry_price,
                sl_price       = EXCLUDED.sl_price,
                tp_price       = EXCLUDED.tp_price,
                key_levels     = EXCLUDED.key_levels,
                gekko_basic    = EXCLUDED.gekko_basic,
                gekko_detailed = EXCLUDED.gekko_detailed,
                tools_used     = EXCLUDED.tools_used,
                score          = EXCLUDED.score,
                market_regime  = EXCLUDED.market_regime
            """,
            payload.signal_id,
            payload.symbol,
            payload.direction,
            payload.recommendation,
            payload.conviction,
            _decimal(payload.entry_price),
            _decimal(payload.sl_price),
            _decimal(payload.tp_price),
            json.dumps(payload.key_levels.model_dump(mode="json")) if payload.key_levels else None,
            json.dumps(payload.gekko_basic.model_dump(mode="json")) if payload.gekko_basic else None,
            json.dumps(payload.gekko_detailed.model_dump(mode="json")) if payload.gekko_detailed else None,
            json.dumps(payload.tools_used),
            _decimal(payload.score),
            payload.market_regime,
            payload.produced_at,
        )


async def list_signals(
    pool: asyncpg.Pool,
    symbol: str | None,
    since: datetime | None,
    limit: int,
) -> list[SignalSummary]:
    clauses: list[str] = []
    args: list[Any] = []
    if symbol:
        args.append(symbol)
        clauses.append(f"symbol = ${len(args)}")
    if since:
        args.append(since)
        clauses.append(f"received_at >= ${len(args)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(limit)
    query = f"""
        SELECT {_SIGNAL_COLUMNS}
        FROM signal_cache
        {where}
        ORDER BY received_at DESC
        LIMIT ${len(args)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
    return [_row_to_summary(r) for r in rows]


async def get_signal(pool: asyncpg.Pool, signal_id: int) -> SignalDetail | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_SIGNAL_COLUMNS} FROM signal_cache WHERE vps1_signal_id = $1",
            signal_id,
        )
    if row is None:
        return None
    return _row_to_detail(row)


def _row_to_summary(row: asyncpg.Record) -> SignalSummary:
    return SignalSummary(
        id=row["id"],
        symbol=row["symbol"],
        direction=row["direction"],
        recommendation=row["recommendation"],
        conviction=row["conviction"],
        entry_price=row["entry_price"],
        sl_price=row["sl_price"],
        tp_price=row["tp_price"],
        received_at=row["received_at"],
    )


def _row_to_detail(row: asyncpg.Record) -> SignalDetail:
    def _j(v: Any) -> Any:
        if v is None:
            return None
        return v if not isinstance(v, str) else json.loads(v)

    return SignalDetail(
        id=row["id"],
        symbol=row["symbol"],
        direction=row["direction"],
        recommendation=row["recommendation"],
        conviction=row["conviction"],
        entry_price=row["entry_price"],
        sl_price=row["sl_price"],
        tp_price=row["tp_price"],
        key_levels=_j(row["key_levels"]),
        gekko_basic=_j(row["gekko_basic"]),
        gekko_detailed=_j(row["gekko_detailed"]),
        tools_used=_j(row["tools_used"]),
        score=row["score"],
        market_regime=row["market_regime"],
        received_at=row["received_at"],
    )
