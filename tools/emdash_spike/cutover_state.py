"""Real primary cutover commands and preservation of newer Core orders."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from tools.identity.contract import create_session

A = UUID("20000000-0000-4000-8000-000000000001")
SYSTEM = UUID("10000000-0000-4000-8000-000000000001")
ORIGIN = "https://proxy:8443"
STATE = Path("/proof/cutover-state.json")


async def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    mode = sys.argv[1]
    assert mode in {"activate", "freeze", "rollback", "verify"}
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with httpx.AsyncClient(
            base_url=ORIGIN,
            verify=ssl.create_default_context(cafile="/proof/root.crt"),
            timeout=20,
        ) as client:

            async def primary() -> dict[str, Any]:
                raw = await db.fetchval(
                    "SELECT to_jsonb(a) FROM public_action_alias a WHERE action_id=$1 AND is_primary",
                    A,
                )
                assert raw is not None
                row: dict[str, Any] = json.loads(raw)
                assert row["alias"] == "krapfentaxi" and row["enabled"]
                return row

            async def select(revision: int, renderer: str) -> dict[str, Any]:
                row = await primary()
                token = await create_session(db, SYSTEM, now=datetime.now(timezone.utc))
                response = await client.put(
                    f"/api/v1/actions/{A}/redirect-aliases/{row['id']}/renderer",
                    headers={
                        "Origin": ORIGIN,
                        "Cookie": f"__Host-leonaid_session={token}",
                    },
                    json={
                        "commandId": str(uuid4()),
                        "revision": revision,
                        "renderer": renderer,
                    },
                )
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store"
                assert "set-cookie" not in response.headers
                result: dict[str, Any] = response.json()
                assert result["renderer"] == renderer
                return result

            async def order_state() -> dict[str, list[str]]:
                return {
                    table: [
                        row["data"]
                        for row in await db.fetch(
                            f"SELECT to_jsonb(t)::text AS data FROM {table} t {condition} ORDER BY {key}"
                        )
                    ]
                    for table, key, condition in (
                        ("commitment", "id", ""),
                        ("commitment_line", "id", ""),
                        ("consent_record", "id", ""),
                        (
                            "command_receipt",
                            "idempotency_key",
                            "WHERE command_type='create_public_order_v1'",
                        ),
                        (
                            "audit_event",
                            "id",
                            "WHERE event_type='public_order_created'",
                        ),
                        ("charity_action", "id", ""),
                    )
                }

            if mode == "activate":
                row = await primary()
                assert not row["campaign_redirect"]
                page = await client.get("/campaigns/krapfentaxi-2026/")
                assert page.status_code == 200
                assert "Published imported campaign webkit" in page.text
                assert "data-order-form" in page.text
                result = await select(row["revision"], "campaign")
                redirected = await client.get("/krapfentaxi")
                assert redirected.status_code == 302
                assert redirected.headers["location"] == "/campaigns/krapfentaxi-2026/"
                state = {"original": row, "selection": result}
                fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as output:
                    json.dump(state, output)
            else:
                assert not STATE.is_symlink() and STATE.stat().st_nlink == 1
                assert STATE.stat().st_mode & 0o777 == 0o600
                state = json.loads(STATE.read_text())
                if mode == "freeze":
                    state["orders"] = await order_state()
                    assert len(state["orders"]["command_receipt"]) >= 48
                    state["aliases"] = [
                        json.loads(row["data"])
                        for row in await db.fetch(
                            "SELECT to_jsonb(a)::text AS data FROM public_action_alias a ORDER BY id"
                        )
                    ]
                elif mode == "rollback":
                    state["rollback"] = await select(
                        state["selection"]["revision"], "legacy"
                    )
                    page = await client.get("/krapfentaxi")
                    assert page.status_code == 200 and "data-order-form" in page.text
                    assert "location" not in page.headers
                else:
                    assert await order_state() == state["orders"]
                    actual = [
                        json.loads(row["data"])
                        for row in await db.fetch(
                            "SELECT to_jsonb(a)::text AS data FROM public_action_alias a ORDER BY id"
                        )
                    ]
                    expected = state["aliases"]
                    for row in expected:
                        if row["id"] == state["original"]["id"]:
                            row["campaign_redirect"] = False
                            row["revision"] = state["rollback"]["revision"]
                    assert actual == expected
                if mode != "verify":
                    STATE.write_text(json.dumps(state))
    finally:
        await db.close()
    print(
        f"cutover-state: {mode} passed; real Core command/alias identity and complete newer order rows verified"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        lines = [
            frame.lineno
            for frame in traceback.extract_tb(error.__traceback__)
            if Path(frame.filename).name == "cutover_state.py"
        ]
        raise SystemExit(
            f"cutover-state: failed at source lines {lines}; details withheld"
        ) from None
