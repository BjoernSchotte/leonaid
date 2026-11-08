#!/usr/bin/env python3
"""Campaign renderer switch (cutover and rollback) over HTTP and real PostgreSQL.

The primary campaign address of an action shows either the legacy public
page or the published EmDash campaign. Only a system admin switches it;
the command is revision-checked and idempotent, a rollback to legacy is the
same command, and every change leaves one audit row. Replaces the former
local-only EmDash cutover-rollback case for these rules (E-028).
Runs as a contract script in the schema gate (tools/schema/test.sh) and,
with CORE_DATABASE_URL set, under pytest.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.entrypoints.fastapi.platform import create_app

# Run as a contract script too (tools/schema/test.sh), not only under pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.integration.test_site_hosts_api import ADMIN, Fixture, settings  # noqa: E402


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    fixture = Fixture(connection)
    now = datetime.now(timezone.utc)
    day = timedelta(days=1)
    command_ids: list[str] = []
    try:
        admin_token = await fixture.user("sysadmin", system_admin=True)
        member_token = await fixture.user("member", system_admin=False)
        action = await fixture.action(
            "renderer", "active", now - day, now + 30 * day, cms=False
        )
        alias = await connection.fetchrow(
            "SELECT id, revision FROM public_action_alias WHERE action_id=$1", action
        )
        assert alias is not None
        path = f"/api/v1/actions/{action}/redirect-aliases/{alias['id']}/renderer"
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ADMIN
            ) as client:

                async def put(
                    token: str, revision: int, renderer: str, command: UUID
                ) -> httpx.Response:
                    command_ids.append(f"campaign-renderer:{command}")
                    return await client.put(
                        path,
                        json={
                            "commandId": str(command),
                            "revision": revision,
                            "renderer": renderer,
                        },
                        headers={
                            "Origin": ADMIN,
                            "Cookie": f"__Host-leonaid_session={token}",
                        },
                    )

                def error(response: httpx.Response) -> str:
                    code: str = response.json()["error"]["code"]
                    return code

                async def state() -> tuple[bool, int]:
                    row = await connection.fetchrow(
                        "SELECT campaign_redirect, revision FROM public_action_alias WHERE id=$1",
                        alias["id"],
                    )
                    assert row is not None
                    return row["campaign_redirect"], row["revision"]

                start = alias["revision"]
                # Not a system admin: refused, nothing changes.
                refused = await put(member_token, start, "campaign", uuid4())
                assert refused.status_code == 403, refused.text
                assert await state() == (False, start)

                # Cutover to the campaign renderer.
                cutover = uuid4()
                switched = await put(admin_token, start, "campaign", cutover)
                assert switched.status_code == 200, switched.text
                assert switched.headers["cache-control"] == "no-store"
                body: dict[str, Any] = switched.json()
                assert body["renderer"] == "campaign"
                assert body["revision"] == start + 1
                assert await state() == (True, start + 1)

                # Same command again: the stored result, no second change.
                replay = await put(admin_token, start, "campaign", cutover)
                assert replay.status_code == 200 and replay.json() == body
                assert await state() == (True, start + 1)
                # Same command ID with other data: refused.
                reused = await put(admin_token, start, "legacy", cutover)
                assert reused.status_code == 409, reused.text
                assert error(reused) == "idempotency_conflict"

                # A stale revision is refused.
                stale = await put(admin_token, start, "legacy", uuid4())
                assert stale.status_code == 409, stale.text
                assert error(stale) == "campaign_alias_revision_conflict"
                assert await state() == (True, start + 1)

                # Rollback to legacy is the same audited command.
                rollback = await put(admin_token, start + 1, "legacy", uuid4())
                assert rollback.status_code == 200, rollback.text
                assert rollback.json()["renderer"] == "legacy"
                assert await state() == (False, start + 2)

        audit = await connection.fetch(
            "SELECT payload->>'previousRenderer' AS before, "
            "payload->>'newRenderer' AS after FROM audit_event "
            "WHERE event_type='campaign_renderer.changed' AND entity_id=$1 "
            "ORDER BY occurred_at",
            alias["id"],
        )
        assert [(row["before"], row["after"]) for row in audit] == [
            ("legacy", "campaign"),
            ("campaign", "legacy"),
        ], audit
    finally:
        await connection.execute(
            "DELETE FROM audit_event WHERE action_id = ANY($1::uuid[])",
            list(fixture.actions.values()),
        )
        await connection.execute(
            "DELETE FROM command_receipt WHERE idempotency_key = ANY($1::text[])",
            command_ids,
        )
        await fixture.cleanup()
        await connection.close()
    print(
        "campaign-renderer-api: OK: system-admin only, revision-checked, "
        "idempotent cutover, audited rollback to legacy"
    )


def test_campaign_renderer_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
