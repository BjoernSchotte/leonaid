"""Real HTTP caller-boundary checks and unchanged Core order persistence."""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg
import httpx


async def main() -> None:
    key = os.environ["LEONAID_ORDER_SUBMISSION_KEY"]
    assert len(key) == 64, "proof caller requires its independent configured key"
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        before = await connection.fetchval("SELECT count(*) FROM commitment")
        async with httpx.AsyncClient(base_url="http://api:8000", timeout=5) as client:
            path = "/api/v1/public/actions/krapfentaxi/orders"
            cases = [
                [],
                [("X-LeonAid-Order-Key", "0" * 64)],
                [("X-LeonAid-Order-Key", key), ("X-LeonAid-Order-Key", key)],
                [("X-LeonAid-Order-Key", key + "0")],
                [("X-Forwarded-For", "127.0.0.1"), ("X-EmDash-Request", "1")],
            ]
            for headers in cases:
                for method in [
                    "GET",
                    "HEAD",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                ]:
                    response = await client.request(method, path, headers=headers)
                    assert response.status_code == 404
                    assert response.headers["cache-control"] == "no-store"
                    assert "location" not in response.headers
                    assert "set-cookie" not in response.headers
                    assert key not in response.text
            response = await client.post(
                path, headers={"X-LeonAid-Order-Key": key}, json={}
            )
            assert response.status_code == (404 if "--denied-key" in sys.argv else 422)
            assert key not in response.text
            assert (await client.get("/api/v1/platform")).status_code == 200
        assert await connection.fetchval("SELECT count(*) FROM commitment") == before
    finally:
        await connection.close()
    print(
        "order-proxy: unauthorized/duplicate/forged internal calls denied; valid caller reaches schema validation; Core order count unchanged"
    )


if __name__ == "__main__":
    asyncio.run(main())
