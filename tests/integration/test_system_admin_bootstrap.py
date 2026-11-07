#!/usr/bin/env python3
"""Operator creation of a System Admin against real PostgreSQL.

``leonaid.adapters.postgres.system_admin.ensure_system_admin`` (behind
``./leonaid pilot-create-system-admin``): a new address becomes an active
account with the ``system_admin`` role, an active member is promoted, an
existing System Admin is left unchanged, a second one needs ``additional``,
and an inactive account is never reactivated. Every change is an
``audit_event`` without an actor. The first System Admin of an empty
installation is proved end to end in ``tools/pilot_install/test.sh``. Runs as
a contract script in the schema gate (tools/schema/test.sh) and, with
CORE_DATABASE_URL set, under pytest.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.system_admin import (
    SystemAdminOutcome,
    SystemAdminRefused,
    ensure_system_admin,
)


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2, command_timeout=10
    )
    tag = uuid4().hex[:8]
    request_id = f"pilot-create-system-admin:{tag}"
    emails = [
        f"{name}.{tag}@leonaid.invalid"
        for name in ("first", "member", "gone", "rescue")
    ]
    try:

        async def ensure(email: str, *, additional: bool) -> SystemAdminOutcome:
            result = await ensure_system_admin(
                pool,
                email=email,
                display_name="Proof Admin",
                additional=additional,
                request_id=request_id,
                operator="leonaid@proof-host",
            )
            return result.outcome

        async def audit() -> list[tuple[str, bool]]:
            rows = await pool.fetch(
                "SELECT event_type, actor_user_id IS NULL AS no_actor FROM audit_event "
                "WHERE request_id = $1 ORDER BY occurred_at",
                request_id,
            )
            return [(row["event_type"], row["no_actor"]) for row in rows]

        assert await ensure(emails[0], additional=True) is SystemAdminOutcome.CREATED
        account = await pool.fetchrow(
            "SELECT id, status FROM user_account WHERE email = $1", emails[0]
        )
        assert account is not None and account["status"] == "active"
        assert await pool.fetchval(
            "SELECT count(*) FROM user_global_role WHERE user_id = $1 AND role = 'system_admin'",
            account["id"],
        )
        assert await audit() == [
            ("identity.account.created", True),
            ("identity.global_role.granted", True),
        ]
        # An active System Admin exists now: a further one needs `additional`.
        try:
            await ensure(emails[1], additional=False)
        except SystemAdminRefused:
            pass
        else:
            raise AssertionError("a second System Admin without additional")
        # Idempotent, also with another spelling of the address.
        assert (
            await ensure(emails[0].upper(), additional=False)
            is SystemAdminOutcome.ALREADY
        )
        assert len(await audit()) == 2
        # An active member is promoted, not duplicated.
        member_id = uuid4()
        await pool.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, 'Proof Member', 'active')",
            member_id,
            emails[1],
        )
        assert await ensure(emails[1], additional=True) is SystemAdminOutcome.PROMOTED
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM user_account WHERE lower(email) = $1", emails[1]
            )
            == 1
        )
        assert [event for event, _ in await audit()][2:] == [
            "identity.global_role.granted"
        ]
        # A suspended account is a System Admin's decision in the admin UI.
        gone_id = uuid4()
        await pool.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, 'Proof Gone', 'suspended')",
            gone_id,
            emails[2],
        )
        try:
            await ensure(emails[2], additional=True)
        except SystemAdminRefused as error:
            assert "suspended" in str(error)
        else:
            raise AssertionError("a suspended account was reactivated")
        assert (
            await pool.fetchval(
                "SELECT status FROM user_account WHERE id = $1", gone_id
            )
            == "suspended"
        )
        assert len(await audit()) == 3
        operator = await pool.fetchval(
            "SELECT payload->>'operator' FROM audit_event WHERE request_id = $1 LIMIT 1",
            request_id,
        )
        assert operator == "leonaid@proof-host"
        # Recovery: every System Admin suspended -> a new one without
        # `additional`, stated as recovery. The statuses are restored after.
        active_admins = [
            row["id"]
            for row in await pool.fetch(
                "SELECT account.id FROM user_account AS account JOIN user_global_role AS role "
                "ON role.user_id = account.id WHERE role.role = 'system_admin' "
                "AND account.status = 'active'"
            )
        ]
        await pool.execute(
            "UPDATE user_account SET status = 'suspended' WHERE id = ANY($1::uuid[])",
            active_admins,
        )
        try:
            rescued = await ensure_system_admin(
                pool,
                email=emails[3],
                display_name="Proof Rescue",
                additional=False,
                request_id=request_id,
                operator="leonaid@proof-host",
            )
        finally:
            await pool.execute(
                "UPDATE user_account SET status = 'active' WHERE id = ANY($1::uuid[])",
                active_admins,
            )
        assert rescued.outcome is SystemAdminOutcome.CREATED and rescued.recovery
        assert await pool.fetchval(
            "SELECT bool_and((payload->>'recovery')::boolean) FROM audit_event "
            "WHERE request_id = $1 AND entity_id = (SELECT id FROM user_account WHERE email = $2)",
            request_id,
            emails[3],
        )
    finally:
        await pool.execute("DELETE FROM audit_event WHERE request_id = $1", request_id)
        ids: list[UUID] = [
            row["id"]
            for row in await pool.fetch(
                "SELECT id FROM user_account WHERE email = ANY($1::text[])", emails
            )
        ]
        await pool.execute("DELETE FROM user_account WHERE id = ANY($1::uuid[])", ids)
        await pool.close()
    print(
        "system-admin-bootstrap: OK: create, promote, idempotent repeat, "
        "--additional rule, no reactivation, recovery, audit with operator"
    )


def test_system_admin_bootstrap() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("CORE_DATABASE_URL is not set")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
