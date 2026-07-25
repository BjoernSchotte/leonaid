"""Platform health endpoints for the real Compose stack."""

from __future__ import annotations

import os
from typing import Any

import asyncpg
import httpx
from fastapi import FastAPI, Response, status

app = FastAPI(title="LeonAid Core", version="0.0.0")


async def postgres_ready() -> dict[str, Any]:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=3)
    try:
        value = await connection.fetchval("SELECT 1")
        return {"status": "ready", "probe": value}
    finally:
        await connection.close()


async def http_ready(name: str, url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(url)
        if response.status_code >= 500:
            raise RuntimeError(f"{name} returned {response.status_code}")
        return {"status": "ready", "httpStatus": response.status_code}


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"service": "leonaid-api", "status": "live"}


@app.get("/health/ready")
async def ready(response: Response) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    probes = (
        ("postgres", postgres_ready),
        (
            "twenty",
            lambda: http_ready("twenty", os.environ["TWENTY_HEALTH_URL"]),
        ),
        (
            "rustfs",
            lambda: http_ready("rustfs", os.environ["RUSTFS_HEALTH_URL"]),
        ),
    )
    for name, probe in probes:
        try:
            checks[name] = await probe()
        except Exception as error:  # readiness must aggregate dependency failures
            checks[name] = {"status": "not-ready", "type": type(error).__name__}
    is_ready = all(check["status"] == "ready" for check in checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "service": "leonaid-api",
        "status": "ready" if is_ready else "not-ready",
        "checks": checks,
    }
