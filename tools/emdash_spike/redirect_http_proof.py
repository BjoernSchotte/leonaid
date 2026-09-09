"""Real Core alias commands and anonymous CA-verified Astro redirect requests."""

from __future__ import annotations

import asyncio
import os
import ssl
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx

from tools.identity.contract import create_session

ACTION = UUID("20000000-0000-4000-8000-000000000001")
SYSTEM = UUID("10000000-0000-4000-8000-000000000001")
ORIGIN = "https://proxy:8443"
ROOT = f"/api/v1/actions/{ACTION}/redirect-aliases"
TARGET = "/campaigns/krapfentaxi-2026/"


async def main() -> None:
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        if "--outage-fixture" in sys.argv:
            await db.execute(
                "INSERT INTO public_action_alias(alias,action_id,is_primary) VALUES ('outage-redirect',$1,false)",
                ACTION,
            )
            return
        tls = ssl.create_default_context(cafile="/proof/root.crt")
        async with httpx.AsyncClient(base_url=ORIGIN, verify=tls, timeout=20) as client:

            async def mutate(
                method: str, path: str, body: dict[str, object]
            ) -> dict[str, object]:
                session = await create_session(
                    db, SYSTEM, now=datetime.now(timezone.utc)
                )
                response = await client.request(
                    method,
                    path,
                    json=body,
                    headers={
                        "Origin": ORIGIN,
                        "Cookie": f"__Host-leonaid_session={session}",
                    },
                )
                assert response.status_code == 200, (
                    f"redirect fixture command: {response.status_code}"
                )
                payload: dict[str, object] = response.json()
                return payload

            alias_id = uuid4()
            await mutate(
                "POST",
                ROOT,
                {
                    "commandId": str(uuid4()),
                    "aliasId": str(alias_id),
                    "alias": "https-redirect",
                    "enabled": True,
                },
            )
            try:
                for path in (
                    "/https-redirect",
                    "/https-redirect/",
                    "/https-redirect?source=proof",
                ):
                    for method in ("GET", "HEAD"):
                        response = await client.request(method, path)
                        assert response.status_code == 302, (
                            f"{method} {path}: {response.status_code}"
                        )
                        assert response.headers["location"] == TARGET
                        assert response.headers["cache-control"] == "no-store"
                        assert "set-cookie" not in response.headers
                        assert not response.content
                for method in ("POST", "PUT", "PATCH", "DELETE"):
                    response = await client.request(
                        method, "/https-redirect", headers={"Origin": ORIGIN}
                    )
                    assert response.status_code == 405, (
                        f"{method}: {response.status_code}"
                    )
                    assert "location" not in response.headers
                    assert response.headers["cache-control"] == "no-store"

                # The legacy primary still renders its own real order form.
                primary = await client.get("/krapfentaxi")
                assert primary.status_code == 200 and "location" not in primary.headers
                assert "data-order-form" in primary.text
                if "--published" in sys.argv:
                    destination = await client.get(TARGET)
                    assert destination.status_code == 200
                    assert "location" not in destination.headers
                    assert "data-order-form" in destination.text

                async def inactive(path: str) -> None:
                    response = await client.get(path)
                    assert response.status_code == 200
                    assert response.headers["cache-control"] == "no-store"
                    assert (
                        "location" not in response.headers
                        and TARGET not in response.text
                    )
                    assert response.headers["x-leonaid-public-state"] == "inactive"

                await inactive("/unknown-redirect")
                draft_root = "/api/v1/actions/20000000-0000-4000-8000-000000000003/redirect-aliases"
                draft_alias = uuid4()
                await mutate(
                    "POST",
                    draft_root,
                    {
                        "commandId": str(uuid4()),
                        "aliasId": str(draft_alias),
                        "alias": "https-draft",
                        "enabled": True,
                    },
                )
                try:
                    await inactive("/https-draft")
                finally:
                    await mutate(
                        "DELETE",
                        f"{draft_root}/{draft_alias}",
                        {
                            "commandId": str(uuid4()),
                            "revision": 1,
                        },
                    )
                await mutate(
                    "PUT",
                    f"{ROOT}/{alias_id}",
                    {
                        "commandId": str(uuid4()),
                        "revision": 1,
                        "targetActionId": str(ACTION),
                        "alias": "https-redirect",
                        "enabled": False,
                    },
                )
                await inactive("/https-redirect")
                await mutate(
                    "PUT",
                    f"{ROOT}/{alias_id}",
                    {
                        "commandId": str(uuid4()),
                        "revision": 2,
                        "targetActionId": str(ACTION),
                        "alias": "https-redirect",
                        "enabled": True,
                    },
                )
                assert (await client.get("/https-redirect")).status_code == 302
                original = await db.fetchrow(
                    "SELECT status,publication_starts_at,publication_ends_at FROM charity_action WHERE id=$1",
                    ACTION,
                )
                assert original is not None
                now = datetime.now(timezone.utc)
                try:
                    for status, start, end in (
                        ("active", now + timedelta(days=1), now + timedelta(days=2)),
                        ("active", now - timedelta(days=2), now - timedelta(days=1)),
                        ("active", None, None),
                    ):
                        await db.execute(
                            "UPDATE charity_action SET status=$2,publication_starts_at=$3,publication_ends_at=$4 WHERE id=$1",
                            ACTION,
                            status,
                            start,
                            end,
                        )
                        await inactive("/https-redirect")
                finally:
                    await db.execute(
                        "UPDATE charity_action SET status=$2,publication_starts_at=$3,publication_ends_at=$4 WHERE id=$1",
                        ACTION,
                        *original.values(),
                    )
                assert (await client.get("/https-redirect")).headers[
                    "location"
                ] == TARGET
                # Advance the separate Golden draft through valid lifecycle
                # states; never disable the database's transition guard.
                other = UUID("20000000-0000-4000-8000-000000000003")
                await db.execute(
                    "UPDATE charity_action SET status='scheduled' WHERE id=$1", other
                )
                await db.execute(
                    "UPDATE charity_action SET status='active',publication_starts_at=$2,publication_ends_at=$3 WHERE id=$1",
                    other,
                    now - timedelta(days=1),
                    now + timedelta(days=1),
                )
                other_slug = await db.fetchval(
                    "SELECT archive_slug FROM charity_action WHERE id=$1", other
                )
                archive_path = "/archive/krapfentaxi-2025"
                archive_before = await client.get(archive_path)
                assert archive_before.status_code == 200
                await mutate(
                    "PUT",
                    f"{ROOT}/{alias_id}",
                    {
                        "commandId": str(uuid4()),
                        "revision": 3,
                        "targetActionId": str(other),
                        "alias": "https-redirect",
                        "enabled": True,
                    },
                )
                for method in ("GET", "HEAD"):
                    moved = await client.request(method, "/https-redirect")
                    assert moved.status_code == 302
                    assert moved.headers["location"] == f"/campaigns/{other_slug}/"
                    assert moved.headers["cache-control"] == "no-store"
                canonical = await client.get(
                    "/api/v1/public/actions/campaign/krapfentaxi-2026"
                )
                assert canonical.status_code == 200
                assert canonical.json()["action"]["id"] == str(ACTION)
                assert canonical.json()["canonicalPath"] == TARGET
                archive_after = await client.get(archive_path)
                assert archive_after.status_code == 200
                assert archive_after.content == archive_before.content
                if "--published" in sys.argv:
                    unchanged = await client.get(TARGET)
                    assert (
                        unchanged.status_code == 200
                        and "location" not in unchanged.headers
                    )
                    assert "Published imported campaign webkit" in unchanged.text
                await mutate(
                    "PUT",
                    f"{draft_root}/{alias_id}",
                    {
                        "commandId": str(uuid4()),
                        "revision": 4,
                        "targetActionId": str(ACTION),
                        "alias": "https-redirect",
                        "enabled": True,
                    },
                )
                assert (await client.get("/https-redirect")).headers[
                    "location"
                ] == TARGET
            finally:
                revision = await db.fetchval(
                    "SELECT revision FROM public_action_alias WHERE id=$1", alias_id
                )
                await mutate(
                    "DELETE",
                    f"{ROOT}/{alias_id}",
                    {"commandId": str(uuid4()), "revision": revision},
                )
        print(
            "redirect-http: real Core commands and CA-verified Astro GET/HEAD 302, no mutation redirects, inactive/disabled/window withdrawal and restoration, preserved primary form, reassignment and unchanged historical archive/canonical identity passed"
        )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
