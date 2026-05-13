from __future__ import annotations

import asyncpg
from fastapi import Request


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db


async def open_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=10.0,
    )


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()
