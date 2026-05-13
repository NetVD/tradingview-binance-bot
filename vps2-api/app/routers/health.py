from __future__ import annotations

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.models.signals import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    db_ok = False
    redis_ok = False
    vps1_ok = False

    try:
        async with request.app.state.db.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        pass

    try:
        pong = await request.app.state.redis.ping()
        redis_ok = bool(pong)
    except Exception:
        pass

    try:
        vps1_ok = await request.app.state.vps1.ping()
    except Exception:
        pass

    return HealthResponse(
        status="ok" if (db_ok and redis_ok) else "degraded",
        version=request.app.version,
        vps1_reachable=vps1_ok,
        db_reachable=db_ok,
        redis_reachable=redis_ok,
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
