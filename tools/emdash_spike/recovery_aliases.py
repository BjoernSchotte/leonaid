"""Real HTTPS alias commands, durable state and replay across encrypted recovery."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import ssl
import sys
import traceback
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from tools.identity.contract import create_session

A = "20000000-0000-4000-8000-000000000001"
B = "20000000-0000-4000-8000-000000000003"
SYSTEM = UUID("10000000-0000-4000-8000-000000000001")
ORIGIN = "https://proxy:8443"
TARGET = "/campaigns/krapfentaxi-2026/"
STATE = Path("/proof/recovery-aliases.json")


async def main() -> None:
    mode = sys.argv[1]
    assert mode in {"prepare", "verify", "cleanup"}
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:

        async def snapshot() -> dict[str, list[Any]]:
            result = {}
            for table, condition, key in (
                ("public_action_alias", "true", "id"),
                (
                    "command_receipt",
                    "command_type='campaign_alias.mutate.v1'",
                    "idempotency_key",
                ),
                ("audit_event", "event_type='campaign_alias.changed'", "id"),
            ):
                result[table] = [
                    json.loads(row["value"])
                    for row in await db.fetch(
                        f"SELECT to_jsonb(t) AS value FROM {table} t WHERE {condition} ORDER BY {key}"
                    )
                ]
            result["targets"] = [
                json.loads(row["value"])
                for row in await db.fetch(
                    "SELECT jsonb_build_object('id',id,'archive_slug',archive_slug,'status',status,"
                    "'publication_starts_at',publication_starts_at,'publication_ends_at',publication_ends_at) AS value "
                    "FROM charity_action WHERE id=ANY($1::uuid[]) ORDER BY id",
                    [UUID(A), UUID(B)],
                )
            ]
            return result

        tls = ssl.create_default_context(cafile="/proof/root.crt")
        async with httpx.AsyncClient(base_url=ORIGIN, verify=tls, timeout=20) as client:

            async def mutate(command: dict[str, Any]) -> dict[str, Any]:
                # Tokens are transient; only synthetic commands/results and SQL
                # snapshots are retained in the private proof directory.
                token = await create_session(db, SYSTEM, now=datetime.now(timezone.utc))
                response = await client.request(
                    command["method"],
                    command["path"],
                    json=command["body"],
                    headers={
                        "Origin": ORIGIN,
                        "Cookie": f"__Host-leonaid_session={token}",
                    },
                )
                assert response.status_code == 200, "recovery alias command refused"
                assert response.headers["cache-control"] == "no-store"
                assert "set-cookie" not in response.headers
                result: dict[str, Any] = response.json()
                return result

            async def public_routes() -> None:
                for path in (
                    "/recovery-enabled",
                    "/recovery-enabled/",
                    "/recovery-enabled?source=recovery",
                ):
                    for method in ("GET", "HEAD"):
                        response = await client.request(method, path)
                        assert response.status_code == 302
                        assert response.headers["location"] == TARGET
                        assert response.headers["cache-control"] == "no-store"
                        assert (
                            "set-cookie" not in response.headers
                            and not response.content
                        )
                for method in ("POST", "PUT", "PATCH", "DELETE"):
                    response = await client.request(
                        method, "/recovery-enabled", headers={"Origin": ORIGIN}
                    )
                    assert response.status_code == 405
                    assert "location" not in response.headers
                for alias in (
                    "recovery-disabled",
                    "recovery-removed",
                ):
                    response = await client.get(f"/{alias}")
                    assert response.status_code == 200
                    assert response.headers["x-leonaid-public-state"] == "inactive"
                    assert response.headers["cache-control"] == "no-store"
                    assert (
                        "location" not in response.headers
                        and TARGET not in response.text
                    )
                # The preceding redirect fixture legitimately activates B in
                # Core, while its CMS record remains a private draft. Preserve
                # that distinction across restore, rather than resetting Core.
                moved_slug = await db.fetchval(
                    "SELECT archive_slug FROM charity_action WHERE id=$1", UUID(B)
                )
                assert isinstance(moved_slug, str) and moved_slug
                moved_target = f"/campaigns/{moved_slug}/"
                for method in ("GET", "HEAD"):
                    response = await client.request(method, "/recovery-moved")
                    assert response.status_code == 302
                    assert response.headers["location"] == moved_target
                    assert response.headers["cache-control"] == "no-store"
                    assert "set-cookie" not in response.headers and not response.content
                hidden = await client.get(moved_target)
                assert hidden.status_code == 404
                assert "Private second campaign before backup" not in hidden.text
                page = await client.get(TARGET)
                assert page.status_code == 200 and "data-order-form" in page.text

            if mode == "prepare":
                commands: list[dict[str, Any]] = []

                async def record(
                    method: str, path: str, body: dict[str, Any]
                ) -> dict[str, Any]:
                    command: dict[str, Any] = {
                        "method": method,
                        "path": path,
                        "body": body,
                    }
                    result = await mutate(command)
                    command["result"] = result
                    commands.append(command)
                    return result

                for name in ("enabled", "disabled", "moved", "removed"):
                    root = f"/api/v1/actions/{A}/redirect-aliases"
                    alias_id = str(uuid4())
                    alias = f"recovery-{name}"
                    await record(
                        "POST",
                        root,
                        {
                            "commandId": str(uuid4()),
                            "aliasId": alias_id,
                            "alias": alias,
                            "enabled": True,
                        },
                    )
                    if name in {"disabled", "moved"}:
                        await record(
                            "PUT",
                            f"{root}/{alias_id}",
                            {
                                "commandId": str(uuid4()),
                                "revision": 1,
                                "targetActionId": B if name == "moved" else A,
                                "alias": alias,
                                "enabled": name != "disabled",
                            },
                        )
                    elif name == "removed":
                        await record(
                            "DELETE",
                            f"{root}/{alias_id}",
                            {"commandId": str(uuid4()), "revision": 1},
                        )
                await public_routes()
                descriptor = os.open(STATE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    json.dump(
                        {"commands": commands, "snapshot": await snapshot()}, output
                    )
            else:
                saved = json.loads(STATE.read_text())
                if mode == "verify":
                    assert await snapshot() == saved["snapshot"], (
                        "restored alias rows/receipts/audit differ"
                    )
                    await public_routes()
                    for command in saved["commands"]:
                        assert await mutate(command) == command["result"], (
                            "restored replay result differs"
                        )
                        assert await snapshot() == saved["snapshot"], (
                            "old command replay changed restored state"
                        )
                    await public_routes()
                else:
                    # Only after the restored browser journey: remove our three
                    # retained aliases through Core commands, not SQL, so the
                    # existing full alias HTTP suite starts with primary aliases.
                    rows = await db.fetch(
                        "SELECT id,action_id,revision FROM public_action_alias WHERE alias=ANY($1::text[])",
                        ["recovery-enabled", "recovery-disabled", "recovery-moved"],
                    )
                    assert len(rows) == 3
                    for row in rows:
                        await mutate(
                            {
                                "method": "DELETE",
                                "path": f"/api/v1/actions/{row['action_id']}/redirect-aliases/{row['id']}",
                                "body": {
                                    "commandId": str(uuid4()),
                                    "revision": row["revision"],
                                },
                            }
                        )
            print(
                f"recovery-aliases: {mode} passed; synthetic HTTPS commands, SQL receipts/audit and anonymous routes verified"
            )
    finally:
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # Only test source line numbers, never exception messages, HTTP bodies,
        # tokens, command payloads or database values.
        lines = [
            frame.lineno
            for frame in traceback.extract_tb(error.__traceback__)
            if Path(frame.filename).name == "recovery_aliases.py"
        ]
        print(
            f"recovery-aliases: failed at test lines {lines}; private command/session state omitted",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
