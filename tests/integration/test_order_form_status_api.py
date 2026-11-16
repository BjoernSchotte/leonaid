#!/usr/bin/env python3
"""Opening and closing an action's public order form over HTTP and PostgreSQL.

A new action's order form starts as a draft, and before this switch only the
demo seed could open it. An action manager opens or closes it; the switch is
idempotent, leaves one audit row per change, refuses archived actions and
actions without a form, and the public order write path follows the status.
Runs as a contract script in the schema gate (tools/schema/test.sh) and,
with CORE_DATABASE_URL set, under pytest.
"""

from __future__ import annotations

import asyncio
import json
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


async def add_order_form(connection: asyncpg.Connection[Any], action: UUID) -> None:
    await connection.execute(
        """
        INSERT INTO action_template_snapshot (
            action_id, template_key, template_version, display_name, configuration
        )
        VALUES ($1, 'blank', 1, 'Leere Aktion', $2::jsonb)
        """,
        action,
        json.dumps({"capabilities": [], "offerings": [], "orderForm": None}),
    )
    await connection.execute(
        """
        INSERT INTO order_form_configuration (
            id, action_id, form_key, status, title, introduction,
            submit_label, require_company_name, require_contact_name,
            require_email, require_phone, require_delivery_address,
            require_billing_address, allow_message
        )
        VALUES ($1, $2, 'bestellung', 'draft', 'Bestellung', 'Bestellen',
                'Bestellen', false, true, true, false, false, true, true)
        """,
        uuid4(),
        action,
    )


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    fixture = Fixture(connection)
    now = datetime.now(timezone.utc)
    day = timedelta(days=1)
    try:
        admin_token = await fixture.user("sysadmin", system_admin=True)
        member_token = await fixture.user("member", system_admin=False)
        action = await fixture.action(
            "orderform", "active", now - day, now + 30 * day, cms=False
        )
        archived = await fixture.action(
            "orderformarchived", "archived", now - 60 * day, now - 30 * day, cms=False
        )
        formless = await fixture.action(
            "orderformnone", "active", now - day, now + 30 * day, cms=False
        )
        await add_order_form(connection, action)
        await add_order_form(connection, archived)
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ADMIN
            ) as client:

                async def put(token: str, target: UUID, active: bool) -> httpx.Response:
                    return await client.put(
                        f"/api/v1/actions/{target}/order-form/status",
                        json={"active": active},
                        headers={
                            "Origin": ADMIN,
                            "Cookie": f"__Host-leonaid_session={token}",
                        },
                    )

                async def status() -> str:
                    value = await connection.fetchval(
                        "SELECT status FROM order_form_configuration WHERE action_id=$1",
                        action,
                    )
                    return str(value)

                def error(response: httpx.Response) -> str:
                    code: str = response.json()["error"]["code"]
                    return code

                configuration = await client.get(
                    f"/api/v1/actions/{action}/configuration",
                    headers={
                        "Origin": ADMIN,
                        "Cookie": f"__Host-leonaid_session={admin_token}",
                    },
                )
                assert configuration.status_code == 200, configuration.text
                assert configuration.json()["orderForm"]["active"] is False

                # Someone who does not manage the action learns nothing.
                refused = await put(member_token, action, True)
                assert refused.status_code in (403, 404), refused.text
                assert await status() == "draft"

                opened = await put(admin_token, action, True)
                assert opened.status_code == 200, opened.text
                assert opened.headers["cache-control"] == "no-store"
                assert opened.json()["orderForm"]["active"] is True
                assert await status() == "active"
                # The same state again changes nothing.
                again = await put(admin_token, action, True)
                assert again.status_code == 200, again.text
                assert again.json()["orderForm"]["active"] is True

                closed = await put(admin_token, action, False)
                assert closed.status_code == 200, closed.text
                assert closed.json()["orderForm"]["active"] is False
                assert await status() == "inactive"

                archived_open = await put(admin_token, archived, True)
                assert archived_open.status_code == 409, archived_open.text
                assert error(archived_open) == "order_form_action_archived"
                # Closing an archived action's form stays possible.
                archived_close = await put(admin_token, archived, False)
                assert archived_close.status_code == 200, archived_close.text

                missing = await put(admin_token, formless, True)
                assert missing.status_code == 409, missing.text
                assert error(missing) == "order_form_missing"

        audit = await connection.fetch(
            "SELECT payload->>'previousStatus' AS before, payload->>'status' AS after "
            "FROM audit_event WHERE event_type='order_form_status_changed' "
            "AND action_id=$1 ORDER BY occurred_at",
            action,
        )
        assert [(row["before"], row["after"]) for row in audit] == [
            ("draft", "active"),
            ("active", "inactive"),
        ], audit
    finally:
        actions = list(fixture.actions.values())
        await connection.execute(
            "DELETE FROM audit_event WHERE action_id = ANY($1::uuid[])", actions
        )
        await connection.execute(
            "DELETE FROM order_form_configuration WHERE action_id = ANY($1::uuid[])",
            actions,
        )
        await connection.execute(
            "DELETE FROM action_template_snapshot WHERE action_id = ANY($1::uuid[])",
            actions,
        )
        await fixture.cleanup()
        await connection.close()
    print(
        "order-form-status-api: OK: managers open and close the form, "
        "idempotent, audited, archived and formless actions refused"
    )


def test_order_form_status_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
