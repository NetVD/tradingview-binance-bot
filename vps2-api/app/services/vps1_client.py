"""
Thin client over the VPS-1 (existing bot) HTTP API.

We only call endpoints that already exist on VPS-1 (per
SKULLTRADING_INVENTORY.md). Authentication is by the shared service
token; VPS-1 also IP-whitelists VPS-2.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.core.metrics import vps1_proxy_call_total


class VPS1Client:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._base = str(settings.vps1_base_url).rstrip("/")
        self._token = settings.service_token
        self._http = http

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Service-Token": self._token, "Accept": "application/json"}

    async def get_price(self, symbol: str) -> dict[str, Any]:
        return await self._get(f"/api/v2/internal/prices/{symbol}", endpoint="prices")

    async def get_crypto_score(self, symbol: str) -> dict[str, Any]:
        return await self._get(f"/api/v2/internal/crypto-score/{symbol}", endpoint="crypto_score")

    async def leverage_calc(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._get(
            "/api/v2/internal/leverage-calculator", endpoint="leverage_calc", params=params
        )

    async def backtest(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/v2/internal/backtest", endpoint="backtest", json=body)

    async def get_signal_detail(self, signal_id: int) -> dict[str, Any] | None:
        try:
            return await self._get(
                f"/api/v2/internal/signals/{signal_id}", endpoint="signal_detail"
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise

    async def ping(self) -> bool:
        try:
            await self._get("/api/v2/internal/health", endpoint="health", timeout=3.0)
            return True
        except Exception:
            return False

    async def _get(
        self,
        path: str,
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        resp = await self._http.get(
            f"{self._base}{path}", headers=self._headers, params=params, timeout=timeout
        )
        vps1_proxy_call_total.labels(endpoint=endpoint, status=str(resp.status_code)).inc()
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"vps1: {resp.text[:200]}")
        return resp.json()

    async def _post(
        self,
        path: str,
        *,
        endpoint: str,
        json: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        resp = await self._http.post(
            f"{self._base}{path}", headers=self._headers, json=json, timeout=timeout
        )
        vps1_proxy_call_total.labels(endpoint=endpoint, status=str(resp.status_code)).inc()
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"vps1: {resp.text[:200]}")
        return resp.json()
