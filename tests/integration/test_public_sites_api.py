#!/usr/bin/env python3
"""What a campaign host serves, canonical URLs and dynamic public origins.

specs/multi-domain §7.2, §7.3, §7.6, §7.7: ``/api/v1/public/sites/{host}``
answers only for active hosts, with the root decision, the public editions
and the history redirects; public route responses name the campaign host
URL so old paths redirect there; Core accepts an active campaign host as
public origin at once (D7); the order-confirmation link is the permanent
edition URL (D8). Runs as a contract script in the schema gate and, with
CORE_DATABASE_URL, under pytest.
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

ADMIN = "https://app.sites.leonaid.invalid"
PUBLIC = "https://sites.leonaid.invalid"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-public-sites-proof-secret-only-3",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-public-sites-proof-encrypt-32",
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


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    tag = uuid4().hex[:8]
    admin_id = uuid4()
    actions: dict[str, UUID] = {}
    hosts: dict[str, UUID] = {}
    now = datetime.now(timezone.utc)
    day = timedelta(days=1)

    def name(label: str) -> str:
        return f"{label}-{tag}.example.org"

    def slug(label: str) -> str:
        return f"lions-open-{label}-{tag}"

    async def action(label: str, status: str, starts: datetime, ends: datetime) -> UUID:
        action_id = uuid4()
        actions[label] = action_id
        await db.execute(
            "INSERT INTO charity_action (id, carrier_name, name, purpose, status, "
            "starts_on, ends_on, archive_slug, publication_starts_at, "
            "publication_ends_at) VALUES ($1, 'Lions', $2, 'Zweck', $3, $4, $5, $6, $7, $8)",
            action_id,
            f"Lions Open {label}",
            status,
            starts.date(),
            ends.date(),
            slug(label),
            starts,
            ends,
        )
        await db.execute(
            "INSERT INTO beneficiary (id, action_id, organization_name, "
            "public_description, sort_order) VALUES ($1, $2, 'Proof', 'Proof', 0)",
            uuid4(),
            action_id,
        )
        await db.execute(
            "INSERT INTO public_action_alias (alias, action_id, is_primary, enabled, "
            "campaign_redirect) VALUES ($1, $2, true, true, true)",
            f"lionsopen{label}{tag}",
            action_id,
        )
        return action_id

    async def host(label: str, status: str, redirect: UUID | None = None) -> UUID:
        host_id = uuid4()
        hosts[label] = host_id
        await db.execute(
            "INSERT INTO site_host (id, hostname, status, verification_token, "
            "created_by, redirect_to_host_id) VALUES ($1, $2, $3, $4, $5, $6)",
            host_id,
            name(label),
            status,
            "t" * 40,
            admin_id,
            redirect,
        )
        return host_id

    async def bind(
        host_id: UUID,
        label: str,
        segment: str,
        *,
        root: bool = False,
        primary: bool = True,
        ended: str | None = None,
    ) -> None:
        await db.execute(
            "INSERT INTO site_binding (site_host_id, action_id, edition_segment, "
            "at_root, is_primary, created_by, valid_to, ended_reason) "
            "VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $7::text IS NULL THEN NULL "
            "ELSE now() END, $7)",
            host_id,
            actions[label],
            segment,
            root,
            primary,
            admin_id,
            ended,
        )

    try:
        await db.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, 'Sys', 'active')",
            admin_id,
            f"sys.{tag}@leonaid.invalid",
        )
        await action("2025", "completed", now - 400 * day, now - 30 * day)
        await action("2026", "active", now - day, now + 30 * day)
        await action("2027", "scheduled", now + 300 * day, now + 330 * day)
        await action("solo", "active", now - day, now + 30 * day)
        lionsopen = await host("lionsopen", "active")
        await host("www", "active", redirect=lionsopen)
        pending = await host("pending", "pending")
        mirror = await host("mirror", "active")
        await bind(lionsopen, "2025", "lo-2025", primary=False, ended="segment_changed")
        await bind(lionsopen, "2025", "2025")
        await bind(lionsopen, "2026", "2026", root=True)
        await bind(lionsopen, "2027", "2027")
        await bind(mirror, "2026", "2026", root=True, primary=False)
        await bind(pending, "solo", "2026", root=True)

        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=PUBLIC
            ) as client:
                site = await client.get(f"/api/v1/public/sites/{name('LionsOpen')}")
                assert site.status_code == 200, site.text
                assert site.headers["cache-control"] == "public, max-age=30"
                data = site.json()
                assert data["kind"] == "campaign"
                assert data["root"] == {"segment": "2026", "mode": "serve"}
                editions = {item["segment"]: item for item in data["editions"]}
                # The scheduled edition is not public.
                assert set(editions) == {"2025", "2026"}, editions
                assert (
                    editions["2026"]["canonicalUrl"] == f"https://{name('lionsopen')}/"
                )
                assert editions["2026"]["editionUrl"] == (
                    f"https://{name('lionsopen')}/2026/"
                )
                assert editions["2025"]["availability"] == "archive"
                assert editions["2025"]["canonicalUrl"] == (
                    f"https://{name('lionsopen')}/2025/"
                )
                assert data["history"] == [
                    {
                        "segment": "lo-2025",
                        "archiveSlug": slug("2025"),
                        "targetUrl": f"https://{name('lionsopen')}/2025/",
                        "status": 308,
                    }
                ]
                # The mirror serves the same edition; its canonical is the primary.
                site = (
                    await client.get(f"/api/v1/public/sites/{name('mirror')}")
                ).json()
                assert site["editions"][0]["canonicalUrl"] == (
                    f"https://{name('lionsopen')}/"
                )
                site = (await client.get(f"/api/v1/public/sites/{name('www')}")).json()
                assert site["kind"] == "redirect"
                assert site["redirectTo"] == f"https://{name('lionsopen')}"
                for unknown in (name("pending"), name("nothing"), "bad host"):
                    response = await client.get(f"/api/v1/public/sites/{unknown}")
                    assert response.status_code == 404, (unknown, response.text)

                # Public routes name the campaign host, so old paths redirect.
                alias = (
                    await client.get(f"/api/v1/public/actions/alias/lionsopen2026{tag}")
                ).json()
                assert (
                    alias.get("campaignHostUrl") == f"https://{name('lionsopen')}/"
                ), alias
                archive = (
                    await client.get(f"/api/v1/public/actions/archive/{slug('2025')}")
                ).json()
                assert (
                    archive["campaignHostUrl"] == f"https://{name('lionsopen')}/2025/"
                )
                campaign = (
                    await client.get(f"/api/v1/public/actions/campaign/{slug('2025')}")
                ).json()
                assert campaign["availability"] == "inactive"
                assert (
                    campaign["campaignHostUrl"] == f"https://{name('lionsopen')}/2025/"
                )
                solo = (
                    await client.get(f"/api/v1/public/actions/archive/{slug('solo')}")
                ).json()
                assert solo.get("campaignHostUrl", "missing") is None, solo
                listed = {
                    item["archiveSlug"]: item
                    for item in (await client.get("/api/v1/public/campaigns")).json()[
                        "items"
                    ]
                }
                assert listed[slug("2026")]["canonicalUrl"] == (
                    f"https://{name('lionsopen')}/"
                )
                assert listed[slug("solo")]["canonicalUrl"] == (
                    f"{PUBLIC}/campaigns/{slug('solo')}/"
                )

                # Public origin: an active campaign host at once, others never.
                for origin_host, expected in (
                    (name("lionsopen"), 422),
                    (name("pending"), 403),
                ):
                    response = await client.post(
                        "/api/v1/public/inbox-cases",
                        headers={
                            "Origin": f"https://{origin_host}",
                            "Host": origin_host,
                            "Sec-Fetch-Site": "same-origin",
                        },
                        json={},
                    )
                    assert response.status_code == expected, (
                        origin_host,
                        response.text,
                    )

                # D8: the order confirmation links the permanent edition URL.
                directory = app.state.site_directory
                assert await directory.edition_link(actions["2026"]) == (
                    f"https://{name('lionsopen')}/2026/"
                )
                assert await directory.edition_link(actions["solo"]) == (
                    f"{PUBLIC}/campaigns/{slug('solo')}/"
                )

                # A lapsed host: not served, canonical falls back (§7.7.6).
                await db.execute(
                    "UPDATE site_host SET status='disabled' WHERE id=$1", lionsopen
                )
                response = await client.get(f"/api/v1/public/sites/{name('lionsopen')}")
                assert response.status_code == 404
                alias = (
                    await client.get(f"/api/v1/public/actions/alias/lionsopen2026{tag}")
                ).json()
                # The mirror still serves 2026 and becomes its canonical host.
                assert alias["campaignHostUrl"] == f"https://{name('mirror')}/"
                archive = (
                    await client.get(f"/api/v1/public/actions/archive/{slug('2025')}")
                ).json()
                assert archive["campaignHostUrl"] is None
    finally:
        ids = list(hosts.values())
        await db.execute(
            "DELETE FROM site_binding WHERE site_host_id = ANY($1::uuid[])", ids
        )
        await db.execute(
            "UPDATE site_host SET redirect_to_host_id=NULL WHERE id = ANY($1::uuid[])",
            ids,
        )
        await db.execute("DELETE FROM site_host WHERE id = ANY($1::uuid[])", ids)
        values = list(actions.values())
        await db.execute(
            "DELETE FROM public_action_alias WHERE action_id = ANY($1::uuid[])", values
        )
        await db.execute(
            "DELETE FROM charity_action WHERE id = ANY($1::uuid[])", values
        )
        await db.execute("DELETE FROM user_account WHERE id=$1", admin_id)
        await db.close()
    print(
        "public-sites-api: OK: active hosts only, root, editions, history, redirect "
        "host, campaign host URLs, dynamic public origin, edition link"
    )


def test_public_sites_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
