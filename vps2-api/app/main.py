from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import AsyncIterator

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import close_pool, open_pool
from app.core.logging import configure_logging
from app.core.metrics import PrometheusMiddleware
from app.routers import health, internal, v2_gekko, v2_prices, v2_signals, v2_tools
from app.services.supabase_client import SupabaseClient
from app.services.vps1_client import VPS1Client

logger = logging.getLogger(__name__)


def _app_version() -> str:
    try:
        return version("skulltrading-app-api")
    except PackageNotFoundError:
        return "0.1.0-dev"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("starting up", extra={"env": settings.app_env})

    app.state.db = await open_pool(settings.database_url)
    app.state.redis = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=False)
    app.state.http = httpx.AsyncClient(timeout=10.0)
    app.state.vps1 = VPS1Client(settings, app.state.http)
    app.state.supabase = SupabaseClient(settings, app.state.http)

    try:
        yield
    finally:
        logger.info("shutting down")
        await app.state.http.aclose()
        await app.state.redis.aclose()
        await close_pool(app.state.db)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="SkullTrading App API",
        version=_app_version(),
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.add_middleware(PrometheusMiddleware)

    app.include_router(health.router)
    app.include_router(internal.router)
    app.include_router(v2_signals.router)
    app.include_router(v2_gekko.router)
    app.include_router(v2_prices.router)
    app.include_router(v2_tools.router)

    return app


app = create_app()
