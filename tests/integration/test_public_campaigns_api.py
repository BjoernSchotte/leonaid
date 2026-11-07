#!/usr/bin/env python3
"""Public home list of active campaigns over HTTP and real PostgreSQL.

specs/multi-domain §6.5: only actions that are active and inside their
publication window are listed, each with the page that shows it on the
public host. Runs as a contract script in the schema gate
(tools/schema/test.sh) and, with CORE_DATABASE_URL set, under pytest.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.configuration import Settings
from leonaid.entrypoints.fastapi.platform import create_app

ADMIN = "https://app.campaigns.leonaid.invalid"
PUBLIC = "https://campaigns.leonaid.invalid"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-campaigns-proof-secret-only-32-chars",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-campaigns-proof-encrypt-32-chars",
            "LEONAID_PUBLIC_BASE_URL": ADMIN,
            "LEONAID_SITE_BASE_URL": PUBLIC,
            "LEONAID_ALLOWED_ORIGINS": ADMIN,
            "LEONAID_PUBLIC_ORIGINS": PUBLIC,
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )


class Fixture:
    """Six actions: three listed, three not."""

    def __init__(self) -> None:
        self.tag = uuid4().hex[:10]
        self.actions: dict[str, UUID] = {}

    def slug(self, name: str) -> str:
        return f"home-{name}-{self.tag}"

    async def insert(self, connection: asyncpg.Connection) -> None:  # type: ignore[type-arg]
        now = datetime.now(timezone.utc)
        hour = timedelta(hours=1)
        day = timedelta(days=1)
        rows = (
            # name, status, publication start, publication end, alias, CMS page
            ("cms", "active", now - 3 * day, now + day, "primary", True),
            ("alias", "active", now - 2 * day, now + day, "primary", False),
            ("plain", "active", now - day, now + day, None, False),
            ("draft", "draft", now - day, now + day, None, False),
            ("scheduled", "active", now + hour, now + day, None, False),
            ("ended", "active", now - 2 * day, now - hour, None, False),
        )
        for name, status, starts, ends, alias, cms in rows:
            action_id = uuid4()
            self.actions[name] = action_id
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug, publication_starts_at, publication_ends_at
                )
                VALUES ($1, 'Lions Club Proof', $2, $3, $4,
                        '2026-01-01', '2099-12-31', $5, $6, $7)
                """,
                action_id,
                f"Home {name} {self.tag}",
                f"Zweck {name}",
                status,
                self.slug(name),
                starts,
                ends,
            )
            if alias is not None:
                await connection.execute(
                    "INSERT INTO public_action_alias "
                    "(alias, action_id, is_primary, enabled, campaign_redirect) "
                    "VALUES ($1, $2, true, true, $3)",
                    f"home{name}{self.tag}",
                    action_id,
                    cms,
                )

    async def remove(self, connection: asyncpg.Connection) -> None:  # type: ignore[type-arg]
        ids = list(self.actions.values())
        await connection.execute(
            "DELETE FROM public_action_alias WHERE action_id = ANY($1::uuid[])", ids
        )
        await connection.execute(
            "DELETE FROM charity_action WHERE id = ANY($1::uuid[])", ids
        )


async def main() -> None:
    # The schema gate runs without the recovery volume.
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    fixture = Fixture()
    try:
        await fixture.insert(connection)
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=PUBLIC
            ) as client:
                response = await client.get(
                    "/api/v1/public/campaigns",
                    params={"availability": "active"},
                    headers={"Origin": PUBLIC},
                )
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"].startswith(
                    "public, max-age=60"
                )
                assert "access-control-allow-credentials" not in response.headers
                items = [
                    item
                    for item in response.json()["items"]
                    if item["archiveSlug"].endswith(fixture.tag)
                ]
                # Newest publication start first; draft, scheduled, ended absent.
                assert [item["archiveSlug"] for item in items] == [
                    fixture.slug("plain"),
                    fixture.slug("alias"),
                    fixture.slug("cms"),
                ], items
                paths = {item["archiveSlug"]: item["canonicalPath"] for item in items}
                assert (
                    paths[fixture.slug("cms")] == f"/campaigns/{fixture.slug('cms')}/"
                )
                assert paths[fixture.slug("alias")] == f"/homealias{fixture.tag}"
                assert (
                    paths[fixture.slug("plain")] == f"/archive/{fixture.slug('plain')}"
                )
                for item in items:
                    assert item["canonicalUrl"] == PUBLIC + item["canonicalPath"]
                    assert set(item) == {
                        "archiveSlug",
                        "name",
                        "purpose",
                        "carrierName",
                        "presentationTheme",
                        "startsOn",
                        "endsOn",
                        "canonicalPath",
                        "canonicalUrl",
                    }
                response = await client.get(
                    "/api/v1/public/campaigns", params={"availability": "archive"}
                )
                assert response.status_code == 422, response.text
    finally:
        await fixture.remove(connection)
        await connection.close()
    print(
        "public-campaigns-api: OK: active campaigns listed newest first with "
        "their public page; draft, scheduled and ended actions absent"
    )


def test_public_campaigns_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
