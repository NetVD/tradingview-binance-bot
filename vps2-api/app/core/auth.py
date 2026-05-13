"""
Supabase JWT verification.

The iOS app authenticates via Supabase GoTrue and presents an `Authorization:
Bearer <jwt>` header on every request. We fetch the project's JWKS once,
cache it for an hour, and validate every token against the cached keys.

We also derive the user's current tier by hitting Supabase's REST API
(authenticated as the service role) and short-circuiting through Redis
for 60s to keep latency low.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import Settings, get_settings


_JWKS_CACHE_TTL = 3600  # 1 hour


@dataclass
class AuthenticatedUser:
    id: str
    email: str | None
    raw_claims: dict[str, Any]


class _JWKSCache:
    def __init__(self) -> None:
        self._client: PyJWKClient | None = None
        self._expires_at: float = 0.0

    def get(self, jwks_url: str) -> PyJWKClient:
        now = time.time()
        if self._client is None or now > self._expires_at:
            self._client = PyJWKClient(jwks_url, cache_keys=True)
            self._expires_at = now + _JWKS_CACHE_TTL
        return self._client


_jwks_cache = _JWKSCache()
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = creds.credentials

    try:
        jwks_client = _jwks_cache.get(str(settings.supabase_jwt_jwks_url))
        signing_key = jwks_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256", "RS256"],
            audience=settings.supabase_jwt_audience,
            issuer=settings.supabase_jwt_issuer,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired") from None
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from None

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="token missing sub")

    user = AuthenticatedUser(
        id=user_id,
        email=claims.get("email"),
        raw_claims=claims,
    )
    request.state.user = user
    return user


async def fetch_user_tier(user_id: str, settings: Settings, http: httpx.AsyncClient) -> str:
    """
    Read v_user_tier from Supabase REST as the service role.
    Returns one of: free / global / pro / personalized.
    Falls back to 'free' if the row is missing or the user's subscription
    has expired.
    """
    url = f"{settings.supabase_url}/rest/v1/v_user_tier?user_id=eq.{user_id}&select=current_tier,is_active"
    resp = await http.get(
        url,
        headers={
            "apikey": settings.supabase_service_key,
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Accept": "application/json",
        },
        timeout=5.0,
    )
    if resp.status_code != 200:
        return "free"
    rows = resp.json()
    if not rows:
        return "free"
    row = rows[0]
    if not row.get("is_active", False):
        return "free"
    return row.get("current_tier", "free")
