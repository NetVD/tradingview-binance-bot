"""
Verifies the service-token gate on POST /internal/signal-webhook.

We deliberately do not hit Postgres in this unit test — we monkeypatch the
persistence layer to be a no-op. A separate integration test against a
real DB lives in tests/integration/.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    # No-op out the side effects so we don't need a live DB / Supabase.
    async def _noop_upsert(*_a, **_kw):
        return None

    async def _noop_notify(*_a, **_kw):
        return None

    monkeypatch.setattr("app.services.cache.upsert_signal", _noop_upsert)
    monkeypatch.setattr(
        "app.services.supabase_client.SupabaseClient.trigger_notify_subscribers", _noop_notify
    )

    app = create_app()
    # Replace lifespan-created state with stubs so the test client doesn't try
    # to connect to Postgres/Redis on startup.
    class _Stub:
        pass

    app.state.db = _Stub()
    app.state.redis = _Stub()
    app.state.http = _Stub()
    app.state.vps1 = _Stub()
    app.state.supabase = _Stub()

    # Bypass the lifespan by using TestClient as a context manager would normally
    # invoke startup; here we set up state manually.
    return TestClient(app)


def _payload(signal_id: int = 42) -> dict:
    return {
        "signal_id": signal_id,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "recommendation": "STRONG_GO",
        "conviction": 8,
        "entry_price": "65000.5",
        "sl_price": "63000.0",
        "tp_price": "67000.0",
        "key_levels": None,
        "gekko_basic": None,
        "gekko_detailed": None,
        "tools_used": [],
        "score": "42.7",
        "market_regime": "trending",
        "produced_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def test_internal_webhook_requires_service_token(client):
    resp = client.post("/internal/signal-webhook", json=_payload())
    assert resp.status_code == 401


def test_internal_webhook_rejects_wrong_token(client):
    resp = client.post(
        "/internal/signal-webhook",
        json=_payload(),
        headers={"X-Service-Token": "wrong"},
    )
    assert resp.status_code == 401


def test_internal_webhook_accepts_valid_token(client):
    token = get_settings().service_token
    resp = client.post(
        "/internal/signal-webhook",
        json=_payload(),
        headers={"X-Service-Token": token},
    )
    assert resp.status_code == 202
    assert resp.json() == {"status": "accepted"}


def test_internal_webhook_validates_payload(client):
    token = get_settings().service_token
    bad = _payload()
    bad["recommendation"] = "INVALID"
    resp = client.post(
        "/internal/signal-webhook",
        json=bad,
        headers={"X-Service-Token": token},
    )
    assert resp.status_code == 422
