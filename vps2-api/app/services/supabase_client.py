"""
Calls Supabase Edge Functions from the FastAPI process.

Currently used only to trigger `notify-subscribers` after a webhook from
VPS-1 lands. All other Supabase access (auth verification, RLS reads) is
done with the user's JWT, not the service key, to keep the trust boundary
tight.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SupabaseClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._notify_url = str(settings.notify_fn_url)
        self._service_key = settings.supabase_service_key
        self._http = http

    async def trigger_notify_subscribers(self, payload: dict[str, Any]) -> None:
        try:
            resp = await self._http.post(
                self._notify_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._service_key}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.error(
                    "notify-subscribers failed",
                    extra={"status": resp.status_code, "body": resp.text[:500]},
                )
        except Exception as exc:
            # Fire-and-forget: we don't want the webhook from VPS-1 to fail
            # because Supabase is briefly unavailable.
            logger.exception("notify-subscribers crashed: %s", exc)
