#!/usr/bin/env python3
"""Prove the admin-access invariants against real PostgreSQL and FastAPI.

The installation keeps at least one active system admin, and every open
action (draft, scheduled, active) keeps at least one active lead
(charity admin). Every path that can take that away is refused with a stable
409 code: role revocation, suspension and archival. Only active accounts
count. All these commands share one lock, so two changes that each look safe
alone cannot together remove the last admin.

The contract creates its own accounts and actions, runs after the other
identity proofs and removes its data again.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.adapters.postgres.identity import (
    AsyncpgIdentityRepository,
    lock_admin_access,
)
from leonaid.adapters.postgres.pool import create_pool
from leonaid.application.errors import Conflict
from leonaid.domain.actions import CharityAction
from leonaid.domain.identity import (
    AccountStatus,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)

from tools.identity.contract import (
    FOREIGN_ACTION_ID,
    SYSTEM_ID,
    ContractFailure,
    create_session,
    require_env,
)

PREFIX = "lastadmin"
LEAD_ONE = UUID("19000000-0000-4000-8000-000000000001")
LEAD_TWO = UUID("19000000-0000-4000-8000-000000000002")
ADMIN_ONE = UUID("19000000-0000-4000-8000-000000000011")
ADMIN_TWO = UUID("19000000-0000-4000-8000-000000000012")
SOLO_ACTION = UUID("29000000-0000-4000-8000-000000000001")
SHARED_ACTION = UUID("29000000-0000-4000-8000-000000000002")
CREATED_ACTION = UUID("29000000-0000-4000-8000-000000000003")
REFUSED_ACTION = UUID("29000000-0000-4000-8000-000000000004")
STAMPED_ACTION = UUID("29000000-0000-4000-8000-000000000005")
USERS = (LEAD_ONE, LEAD_TWO, ADMIN_ONE, ADMIN_TWO)
ACTIONS = (SOLO_ACTION, SHARED_ACTION, CREATED_ACTION, REFUSED_ACTION, STAMPED_ACTION)
RACE_ROUNDS = 12


def command(name: str) -> dict[str, str]:
    key = f"{PREFIX}:{name}:{uuid4()}"
    return {
        "idempotency_key": key,
        "request_hash": hashlib.sha256(key.encode()).hexdigest(),
        "request_id": key,
    }


async def cleanup(connection: asyncpg.Connection[Any]) -> None:
    # The golden system admin is active; a killed earlier run may have left
    # it suspended (see prove_repository).
    await connection.execute(
        "UPDATE user_account SET status = 'active' WHERE id = $1"
        " AND status = 'suspended'",
        SYSTEM_ID,
    )
    await connection.execute(
        "DELETE FROM command_receipt WHERE idempotency_key LIKE $1", f"{PREFIX}:%"
    )
    await connection.execute(
        "DELETE FROM audit_event WHERE request_id LIKE $1", f"{PREFIX}:%"
    )
    await connection.execute(
        "DELETE FROM audit_event WHERE actor_user_id = ANY($1::uuid[])", list(USERS)
    )
    await connection.execute(
        "DELETE FROM action_membership WHERE action_id = ANY($1::uuid[])"
        " OR user_id = ANY($2::uuid[])",
        list(ACTIONS),
        list(USERS),
    )
    await connection.execute(
        "DELETE FROM user_global_role WHERE user_id = ANY($1::uuid[])", list(USERS)
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])", list(USERS)
    )
    await connection.execute(
        "DELETE FROM user_account WHERE id = ANY($1::uuid[])", list(USERS)
    )
    for table in (
        "beneficiary",
        "charity_action_capability",
        "action_delivery_configuration",
    ):
        await connection.execute(
            f"DELETE FROM {table} WHERE action_id = ANY($1::uuid[])", list(ACTIONS)
        )
    await connection.execute(
        "DELETE FROM charity_action WHERE id = ANY($1::uuid[])", list(ACTIONS)
    )


async def seed(connection: asyncpg.Connection[Any], now: datetime) -> None:
    for index, user_id in enumerate(USERS):
        await connection.execute(
            """
            INSERT INTO user_account (id, email, display_name, status)
            VALUES ($1, $2, $3, 'active')
            """,
            user_id,
            f"{PREFIX}-{index}@leonaid.invalid",
            f"Letzte Leitung {index}",
        )
    for user_id in (ADMIN_ONE, ADMIN_TWO):
        await connection.execute(
            """
            INSERT INTO user_global_role (user_id, role, granted_at)
            VALUES ($1, 'system_admin', $2)
            """,
            user_id,
            now,
        )
    for action_id, slug in (
        (SOLO_ACTION, f"{PREFIX}-solo"),
        (SHARED_ACTION, f"{PREFIX}-shared"),
    ):
        await connection.execute(
            """
            INSERT INTO charity_action (
                id, carrier_name, name, purpose, status, starts_on, ends_on,
                publication_starts_at, publication_ends_at, archive_slug,
                goal_value, actual_value, goal_unit, currency
            )
            SELECT $1, carrier_name, $2, purpose, 'draft', starts_on, ends_on,
                   NULL, NULL, $2, goal_value, actual_value, goal_unit, currency
            FROM charity_action
            WHERE id = $3
            """,
            action_id,
            slug,
            FOREIGN_ACTION_ID,
        )
        await connection.execute(
            """
            INSERT INTO beneficiary (
                id, action_id, organization_name, public_description, sort_order
            )
            SELECT gen_random_uuid(), $1, organization_name, public_description,
                   sort_order
            FROM beneficiary
            WHERE action_id = $2
            """,
            action_id,
            FOREIGN_ACTION_ID,
        )
    # Solo: only LEAD_ONE. Shared: LEAD_ONE and LEAD_TWO.
    for action_id, user_id in (
        (SOLO_ACTION, LEAD_ONE),
        (SHARED_ACTION, LEAD_ONE),
        (SHARED_ACTION, LEAD_TWO),
    ):
        await grant_lead(connection, action_id, user_id, now)


async def grant_lead(
    connection: asyncpg.Connection[Any],
    action_id: UUID,
    user_id: UUID,
    now: datetime,
) -> None:
    await connection.execute(
        """
        INSERT INTO action_membership (
            id, action_id, user_id, role, active_from, active_until,
            created_at, updated_at
        )
        VALUES ($1, $2, $3, 'charity_admin', $4, NULL, $4, $4)
        ON CONFLICT (action_id, user_id, role)
        DO UPDATE SET active_from = EXCLUDED.active_from, active_until = NULL
        """,
        uuid4(),
        action_id,
        user_id,
        now,
    )


async def expect_conflict(awaitable: Awaitable[object], code: str, what: str) -> None:
    try:
        await awaitable
    except Conflict as error:
        if error.code != code:
            raise ContractFailure(
                f"{what}: expected {code}, got {error.code}"
            ) from error
    else:
        raise ContractFailure(f"{what}: the change was not refused")


class Api:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.cookies = {"__Host-leonaid_session": token}

    async def revision(self, user_id: UUID) -> int:
        response = await self.client.get(
            f"/api/v1/admin/members/{user_id}", cookies=self.cookies
        )
        if response.status_code != 200:
            raise ContractFailure(f"member {user_id} could not be loaded")
        return int(response.json()["revision"])

    async def patch(self, path: str, body: dict[str, Any], name: str) -> httpx.Response:
        key = f"{PREFIX}:http:{name}:{uuid4()}"
        return await self.client.patch(
            path,
            cookies=self.cookies,
            headers={"Idempotency-Key": key, "X-Request-ID": key},
            json=body,
        )

    async def status(self, user_id: UUID, status: str) -> httpx.Response:
        return await self.patch(
            f"/api/v1/admin/members/{user_id}/status",
            {"status": status, "expectedRevision": await self.revision(user_id)},
            f"status-{status}",
        )

    async def lead(
        self, user_id: UUID, action_id: UUID, enabled: bool
    ) -> httpx.Response:
        return await self.patch(
            f"/api/v1/admin/members/{user_id}/actions/{action_id}/roles/charity_admin",
            {"enabled": enabled, "expectedRevision": await self.revision(user_id)},
            f"lead-{enabled}",
        )


def require(response: httpx.Response, status: int, code: str | None, what: str) -> None:
    actual_code = (
        response.json().get("error", {}).get("code")
        if response.status_code >= 400
        else None
    )
    if response.status_code != status or actual_code != code:
        raise ContractFailure(
            f"{what}: expected HTTP {status} {code}, got HTTP "
            f"{response.status_code} {actual_code}: {response.text[:300]}"
        )


async def prove_http(api: Api) -> None:
    # The only lead of an open action cannot be suspended or archived.
    require(
        await api.status(LEAD_ONE, "suspended"),
        409,
        "last_charity_admin_suspension_forbidden",
        "suspending the last lead",
    )
    require(
        await api.status(LEAD_ONE, "archived"),
        409,
        "last_charity_admin_archival_forbidden",
        "archiving the last lead",
    )
    # A second lead on the solo action who is suspended does not count.
    require(await api.lead(LEAD_TWO, SOLO_ACTION, True), 200, None, "second lead")
    require(await api.status(LEAD_TWO, "suspended"), 200, None, "suspend second lead")
    require(
        await api.lead(LEAD_ONE, SOLO_ACTION, False),
        409,
        "last_charity_admin_role_forbidden",
        "revoking the last active lead next to a suspended one",
    )
    # Once the second lead is active again, the first may go.
    require(await api.status(LEAD_TWO, "active"), 200, None, "reactivate second lead")
    require(await api.lead(LEAD_ONE, SOLO_ACTION, False), 200, None, "hand over")
    require(
        await api.status(LEAD_ONE, "suspended"),
        200,
        None,
        "suspend a lead whose actions keep another active lead",
    )
    require(await api.status(LEAD_ONE, "active"), 200, None, "reactivate first lead")


async def revision(connection: asyncpg.Connection[Any], user_id: UUID) -> int:
    return int(
        await connection.fetchval(
            "SELECT revision FROM user_account WHERE id = $1", user_id
        )
    )


async def active_system_admins(connection: asyncpg.Connection[Any]) -> int:
    return int(
        await connection.fetchval(
            """
            SELECT count(*) FROM user_global_role AS role
            JOIN user_account AS account ON account.id = role.user_id
            WHERE role.role = 'system_admin' AND account.status = 'active'
            """
        )
    )


async def active_leads(connection: asyncpg.Connection[Any], action_id: UUID) -> int:
    return int(
        await connection.fetchval(
            """
            SELECT count(*) FROM action_membership AS membership
            JOIN user_account AS account ON account.id = membership.user_id
            WHERE membership.action_id = $1
              AND membership.role = 'charity_admin'
              AND membership.active_until IS NULL
              AND account.status = 'active'
            """,
            action_id,
        )
    )


async def reset_admins(connection: asyncpg.Connection[Any]) -> None:
    """ADMIN_ONE and ADMIN_TWO are the only active system admins."""

    await connection.execute(
        "UPDATE user_account SET status = 'active' WHERE id = ANY($1::uuid[])",
        [ADMIN_ONE, ADMIN_TWO],
    )
    for user_id in (ADMIN_ONE, ADMIN_TWO):
        await connection.execute(
            """
            INSERT INTO user_global_role (user_id, role, granted_at)
            VALUES ($1, 'system_admin', now())
            ON CONFLICT DO NOTHING
            """,
            user_id,
        )


async def two_leads_on_shared(
    connection: asyncpg.Connection[Any],
) -> tuple[int, int]:
    """LEAD_ONE and LEAD_TWO are the only leads, of SHARED_ACTION only.
    Returns their account revisions."""

    await reset_admins(connection)
    await connection.execute(
        "UPDATE user_account SET status = 'active' WHERE id = ANY($1::uuid[])",
        [LEAD_ONE, LEAD_TWO],
    )
    # SOLO_ACTION gets no lead role from these two here.
    await connection.execute(
        "UPDATE action_membership SET active_until = GREATEST(now(),"
        " active_from + interval '1 microsecond')"
        " WHERE action_id = $1 AND role = 'charity_admin'",
        SOLO_ACTION,
    )
    await connection.execute(
        "UPDATE action_membership SET active_until = GREATEST(now(),"
        " active_from + interval '1 microsecond')"
        " WHERE action_id <> $1 AND user_id = ANY($2::uuid[])"
        " AND role = 'charity_admin'",
        SHARED_ACTION,
        [LEAD_ONE, LEAD_TWO],
    )
    occurred_at = datetime.now(timezone.utc)
    for user_id in (LEAD_ONE, LEAD_TWO):
        await grant_lead(connection, SHARED_ACTION, user_id, occurred_at)
    return (
        await revision(connection, LEAD_ONE),
        await revision(connection, LEAD_TWO),
    )


async def prove_repository(
    pool: asyncpg.Pool[Any],
    identity: AsyncpgIdentityRepository,
    actions: AsyncpgCharityActionRepository,
) -> None:
    now = datetime.now(timezone.utc)
    async with pool.acquire() as connection:
        # Leave ADMIN_ONE as the only active system admin.
        await connection.execute(
            "UPDATE user_account SET status = 'suspended' WHERE id = ANY($1::uuid[])",
            [SYSTEM_ID, ADMIN_TWO],
        )
        others = int(
            await connection.fetchval(
                """
                SELECT count(*) FROM user_global_role AS role
                JOIN user_account AS account ON account.id = role.user_id
                WHERE role.role = 'system_admin' AND account.status = 'active'
                  AND role.user_id <> $1
                """,
                ADMIN_ONE,
            )
        )
        if others:
            raise ContractFailure("unexpected extra active system admins in the stack")
        admin_revision = await revision(connection, ADMIN_ONE)

    for target, code in (
        (AccountStatus.SUSPENDED, "last_system_admin_suspension_forbidden"),
        (AccountStatus.ARCHIVED, "last_system_admin_archival_forbidden"),
    ):
        await expect_conflict(
            identity.transition_account_status(
                ADMIN_ONE,
                target,
                actor_user_id=ADMIN_ONE,
                expected_revision=admin_revision,
                occurred_at=now,
                **command(f"last-system-{target.value}"),
            ),
            code,
            f"{target.value} of the last active system admin",
        )
    await expect_conflict(
        identity.grant_global_role(
            ADMIN_ONE,
            GlobalRole.SYSTEM_ADMIN,
            enabled=False,
            actor_user_id=ADMIN_ONE,
            expected_revision=admin_revision,
            occurred_at=now,
            **command("last-system-role"),
        ),
        "last_system_admin_role_forbidden",
        "revoking the last active system admin role",
    )

    # The actor's authority is re-read under the lock: ADMIN_TWO, suspended
    # meanwhile, cannot finish a queued command.
    async with pool.acquire() as connection:
        lead_one_revision = await revision(connection, LEAD_ONE)
    await expect_conflict(
        identity.transition_account_status(
            LEAD_ONE,
            AccountStatus.SUSPENDED,
            actor_user_id=ADMIN_TWO,
            expected_revision=lead_one_revision,
            occurred_at=now,
            **command("stale-actor-status"),
        ),
        "admin_scope_changed",
        "status change by a suspended system admin",
    )
    await expect_conflict(
        identity.grant_global_role(
            LEAD_ONE,
            GlobalRole.FINANCE_READER,
            enabled=True,
            actor_user_id=ADMIN_TWO,
            expected_revision=lead_one_revision,
            occurred_at=now,
            **command("stale-actor-global"),
        ),
        "admin_scope_changed",
        "global role change by a suspended system admin",
    )
    await expect_conflict(
        identity.grant_action_membership(
            LEAD_ONE,
            SHARED_ACTION,
            ActionRole.ACQUIRER,
            enabled=True,
            actor=system_principal(ADMIN_TWO),
            actor_user_id=ADMIN_TWO,
            expected_revision=lead_one_revision,
            occurred_at=now,
            **command("stale-actor-membership"),
        ),
        "role_action_scope_changed",
        "action role change by a suspended system admin",
    )

    # Action creation: the creator becomes the only lead, so it must be
    # active (LEAD_TWO is suspended for this step).
    template = await actions.get(SOLO_ACTION)
    if template is None:
        raise ContractFailure("solo action disappeared")
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE user_account SET status = 'suspended' WHERE id = $1", LEAD_TWO
        )
    await expect_conflict(
        actions.create(
            copy_action(template, REFUSED_ACTION),
            responsible_admin_user_id=LEAD_TWO,
            request_id=f"{PREFIX}:create-refused",
            occurred_at=now,
        ),
        "action_responsible_administrator_unavailable",
        "creating an action whose only lead is suspended",
    )
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE user_account SET status = 'active' WHERE id = $1", LEAD_TWO
        )

    # Deterministic lock proof for every guarded path: while the lock is
    # held, the command waits; after the holder rolls back, it finishes.
    async with pool.acquire() as connection:
        await reset_admins(connection)
        two = await revision(connection, ADMIN_TWO)
        lead_one_revision = await revision(connection, LEAD_ONE)
    await expect_waits(
        pool,
        lambda: identity.transition_account_status(
            ADMIN_TWO,
            AccountStatus.SUSPENDED,
            actor_user_id=ADMIN_ONE,
            expected_revision=two,
            occurred_at=datetime.now(timezone.utc),
            **command("lock-wait-status"),
        ),
        "account status change",
    )
    await expect_waits(
        pool,
        lambda: identity.grant_global_role(
            LEAD_ONE,
            GlobalRole.FINANCE_READER,
            enabled=True,
            actor_user_id=ADMIN_ONE,
            expected_revision=lead_one_revision,
            occurred_at=datetime.now(timezone.utc),
            **command("lock-wait-global"),
        ),
        "global role change",
    )
    await expect_waits(
        pool,
        lambda: actions.create(
            copy_action(template, CREATED_ACTION),
            responsible_admin_user_id=ADMIN_ONE,
            request_id=f"{PREFIX}:create",
            occurred_at=datetime.now(timezone.utc),
        ),
        "action creation",
    )

    # One lock: while it is held, status and role commands wait.
    async with pool.acquire() as holder:
        transaction = holder.transaction()
        await transaction.start()
        await lock_admin_access(holder)
        async with pool.acquire() as connection:
            await reset_admins(connection)
            lead_revision = await revision(connection, LEAD_TWO)
        waiting = asyncio.ensure_future(
            identity.grant_action_membership(
                LEAD_TWO,
                SOLO_ACTION,
                ActionRole.ACQUIRER,
                enabled=True,
                actor=system_principal(ADMIN_ONE),
                actor_user_id=ADMIN_ONE,
                expected_revision=lead_revision,
                occurred_at=datetime.now(timezone.utc),
                **command("lock-wait"),
            )
        )
        await queued_behind(pool, holder, waiting, "a role change")
        await transaction.rollback()
    await asyncio.wait_for(waiting, timeout=10)

    # Race: two system admins act on each other at the same moment. Exactly
    # one wins; there is always an active system admin left.
    for round_number in range(RACE_ROUNDS):
        async with pool.acquire() as connection:
            await reset_admins(connection)
            one = await revision(connection, ADMIN_ONE)
            two = await revision(connection, ADMIN_TWO)
        occurred_at = datetime.now(timezone.utc)
        results = await asyncio.gather(
            identity.transition_account_status(
                ADMIN_TWO,
                AccountStatus.SUSPENDED,
                actor_user_id=ADMIN_ONE,
                expected_revision=two,
                occurred_at=occurred_at,
                **command(f"race-suspend-{round_number}"),
            ),
            identity.grant_global_role(
                ADMIN_ONE,
                GlobalRole.SYSTEM_ADMIN,
                enabled=False,
                actor_user_id=ADMIN_TWO,
                expected_revision=one,
                occurred_at=occurred_at,
                **command(f"race-revoke-{round_number}"),
            ),
            return_exceptions=True,
        )
        refused = [item for item in results if isinstance(item, Conflict)]
        unexpected = [
            item
            for item in results
            if isinstance(item, BaseException) and not isinstance(item, Conflict)
        ]
        if unexpected:
            raise ContractFailure(f"race round {round_number}: {unexpected[0]!r}")
        # The loser is refused either because its actor lost the system-admin
        # authority to the winner (re-read under the lock), or by the
        # invariant itself.
        if len(refused) != 1 or refused[0].code not in {
            "admin_scope_changed",
            "last_system_admin_suspension_forbidden",
            "last_system_admin_role_forbidden",
        }:
            raise ContractFailure(
                f"race round {round_number}: expected exactly one refusal, got "
                f"{[getattr(item, 'code', 'ok') for item in results]}"
            )
        async with pool.acquire() as connection:
            if await active_system_admins(connection) != 1:
                raise ContractFailure(
                    f"race round {round_number} left no active system admin"
                )

    # Race on an open action: its two leads leave at the same moment.
    for round_number in range(RACE_ROUNDS):
        async with pool.acquire() as connection:
            one, two = await two_leads_on_shared(connection)
        actor = system_principal(ADMIN_ONE)
        results = await asyncio.gather(
            identity.transition_account_status(
                LEAD_ONE,
                AccountStatus.SUSPENDED,
                actor_user_id=ADMIN_ONE,
                expected_revision=one,
                occurred_at=datetime.now(timezone.utc),
                **command(f"lead-race-suspend-{round_number}"),
            ),
            identity.grant_action_membership(
                LEAD_TWO,
                SHARED_ACTION,
                ActionRole.CHARITY_ADMIN,
                enabled=False,
                actor=actor,
                actor_user_id=ADMIN_ONE,
                expected_revision=two,
                occurred_at=datetime.now(timezone.utc),
                **command(f"lead-race-revoke-{round_number}"),
            ),
            return_exceptions=True,
        )
        refused = [item for item in results if isinstance(item, Conflict)]
        unexpected = [
            item
            for item in results
            if isinstance(item, BaseException) and not isinstance(item, Conflict)
        ]
        if unexpected:
            raise ContractFailure(f"lead race round {round_number}: {unexpected[0]!r}")
        if len(refused) != 1 or refused[0].code not in {
            "last_charity_admin_suspension_forbidden",
            "last_charity_admin_role_forbidden",
        }:
            raise ContractFailure(
                f"lead race round {round_number}: expected exactly one refusal, "
                f"got {[getattr(item, 'code', 'ok') for item in results]}"
            )
        async with pool.acquire() as connection:
            if await active_leads(connection, SHARED_ACTION) != 1:
                raise ContractFailure(
                    f"lead race round {round_number} left the action without a lead"
                )

    await prove_stamp_order(pool, identity, actions, template)

    # The responsible-admin replacement takes the same lock.
    async with pool.acquire() as holder:
        transaction = holder.transaction()
        await transaction.start()
        await lock_admin_access(holder)
        action = await actions.get(SHARED_ACTION)
        if action is None:
            raise ContractFailure("shared action disappeared")
        replacing = asyncio.ensure_future(
            actions.replace_responsible_administrators(
                action,
                responsible_user_ids=frozenset({ADMIN_ONE}),
                actor_user_id=ADMIN_ONE,
                request_id=f"{PREFIX}:responsibles",
                occurred_at=datetime.now(timezone.utc),
            )
        )
        await queued_behind(
            pool, holder, replacing, "the responsible-admin replacement"
        )
        await transaction.rollback()
    await asyncio.wait_for(replacing, timeout=10)


async def end_leads(
    connection: asyncpg.Connection[Any], user_id: UUID, *, except_action: UUID
) -> None:
    await connection.execute(
        "UPDATE action_membership SET active_until = GREATEST(now(),"
        " active_from + interval '1 microsecond')"
        " WHERE user_id = $1 AND action_id <> $2 AND role = 'charity_admin'"
        " AND active_until IS NULL",
        user_id,
        except_action,
    )


async def prove_stamp_order(
    pool: asyncpg.Pool[Any],
    identity: AsyncpgIdentityRepository,
    actions: AsyncpgCharityActionRepository,
    template: CharityAction,
) -> None:
    """A command that queued for the lock first must see what a command that
    got the lock before it committed, whatever times their callers passed.

    Each case passes the earlier time to the command that runs second, the
    order of the lead race of 2026-11-05. The commands take their time once
    they hold the lock (lock_admin_access), so the passed times must not
    matter. All cases run; the failures are reported together.
    """

    failures: list[str] = []
    actor = system_principal(ADMIN_ONE)

    async def refused(name: str, call: Awaitable[object], code: str) -> None:
        try:
            await call
        except Conflict as error:
            if error.code != code:
                failures.append(f"{name}: refused with {error.code}, not {code}")
        except Exception as error:  # noqa: BLE001 - reported as a failure
            failures.append(f"{name}: {error!r}")
        else:
            failures.append(f"{name}: accepted, expected {code}")

    async def leads(name: str, action_id: UUID, expected: int) -> None:
        async with pool.acquire() as connection:
            count = await active_leads(connection, action_id)
        if count != expected:
            failures.append(f"{name}: {count} active leads, expected {expected}")

    # 1. An ended role: a revoke runs first (later time), then a suspension
    #    of the other lead (earlier time) must be refused.
    async with pool.acquire() as connection:
        one, two = await two_leads_on_shared(connection)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=5)
    await identity.grant_action_membership(
        LEAD_TWO,
        SHARED_ACTION,
        ActionRole.CHARITY_ADMIN,
        enabled=False,
        actor=actor,
        actor_user_id=ADMIN_ONE,
        expected_revision=two,
        occurred_at=later,
        **command("stamp-revoke"),
    )
    await refused(
        "ended role",
        identity.transition_account_status(
            LEAD_ONE,
            AccountStatus.SUSPENDED,
            actor_user_id=ADMIN_ONE,
            expected_revision=one,
            occurred_at=earlier,
            **command("stamp-suspend"),
        ),
        "last_charity_admin_suspension_forbidden",
    )
    await leads("ended role", SHARED_ACTION, 1)

    # 2. The suspended user's own new lead role: the responsible-admin
    #    replacement makes LEAD_TWO the only lead (later time, no account
    #    revision bump), then suspending LEAD_TWO (earlier time) must be
    #    refused.
    async with pool.acquire() as connection:
        await two_leads_on_shared(connection)
        await connection.execute(
            "UPDATE action_membership SET active_until = GREATEST(now(),"
            " active_from + interval '1 microsecond')"
            " WHERE action_id = $1 AND user_id = $2 AND role = 'charity_admin'",
            SHARED_ACTION,
            LEAD_TWO,
        )
        two = await revision(connection, LEAD_TWO)
    shared = await actions.get(SHARED_ACTION)
    if shared is None:
        raise ContractFailure("shared action disappeared")
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=5)
    await actions.replace_responsible_administrators(
        shared,
        responsible_user_ids=frozenset({LEAD_TWO}),
        actor_user_id=ADMIN_ONE,
        request_id=f"{PREFIX}:stamp-replace",
        occurred_at=later,
    )
    await refused(
        "replacement lead",
        identity.transition_account_status(
            LEAD_TWO,
            AccountStatus.SUSPENDED,
            actor_user_id=ADMIN_ONE,
            expected_revision=two,
            occurred_at=earlier,
            **command("stamp-replace-suspend"),
        ),
        "last_charity_admin_suspension_forbidden",
    )
    await leads("replacement lead", SHARED_ACTION, 1)

    # 3. Action create: the creator becomes the only lead (later time), then
    #    suspending the creator (earlier time) must be refused.
    async with pool.acquire() as connection:
        await two_leads_on_shared(connection)
        await end_leads(connection, LEAD_TWO, except_action=STAMPED_ACTION)
        two = await revision(connection, LEAD_TWO)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=5)
    await actions.create(
        copy_action(template, STAMPED_ACTION),
        responsible_admin_user_id=LEAD_TWO,
        request_id=f"{PREFIX}:stamp-create",
        occurred_at=later,
    )
    await refused(
        "created action",
        identity.transition_account_status(
            LEAD_TWO,
            AccountStatus.SUSPENDED,
            actor_user_id=ADMIN_ONE,
            expected_revision=two,
            occurred_at=earlier,
            **command("stamp-create-suspend"),
        ),
        "last_charity_admin_suspension_forbidden",
    )
    await leads("created action", STAMPED_ACTION, 1)

    # 4. The actor re-check: LEAD_ONE's lead role is revoked first (later
    #    time), then LEAD_ONE acting as lead (earlier time) must be refused.
    async with pool.acquire() as connection:
        one, two = await two_leads_on_shared(connection)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=5)
    await identity.grant_action_membership(
        LEAD_ONE,
        SHARED_ACTION,
        ActionRole.CHARITY_ADMIN,
        enabled=False,
        actor=actor,
        actor_user_id=ADMIN_ONE,
        expected_revision=one,
        occurred_at=later,
        **command("stamp-actor-revoke"),
    )
    await refused(
        "revoked actor",
        identity.grant_action_membership(
            LEAD_TWO,
            SHARED_ACTION,
            ActionRole.ACQUIRER,
            enabled=True,
            actor=actor,
            actor_user_id=LEAD_ONE,
            expected_revision=two,
            occurred_at=earlier,
            **command("stamp-actor-grant"),
        ),
        "role_action_scope_changed",
    )

    # 5. An end never lies before its start: a lead whose start another
    #    clock wrote slightly ahead is ended by the replacement without a
    #    period violation (no 500).
    async with pool.acquire() as connection:
        await two_leads_on_shared(connection)
        await connection.execute(
            "UPDATE action_membership SET active_from = clock_timestamp()"
            " + interval '1 second'"
            " WHERE action_id = $1 AND user_id = $2 AND role = 'charity_admin'",
            SHARED_ACTION,
            LEAD_ONE,
        )
    shared = await actions.get(SHARED_ACTION)
    if shared is None:
        raise ContractFailure("shared action disappeared")
    try:
        await actions.replace_responsible_administrators(
            shared,
            responsible_user_ids=frozenset({LEAD_TWO}),
            actor_user_id=ADMIN_ONE,
            request_id=f"{PREFIX}:stamp-clamp",
            occurred_at=datetime.now(timezone.utc),
        )
    except Exception as error:  # noqa: BLE001 - reported as a failure
        failures.append(f"end before start: {error!r}")
    else:
        async with pool.acquire() as connection:
            if not await connection.fetchval(
                "SELECT active_until > active_from FROM action_membership"
                " WHERE action_id = $1 AND user_id = $2 AND role = 'charity_admin'",
                SHARED_ACTION,
                LEAD_ONE,
            ):
                failures.append("end before start: the end is not after the start")
    async with pool.acquire() as connection:
        # The stamped action's lead must not count for the later proofs.
        await connection.execute(
            "UPDATE action_membership SET active_until = GREATEST("
            " clock_timestamp(), active_from + interval '1 microsecond')"
            " WHERE action_id = $1 AND active_until IS NULL",
            STAMPED_ACTION,
        )
    if failures:
        raise ContractFailure("stamp order: " + "; ".join(failures))


def copy_action(template: CharityAction, action_id: UUID) -> CharityAction:
    return replace(
        template,
        id=action_id,
        name=f"{PREFIX}-{action_id}",
        archive_slug=f"{PREFIX}-{str(action_id)[-4:]}",
        revision=1,
        beneficiaries=tuple(
            replace(beneficiary, id=uuid4(), action_id=action_id)
            for beneficiary in template.beneficiaries
        ),
    )


async def queued_behind(
    pool: asyncpg.Pool[Any],
    holder: asyncpg.Connection[Any],
    task: asyncio.Future[Any],
    what: str,
) -> None:
    """Wait until a backend is blocked by the holder's lock, or fail.

    A fixed sleep would also pass for a command that is only slow; this
    proves it is queued behind the held lock (pg_blocking_pids).
    """

    holder_pid = await holder.fetchval("SELECT pg_backend_pid()")
    deadline = asyncio.get_running_loop().time() + 10
    async with pool.acquire() as observer:
        while True:
            if task.done():
                raise ContractFailure(f"{what} did not wait for the admin lock")
            if await observer.fetchval(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE $1::integer = ANY(pg_blocking_pids(pid))",
                holder_pid,
            ):
                return
            if asyncio.get_running_loop().time() > deadline:
                raise ContractFailure(f"{what} never queued behind the admin lock")
            await asyncio.sleep(0.02)


async def expect_waits(
    pool: asyncpg.Pool[Any],
    start: Callable[[], Awaitable[object]],
    what: str,
) -> None:
    """Hold the admin lock, start the command, see it wait, then release."""

    async with pool.acquire() as holder:
        transaction = holder.transaction()
        await transaction.start()
        await lock_admin_access(holder)
        task = asyncio.ensure_future(start())
        try:
            await queued_behind(pool, holder, task, what)
        finally:
            await transaction.rollback()
    await asyncio.wait_for(task, timeout=10)


def system_principal(user_id: UUID) -> IdentityPrincipal:
    """The acting system admin; only `is_system_admin` is read."""

    return IdentityPrincipal(
        account=UserAccount(
            id=user_id,
            email=f"{PREFIX}@leonaid.invalid",
            display_name="Letzte Leitung",
            status=AccountStatus.ACTIVE,
            email_verified_at=None,
            revision=1,
        ),
        global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}),
        action_memberships=(),
    )


async def run() -> None:
    database_url = require_env("CORE_DATABASE_URL")
    base_url = require_env("LEONAID_API_BASE_URL").rstrip("/")
    now = datetime.now(timezone.utc)
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        system_status = await connection.fetchval(
            "SELECT status FROM user_account WHERE id = $1", SYSTEM_ID
        )
        await cleanup(connection)
        await seed(connection, now)
        token = await create_session(connection, SYSTEM_ID, now=now)
    finally:
        await connection.close()
    pool = await create_pool(database_url, minimum_size=2, maximum_size=6)
    try:
        identity = AsyncpgIdentityRepository(pool)
        actions = AsyncpgCharityActionRepository(pool)
        async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
            await prove_http(Api(client, token))
        await prove_repository(pool, identity, actions)
    finally:
        async with pool.acquire() as connection:
            await connection.execute(
                "UPDATE user_account SET status = $2 WHERE id = $1",
                SYSTEM_ID,
                system_status,
            )
            await connection.execute(
                "DELETE FROM user_session WHERE token_digest = $1",
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
            )
            await cleanup(connection)
        await pool.close()


def main() -> int:
    try:
        asyncio.run(run())
    except ContractFailure as error:
        print(f"last-admin-contract: FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "last-admin-contract: OK: last system admin and last lead refused on "
        "suspend, archive and revoke; suspended leads do not count; one lock "
        "serializes status, role, membership, responsible and creation "
        "commands; stale actors refused; "
        f"{RACE_ROUNDS}+{RACE_ROUNDS} races keep an admin; commands take their "
        "time under the lock (ended role, replacement lead, created action, "
        "revoked actor, end before start)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
