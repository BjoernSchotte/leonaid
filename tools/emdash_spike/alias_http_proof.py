"""Real CA-verified HTTPS alias API, Core sessions and database effects."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from datetime import datetime, timezone
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
ROOT = f"/api/v1/actions/{A}/redirect-aliases"
ORIGIN = "https://proxy:8443"


async def main() -> None:
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        await db.execute(
            "DELETE FROM action_membership WHERE user_id=$1 AND action_id=$2",
            CHARITY,
            B,
        )
        tls = ssl.create_default_context(cafile="/proof/root.crt")
        async with httpx.AsyncClient(base_url=ORIGIN, verify=tls, timeout=15) as client:

            async def token(actor: UUID) -> str:
                return await create_session(db, actor, now=datetime.now(timezone.utc))

            async def call(
                method: str,
                path: str,
                data: dict[str, Any] | None = None,
                *,
                actor: UUID | None = CHARITY,
                status: int = 200,
                session: str | None = None,
                origin: str = ORIGIN,
            ) -> dict[str, Any]:
                headers = {"Origin": origin}
                if actor is not None:
                    headers["Cookie"] = (
                        f"__Host-leonaid_session={session or await token(actor)}"
                    )
                response = await client.request(
                    method, path, json=data, headers=headers
                )
                assert response.status_code == status, (
                    f"alias HTTPS {method}: expected {status}, got {response.status_code}"
                )
                assert response.headers["cache-control"] == "no-store"
                assert "set-cookie" not in response.headers
                payload: dict[str, Any] = response.json()
                return payload

            async def snapshot() -> list[list[asyncpg.Record]]:
                return [
                    await db.fetch(f"SELECT * FROM {table} ORDER BY {key}")
                    for table, key in (
                        ("public_action_alias", "id"),
                        ("command_receipt", "idempotency_key"),
                        ("audit_event", "id"),
                    )
                ]

            async def deny(
                method: str,
                path: str,
                data: dict[str, Any] | None,
                *,
                status: int,
                actor: UUID | None = CHARITY,
                session: str | None = None,
                origin: str = ORIGIN,
            ) -> None:
                before = await snapshot()
                await call(
                    method,
                    path,
                    data,
                    status=status,
                    actor=actor,
                    session=session,
                    origin=origin,
                )
                assert await snapshot() == before

            await deny("GET", ROOT, None, actor=None, status=401)
            await deny("GET", ROOT, None, actor=FINANCE, status=403)
            await deny("GET", f"/api/v1/actions/{B}/redirect-aliases", None, status=403)
            listing = await call("GET", ROOT)
            assert listing["canonicalPath"] == "/campaigns/krapfentaxi-2026/"
            assert len(listing["items"]) == 1 and listing["items"][0]["isPrimary"]
            original = listing["items"][0]
            body = {
                "commandId": str(uuid4()),
                "aliasId": str(uuid4()),
                "alias": "https-alias",
                "enabled": True,
            }
            await deny(
                "POST", ROOT, body, origin="https://untrusted.invalid", status=403
            )
            for invalid in (
                "campaigns",
                "email-change",
                "health",
                "https://example.org",
                "a/b",
                "a%2fb",
                "a?b",
                "a#b",
                "..",
            ):
                await deny("POST", ROOT, {**body, "alias": invalid}, status=422)
            for extra in (
                {"targetUrl": "https://example.org"},
                {"enabled": "false"},
                {"actionId": str(B)},
            ):
                await deny("POST", ROOT, {**body, **extra}, status=422)
            created = await call("POST", ROOT, body)
            assert created["aliasId"] == body["aliasId"] and created["revision"] == 1
            before = await snapshot()
            assert await call("POST", ROOT, body) == created
            assert await snapshot() == before
            await deny("POST", ROOT, {**body, "alias": "different"}, status=409)
            await deny(
                "POST",
                ROOT,
                {**body, "commandId": str(uuid4()), "aliasId": str(uuid4())},
                status=409,
            )
            second = {
                "commandId": str(uuid4()),
                "aliasId": str(uuid4()),
                "alias": "second-https-alias",
                "enabled": True,
            }
            await call("POST", ROOT, second)
            listing = await call("GET", ROOT)
            assert [item["alias"] for item in listing["items"]] == [
                "krapfentaxi",
                "https-alias",
                "second-https-alias",
            ]
            path = f"{ROOT}/{body['aliasId']}"
            edit = {
                "commandId": str(uuid4()),
                "revision": 1,
                "targetActionId": str(A),
                "alias": "renamed-https-alias",
                "enabled": False,
            }
            updated = await call("PUT", path, edit)
            assert updated["revision"] == 2 and updated["enabled"] is False
            listed = await call("GET", ROOT)
            assert any(
                item["alias"] == "renamed-https-alias" and not item["enabled"]
                for item in listed["items"]
            )
            await deny("PUT", path, {**edit, "commandId": str(uuid4())}, status=409)
            await deny(
                "PUT",
                path,
                {**edit, "commandId": str(uuid4()), "revision": True},
                status=422,
            )
            move = {
                **edit,
                "commandId": str(uuid4()),
                "revision": 2,
                "targetActionId": str(B),
                "enabled": True,
            }
            await deny("PUT", path, move, status=403)
            moved = await call("PUT", path, move, actor=SYSTEM)
            assert moved["actionId"] == str(B) and moved["revision"] == 3
            assert await call("PUT", path, move, actor=SYSTEM) == moved
            await deny("POST", ROOT, body, status=403)
            moved_path = f"/api/v1/actions/{B}/redirect-aliases/{body['aliasId']}"
            # Grant actual responsibility for B; the same Charity Admin can
            # now move between both owned actions without System Admin status.
            await db.execute(
                "INSERT INTO action_membership(id,action_id,user_id,role,active_from) VALUES($1,$2,$3,'charity_admin',clock_timestamp())",
                uuid4(),
                B,
                CHARITY,
            )
            owned_move = {
                **move,
                "commandId": str(uuid4()),
                "revision": 3,
                "targetActionId": str(A),
            }
            returned = await call("PUT", moved_path, owned_move)
            assert returned["actionId"] == str(A) and returned["revision"] == 4
            assert await call("PUT", moved_path, owned_move) == returned
            await deny(
                "PUT", moved_path, {**owned_move, "commandId": str(uuid4())}, status=404
            )
            moved_path = path
            removed_body = {"commandId": str(uuid4()), "revision": 4}
            removed = await call("DELETE", moved_path, removed_body, actor=SYSTEM)
            assert removed["removed"] is True
            before = await snapshot()
            assert (
                await call("DELETE", moved_path, removed_body, actor=SYSTEM) == removed
            )
            assert await snapshot() == before
            await deny(
                "DELETE",
                f"{ROOT}/{original['aliasId']}",
                {"commandId": str(uuid4()), "revision": original["revision"]},
                status=409,
            )
            # Actual five-second fixture freshness expiry; no clock patching.
            stale = await token(CHARITY)
            await asyncio.sleep(6)
            await call("GET", ROOT, session=stale)
            await deny(
                "POST",
                ROOT,
                {
                    **body,
                    "commandId": str(uuid4()),
                    "aliasId": str(uuid4()),
                    "alias": "stale-session",
                },
                session=stale,
                status=401,
            )
            fresh = await token(CHARITY)
            await db.execute(
                "UPDATE action_membership SET active_until=clock_timestamp() WHERE user_id=$1 AND action_id=$2",
                CHARITY,
                A,
            )
            await deny("GET", ROOT, None, session=fresh, status=403)
            await deny(
                "POST",
                ROOT,
                {
                    **body,
                    "commandId": str(uuid4()),
                    "aliasId": str(uuid4()),
                    "alias": "withdrawn",
                },
                session=fresh,
                status=403,
            )
            rows = await db.fetch(
                "SELECT payload FROM audit_event WHERE entity_id=$1 AND event_type='campaign_alias.changed' ORDER BY occurred_at",
                UUID(str(body["aliasId"])),
            )
            assert len(rows) == 5
            assert json.loads(rows[2]["payload"])["newTarget"] == str(B)
            assert (await call("GET", ROOT, actor=SYSTEM))["items"][0] == original
            race_token = await token(SYSTEM)
            race_headers = {
                "Origin": ORIGIN,
                "Cookie": f"__Host-leonaid_session={race_token}",
            }
            claims = [
                {
                    "commandId": str(uuid4()),
                    "aliasId": str(uuid4()),
                    "alias": "https-race",
                    "enabled": True,
                }
                for _ in range(2)
            ]
            races = await asyncio.gather(
                *(
                    client.post(ROOT, json=claim, headers=race_headers)
                    for claim in claims
                )
            )
            assert sorted(response.status_code for response in races) == [200, 409]
            assert all(
                response.headers["cache-control"] == "no-store" for response in races
            )
            assert (
                await db.fetchval(
                    "SELECT count(*) FROM public_action_alias WHERE alias='https-race'"
                )
                == 1
            )
            identical = {
                "commandId": str(uuid4()),
                "aliasId": str(uuid4()),
                "alias": "https-retry-race",
                "enabled": True,
            }
            replays = await asyncio.gather(
                *(
                    client.post(ROOT, json=identical, headers=race_headers)
                    for _ in range(2)
                )
            )
            assert all(response.status_code == 200 for response in replays)
            assert replays[0].json() == replays[1].json()
            assert (
                await db.fetchval(
                    "SELECT count(*) FROM audit_event WHERE entity_id=$1 AND event_type='campaign_alias.changed'",
                    UUID(str(identical["aliasId"])),
                )
                == 1
            )
            # Revoke through the real Core endpoint, then retain the old cookie.
            logout = await client.post("/api/v1/auth/logout", headers=race_headers)
            assert logout.is_success
            await deny("GET", ROOT, None, actor=SYSTEM, session=race_token, status=401)
            await deny(
                "POST", ROOT, identical, actor=SYSTEM, session=race_token, status=401
            )
            suspended = await token(SYSTEM)
            await db.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1", SYSTEM
            )
            await deny("GET", ROOT, None, actor=SYSTEM, session=suspended, status=401)
            await deny(
                "POST", ROOT, identical, actor=SYSTEM, session=suspended, status=401
            )
        print(
            "alias-http: actual CA-verified HTTPS list/create/update/disable/move/remove, fresh Core sessions and expiry, role/withdrawal/CSRF denial, strict bodies, canonical path, revisions, concurrent claims and replays, Core logout and account suspension, protected primary and real SQL/audit effects passed"
        )
    finally:
        await db.close()


asyncio.run(main())
