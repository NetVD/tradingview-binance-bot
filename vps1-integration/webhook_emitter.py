"""
Fire-and-forget webhook from VPS-1 to VPS-2.

Drop this file inside the existing bot project (e.g. agents/webhook_emitter.py)
and call `emit_signal_to_app_vps()` from `gekko_agent.py` right after a
STRONG_GO / GO analysis has been persisted.

Design rules
------------
* This function MUST NOT raise. The personal trading bot keeps running
  whether VPS-2 is up or down.
* It MUST NOT block the calling pipeline. We dispatch to a thread.
* It logs failures so they show up in your existing dashboard logs.
* Required env vars: APP_VPS_WEBHOOK_URL, SERVICE_TOKEN.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger("webhook_emitter")

_TIMEOUT_SECONDS = 5.0


def emit_signal_to_app_vps(signal_id: int, payload: dict[str, Any]) -> None:
    """
    Public entrypoint. Non-blocking — schedules the POST on a background
    thread and returns immediately.
    """
    url = os.environ.get("APP_VPS_WEBHOOK_URL")
    token = os.environ.get("SERVICE_TOKEN")
    if not url or not token:
        logger.warning(
            "webhook emitter not configured (APP_VPS_WEBHOOK_URL / SERVICE_TOKEN missing); skipping signal_id=%s",
            signal_id,
        )
        return

    thread = threading.Thread(
        target=_post,
        args=(url, token, signal_id, payload),
        name=f"app-webhook-{signal_id}",
        daemon=True,
    )
    thread.start()


def _post(url: str, token: str, signal_id: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Service-Token": token,
            "User-Agent": "skulltrading-vps1-webhook/1",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:  # noqa: S310
            if 200 <= resp.status < 300:
                logger.info("webhook delivered signal_id=%s status=%s", signal_id, resp.status)
            else:
                logger.warning(
                    "webhook non-2xx signal_id=%s status=%s body=%s",
                    signal_id,
                    resp.status,
                    resp.read()[:200],
                )
    except urlerror.HTTPError as e:
        logger.warning("webhook HTTPError signal_id=%s status=%s reason=%s", signal_id, e.code, e.reason)
    except urlerror.URLError as e:
        logger.warning("webhook URLError signal_id=%s reason=%s", signal_id, e.reason)
    except Exception as e:  # noqa: BLE001
        logger.exception("webhook unexpected error signal_id=%s: %s", signal_id, e)
