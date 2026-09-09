"""CA-verified renderer command and public redirect/rollback transport."""

from __future__ import annotations

import asyncio
import os
import ssl
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from tools.identity.contract import create_session

A = UUID("20000000-0000-4000-8000-000000000001")
B = UUID("20000000-0000-4000-8000-000000000003")
SYSTEM = UUID("10000000-0000-4000-8000-000000000001")
CHARITY = UUID("10000000-0000-4000-8000-000000000002")
FINANCE = UUID("10000000-0000-4000-8000-000000000007")
ORIGIN = "https://proxy:8443"
ROOT = f"/api/v1/actions/{A}/redirect-aliases"
CANONICAL = "/api/v1/public/actions/campaign/krapfentaxi-2026"


async def main() -> None:
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with httpx.AsyncClient(
            base_url=ORIGIN,
            verify=ssl.create_default_context(cafile="/proof/root.crt"),
            timeout=20,
        ) as client:

            async def session(actor: UUID) -> str:
                return await create_session(db, actor, now=datetime.now(timezone.utc))

            async def call(
                path: str,
                body: dict[str, Any],
                *,
                status: int = 200,
                actor: UUID | None = SYSTEM,
                cookie: str | None = None,
                origin: str = ORIGIN,
            ) -> dict[str, Any]:
                headers = {"Origin": origin}
                if actor is not None:
                    headers["Cookie"] = (
                        f"__Host-leonaid_session={cookie or await session(actor)}"
                    )
                response = await client.put(path, json=body, headers=headers)
                assert response.status_code == status
                assert response.headers["cache-control"] == "no-store"
                assert "set-cookie" not in response.headers
                result: dict[str, Any] = response.json()
                return result

            async def snapshot() -> list[list[asyncpg.Record]]:
                return [
                    await db.fetch(f"SELECT * FROM {table} ORDER BY {key}")
                    for table, key in (
                        ("public_action_alias", "id"),
                        ("charity_action", "id"),
                        ("command_receipt", "idempotency_key"),
                        ("audit_event", "id"),
                        ("commitment", "id"),
                        ("commitment_line", "id"),
                    )
                ]

            async def facts() -> dict[str, Any]:
                response = await client.get(CANONICAL)
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store"
                payload: dict[str, Any] = response.json()
                assert (
                    payload["submissionsAllowed"]
                    and payload["orderAlias"] == "krapfentaxi"
                )
                assert payload["action"]["orderForm"].pop("accessToken")
                return payload

            primary = await db.fetchrow(
                "SELECT id,revision FROM public_action_alias WHERE action_id=$1 AND is_primary",
                A,
            )
            assert primary is not None
            path = f"{ROOT}/{primary['id']}/renderer"
            body = {
                "commandId": str(uuid4()),
                "revision": primary["revision"],
                "renderer": "campaign",
            }
            before = await snapshot()
            await call(path, body, actor=None, status=401)
            await call(path, body, actor=CHARITY, status=403)
            await call(path, body, actor=FINANCE, status=403)
            await call(path, body, origin="https://untrusted.invalid", status=403)
            await call(path.replace(str(A), str(B)), body, status=404)
            for invalid in (
                {"revision": True},
                {"revision": "1"},
                {"revision": 0},
                {"renderer": "https://untrusted.invalid"},
                {"renderer": "cms"},
                {"targetActionId": str(B)},
                {"alias": "replacement"},
            ):
                await call(path, {**body, **invalid}, status=422)
            stale = await session(SYSTEM)
            await asyncio.sleep(6)  # actual configured five-second freshness
            await call(path, body, cookie=stale, status=401)
            assert await snapshot() == before
            baseline = await facts()
            archived = await client.get("/archive/krapfentaxi-2025")
            assert archived.status_code == 200
            original = await client.get("/krapfentaxi")
            assert original.status_code == 200 and "data-order-form" in original.text
            changed = await call(path, body)
            assert changed["renderer"] == "campaign"
            assert changed["revision"] == primary["revision"] + 1
            before = await snapshot()
            assert await call(path, body) == changed
            await call(path, {**body, "renderer": "legacy"}, status=409)
            await call(path, {**body, "commandId": str(uuid4())}, status=409)
            assert await snapshot() == before
            for suffix in ("", "/", "?source=synthetic", "/?source=synthetic"):
                for method in ("GET", "HEAD"):
                    redirected = await client.request(method, "/krapfentaxi" + suffix)
                    assert redirected.status_code == 302
                    assert (
                        redirected.headers["location"] == "/campaigns/krapfentaxi-2026/"
                    )
                    assert redirected.headers["cache-control"] == "no-store"
                    assert (
                        "set-cookie" not in redirected.headers
                        and not redirected.content
                    )
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                missing_origin = await client.request(method, "/krapfentaxi")
                assert missing_origin.status_code in {403, 405}
                assert "location" not in missing_origin.headers
                refused = await client.request(
                    method, "/krapfentaxi", headers={"Origin": ORIGIN}
                )
                assert refused.status_code == 405
                assert "location" not in refused.headers
            assert await facts() == baseline
            assert (
                await client.get("/archive/krapfentaxi-2025")
            ).content == archived.content
            rollback = {
                "commandId": str(uuid4()),
                "revision": changed["revision"],
                "renderer": "legacy",
            }
            restored = await call(path, rollback)
            assert restored["renderer"] == "legacy"
            before = await snapshot()
            assert await call(path, body) == changed  # never reapply an old success
            assert await call(path, rollback) == restored
            assert await snapshot() == before
            legacy = await client.get("/krapfentaxi")
            assert legacy.status_code == 200 and "data-order-form" in legacy.text
            assert "location" not in legacy.headers
            assert await facts() == baseline
            revoked = await session(SYSTEM)
            logout = await client.post(
                "/api/v1/auth/logout",
                headers={
                    "Origin": ORIGIN,
                    "Cookie": f"__Host-leonaid_session={revoked}",
                },
            )
            assert logout.is_success
            # Logout legitimately appends its own audit event. Compare the
            # denied renderer retry with the state after that completed logout.
            before = await snapshot()
            await call(path, body, cookie=revoked, status=401)
            assert await snapshot() == before
    finally:
        await db.close()
    print(
        "alias-renderer-http: actual fresh System-Admin HTTPS selection/rollback, role/CSRF/body/stale/logout denial without mutation, 302 GET/HEAD only, stable canonical order payload and historical archive, restored legacy form and stale replay without reactivation passed; no published-CMS cutover or CMS-data rollback claimed"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        lines = [
            frame.lineno
            for frame in traceback.extract_tb(error.__traceback__)
            if Path(frame.filename).name == "alias_renderer_http_proof.py"
        ]
        raise SystemExit(
            f"alias-renderer-http: failed at source lines {lines}; details withheld"
        ) from None
