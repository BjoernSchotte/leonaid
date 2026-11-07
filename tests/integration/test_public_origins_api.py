#!/usr/bin/env python3
"""Admin and public origins over HTTP: full FastAPI app and real PostgreSQL.

specs/multi-domain §6.3: the public host may call /api/v1/public/* with CORS
but never with credentials; every other endpoint accepts only the admin
origin. Runs as a contract script in the schema gate (tools/schema/test.sh)
and, with CORE_DATABASE_URL set, under pytest.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from leonaid.configuration import Settings
from leonaid.entrypoints.fastapi.platform import create_app

ADMIN = "https://app.origins.leonaid.invalid"
PUBLIC = "https://origins.leonaid.invalid"
ALIAS = "https://www.origins.leonaid.invalid"
FOREIGN = "https://evil.leonaid.invalid"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-origins-proof-secret-only-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-origins-proof-encryption-32-chars",
            "LEONAID_PUBLIC_BASE_URL": ADMIN,
            "LEONAID_SITE_BASE_URL": PUBLIC,
            "LEONAID_ALLOWED_ORIGINS": ADMIN,
            "LEONAID_PUBLIC_ORIGINS": f"{PUBLIC},{ALIAS}",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )


def preflight(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }


async def main() -> None:
    # The schema gate runs without the recovery volume.
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    app = create_app(settings())
    public_path = "/api/v1/public/inbox-cases"
    member_path = "/api/v1/auth/login"
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("192.0.2.40", 1234)),
            base_url=PUBLIC,
        ) as client:
            for origin in (PUBLIC, ALIAS):
                # Same-origin: Caddy forwards the browser's Host unchanged.
                own_host = origin.split("://", 1)[1]
                response = await client.options(
                    public_path, headers={**preflight(origin), "Host": own_host}
                )
                assert response.status_code == 204, response.text
                assert response.headers["access-control-allow-origin"] == origin
                assert "access-control-allow-credentials" not in response.headers
                # Invalid body: reaching validation proves CSRF accepted it.
                response = await client.post(
                    public_path,
                    headers={
                        "Origin": origin,
                        "Host": own_host,
                        "Sec-Fetch-Site": "same-origin",
                    },
                    json={},
                )
                assert response.status_code == 422, response.text
                assert response.headers["access-control-allow-origin"] == origin
                assert "access-control-allow-credentials" not in response.headers
                # A public origin never reaches a member endpoint.
                response = await client.options(member_path, headers=preflight(origin))
                assert response.status_code == 403, response.text
                assert response.json()["error"]["code"] == "cors_origin_rejected"
                response = await client.post(
                    member_path,
                    headers={"Origin": origin},
                    json={"email": "nobody@leonaid.invalid"},
                )
                assert response.status_code == 403, response.text
                assert response.json()["error"]["code"] == "csrf_rejected"
                assert "access-control-allow-origin" not in response.headers
            # A public page never reaches the public API of another host: the
            # admin host (same-site, it would carry the admin cookies) or the
            # public host from an alias page.
            for origin, host in (
                (PUBLIC, ADMIN.split("://", 1)[1]),
                (ALIAS, PUBLIC.split("://", 1)[1]),
            ):
                response = await client.options(
                    public_path, headers={**preflight(origin), "Host": host}
                )
                assert response.status_code == 403, response.text
                assert response.json()["error"]["code"] == "cors_origin_rejected"
                response = await client.post(
                    public_path,
                    headers={
                        "Origin": origin,
                        "Host": host,
                        "Sec-Fetch-Site": "same-site",
                    },
                    json={},
                )
                assert response.status_code == 403, response.text
                assert response.json()["error"]["code"] == "csrf_rejected"
                assert "access-control-allow-origin" not in response.headers
            # The admin origin keeps credentialed CORS on every endpoint.
            response = await client.options(public_path, headers=preflight(ADMIN))
            assert response.status_code == 204, response.text
            assert response.headers["access-control-allow-credentials"] == "true"
            response = await client.options(member_path, headers=preflight(ADMIN))
            assert response.status_code == 204, response.text
            assert response.headers["access-control-allow-credentials"] == "true"
            # Unknown origins stay rejected, also on the public API.
            response = await client.options(public_path, headers=preflight(FOREIGN))
            assert response.status_code == 403, response.text
            response = await client.post(
                public_path, headers={"Origin": FOREIGN}, json={}
            )
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "csrf_rejected"
    print(
        "public-origins-api: OK: public host CORS without credentials on its own "
        "host's public API only; cross-host and foreign origins rejected; admin "
        "origin credentialed"
    )


def test_public_origins_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
