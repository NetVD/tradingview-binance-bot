"""
Internal endpoints called by VPS-1 (not the iOS app).

Auth: shared `X-Service-Token` header. Constant-time comparison.
"""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.metrics import vps1_webhook_received_total
from app.models.webhooks import SignalWebhook
from app.services import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


def verify_service_token(
    x_service_token: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if x_service_token is None or not hmac.compare_digest(x_service_token, settings.service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid service token")


@router.post(
    "/signal-webhook",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_service_token)],
)
async def signal_webhook(
    request: Request,
    payload: SignalWebhook,
    background: BackgroundTasks,
) -> dict[str, str]:
    """
    VPS-1 → VPS-2 fan-in.

    Strategy: persist synchronously (so we can replay later from
    signal_cache if a downstream call fails), but fan out APNS asynchronously
    so VPS-1 isn't kept waiting on Apple.
    """
    try:
        await cache.upsert_signal(request.app.state.db, payload)
    except Exception as exc:
        logger.exception("failed to persist webhook payload")
        # Park the payload in the dead-letter table for manual replay.
        async with request.app.state.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO signal_dead_letter (payload, error) VALUES ($1::jsonb, $2)",
                payload.model_dump_json(),
                str(exc),
            )
        raise HTTPException(status_code=500, detail="persist failed") from exc

    vps1_webhook_received_total.labels(
        symbol=payload.symbol, recommendation=payload.recommendation
    ).inc()

    background.add_task(
        request.app.state.supabase.trigger_notify_subscribers,
        {
            "signal_id": payload.signal_id,
            "symbol": payload.symbol,
            "direction": payload.direction,
            "recommendation": payload.recommendation,
            "conviction": payload.conviction,
            "entry_price": str(payload.entry_price) if payload.entry_price else None,
            "headline": payload.gekko_basic.headline if payload.gekko_basic else None,
        },
    )

    return {"status": "accepted"}


@router.get("/health", dependencies=[Depends(verify_service_token)])
async def internal_health() -> dict[str, str]:
    return {"status": "ok"}
