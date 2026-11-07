"""Create or promote a Core System Admin on behalf of the installation operator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.identity import lock_admin_access


class SystemAdminOutcome(Enum):
    CREATED = "created"
    PROMOTED = "promoted"
    ALREADY = "already"


@dataclass(frozen=True, slots=True)
class SystemAdminResult:
    outcome: SystemAdminOutcome
    #: No active System Admin was left, but inactive ones exist: the command
    #: restored access without --additional (recovery, stated in the output).
    recovery: bool = False


class SystemAdminRefused(RuntimeError):
    """Operator-readable refusal; never contains another account's data."""


async def _audit(
    connection: asyncpg.Connection[Any],
    *,
    event_type: str,
    entity_type: str,
    entity_id: UUID,
    request_id: str,
    payload: dict[str, str | bool],
) -> None:
    # No actor: the installation operator acts from the shell, not as a user.
    await connection.execute(
        """
        INSERT INTO audit_event (
            id, action_id, actor_user_id, event_type, entity_type,
            entity_id, request_id, payload, occurred_at
        )
        VALUES ($1, NULL, NULL, $2, $3, $4, $5, $6::jsonb, clock_timestamp())
        """,
        uuid4(),
        event_type,
        entity_type,
        entity_id,
        request_id,
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )


async def ensure_system_admin(
    pool: asyncpg.Pool[Any],
    *,
    email: str,
    display_name: str,
    additional: bool,
    request_id: str,
    operator: str,
) -> SystemAdminResult:
    """One transaction under the admin-access lock (same lock as role changes)."""

    email = email.strip().lower()

    async with pool.acquire() as connection:
        async with connection.transaction():
            occurred_at = await lock_admin_access(connection)
            account = await connection.fetchrow(
                """
                SELECT account.id, account.status,
                       EXISTS (
                           SELECT 1 FROM user_global_role AS role
                           WHERE role.user_id = account.id
                             AND role.role = 'system_admin'
                       ) AS is_system_admin
                FROM user_account AS account
                WHERE lower(account.email) = lower($1)
                """,
                email,
            )
            if (
                account is not None
                and account["status"] == "active"
                and account["is_system_admin"]
            ):
                return SystemAdminResult(SystemAdminOutcome.ALREADY)
            active_admins = int(
                await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM user_global_role AS role
                    JOIN user_account AS account ON account.id = role.user_id
                    WHERE role.role = 'system_admin' AND account.status = 'active'
                    """
                )
            )
            if active_admins and not additional:
                raise SystemAdminRefused(
                    "an active System Admin exists already; pass --additional "
                    "to add another one, or let a System Admin invite members"
                )
            # Only *active* System Admins block: when every one is suspended or
            # archived, this command is the documented way back in.
            inactive_admins = int(
                await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM user_global_role AS role
                    JOIN user_account AS account ON account.id = role.user_id
                    WHERE role.role = 'system_admin' AND account.status <> 'active'
                    """
                )
            )
            recovery = not active_admins and bool(inactive_admins)
            payload: dict[str, str | bool] = {
                "source": "pilot-create-system-admin",
                "additional": bool(active_admins),
                "recovery": recovery,
                "operator": operator,
            }
            if account is None:
                user_id = uuid4()
                await connection.execute(
                    """
                    INSERT INTO user_account (
                        id, email, display_name, status, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, 'active', $4, $4)
                    """,
                    user_id,
                    email,
                    display_name,
                    occurred_at,
                )
                await _audit(
                    connection,
                    event_type="identity.account.created",
                    entity_type="user_account",
                    entity_id=user_id,
                    request_id=request_id,
                    payload=payload,
                )
                outcome = SystemAdminOutcome.CREATED
            elif account["status"] != "active":
                # Suspended or archived accounts are a System Admin's decision
                # in the admin UI; the operator command never reactivates one.
                raise SystemAdminRefused(
                    f"the account of this address is {account['status']}; it is "
                    "not reactivated from the shell"
                )
            else:
                user_id = account["id"]
                outcome = SystemAdminOutcome.PROMOTED
            await connection.execute(
                """
                INSERT INTO user_global_role (user_id, role, granted_at)
                VALUES ($1, 'system_admin', $2)
                """,
                user_id,
                occurred_at,
            )
            await connection.execute(
                "UPDATE user_account SET revision = revision + 1, updated_at = $2 WHERE id = $1",
                user_id,
                occurred_at,
            )
            await _audit(
                connection,
                event_type="identity.global_role.granted",
                entity_type="user_global_role",
                entity_id=user_id,
                request_id=request_id,
                payload={**payload, "role": "system_admin", "enabled": True},
            )
            return SystemAdminResult(outcome, recovery=recovery)
