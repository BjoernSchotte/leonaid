"""Shared asyncpg pool construction."""

from __future__ import annotations

from typing import Any

import asyncpg


async def create_pool(
    database_url: str,
    *,
    minimum_size: int = 1,
    maximum_size: int = 10,
) -> asyncpg.Pool[Any]:
    return await asyncpg.create_pool(
        database_url,
        min_size=minimum_size,
        max_size=maximum_size,
        command_timeout=30,
    )
