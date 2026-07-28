"""PostgreSQL identity repository with atomic audit events."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict
from leonaid.application.identity import (
    AccountStatusChange,
    ROLE_LABELS,
    STATUS_LABELS,
    AuthenticatedIdentity,
    MemberDirectoryAction,
    MemberDirectoryMember,
    MemberDirectoryMembership,
    MemberDirectorySnapshot,
    RoleAssignmentChange,
)
from leonaid.domain.actions import CharityActionStatus
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
    removes_last_active_system_admin,
    removes_last_required_charity_admin,
)
from leonaid.domain.sessions import UserSession


def account_from_record(row: asyncpg.Record) -> UserAccount:
    return UserAccount(
        id=row["id"],
        email=str(row["email"]),
        display_name=str(row["display_name"]),
        status=AccountStatus(str(row["status"])),
        email_verified_at=row["email_verified_at"],
        revision=int(row["revision"]),
    )


def replayed_status_change(value: Any) -> AccountStatusChange:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        account_value = value["account"]
        verified_at = account_value.get("emailVerifiedAt")
        return AccountStatusChange(
            account=UserAccount(
                id=UUID(str(account_value["id"])),
                email=str(account_value["email"]),
                display_name=str(account_value["displayName"]),
                status=AccountStatus(str(account_value["status"])),
                email_verified_at=(
                    datetime.fromisoformat(str(verified_at))
                    if verified_at is not None
                    else None
                ),
                revision=int(account_value["revision"]),
            ),
            previous_status=AccountStatus(str(value["previousStatus"])),
            revoked_session_count=int(value["revokedSessionCount"]),
            replayed=True,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "Der Beleg der Kontostatusänderung ist unvollständig."
        ) from error


def status_change_receipt(change: AccountStatusChange) -> dict[str, Any]:
    account = change.account
    return {
        "account": {
            "id": str(account.id),
            "email": account.email,
            "displayName": account.display_name,
            "status": account.status.value,
            "emailVerifiedAt": (
                account.email_verified_at.isoformat()
                if account.email_verified_at is not None
                else None
            ),
            "revision": account.revision,
        },
        "previousStatus": change.previous_status.value,
        "revokedSessionCount": change.revoked_session_count,
    }


def replayed_role_assignment(value: Any) -> RoleAssignmentChange:
    try:
        if isinstance(value, str):
            value = json.loads(value)
        scope = str(value["scope"])
        role: GlobalRole | ActionRole = (
            GlobalRole(str(value["role"]))
            if scope == "global"
            else ActionRole(str(value["role"]))
        )
        return RoleAssignmentChange(
            user_id=UUID(str(value["userId"])),
            revision=int(value["revision"]),
            role=role,
            enabled=bool(value["enabled"]),
            action_id=(
                UUID(str(value["actionId"]))
                if value.get("actionId") is not None
                else None
            ),
            action_name=(
                str(value["actionName"])
                if value.get("actionName") is not None
                else None
            ),
            replayed=True,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Der Beleg der Rollenänderung ist unvollständig.") from error


def role_assignment_receipt(change: RoleAssignmentChange) -> dict[str, Any]:
    return {
        "userId": str(change.user_id),
        "revision": change.revision,
        "scope": "global" if isinstance(change.role, GlobalRole) else "action",
        "role": change.role.value,
        "enabled": change.enabled,
        "actionId": str(change.action_id) if change.action_id is not None else None,
        "actionName": change.action_name,
    }


class AsyncpgIdentityRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def principal_for_session(
        self,
        token_digest: str,
        *,
        now: datetime,
    ) -> AuthenticatedIdentity | None:
        async with self._pool.acquire() as connection:
            account_row = await connection.fetchrow(
                """
                SELECT
                    account.id,
                    account.email,
                    account.display_name,
                    account.status,
                    account.email_verified_at,
                    account.revision,
                    session.id AS session_id,
                    session.created_at AS session_created_at,
                    session.expires_at AS session_expires_at,
                    session.last_seen_at AS session_last_seen_at,
                    session.fresh_login_at AS session_fresh_login_at,
                    session.revoked_at AS session_revoked_at
                FROM user_session AS session
                JOIN user_account AS account ON account.id = session.user_id
                WHERE session.token_digest = $1
                  AND session.revoked_at IS NULL
                  AND session.expires_at > $2
                  AND account.status = 'active'
                """,
                token_digest,
                now,
            )
            if account_row is None:
                return None
            user_id = account_row["id"]
            role_rows = await connection.fetch(
                """
                SELECT role
                FROM user_global_role
                WHERE user_id = $1
                ORDER BY role
                """,
                user_id,
            )
            membership_rows = await connection.fetch(
                """
                SELECT
                    membership.id,
                    membership.action_id,
                    action.name AS action_name,
                    membership.user_id,
                    membership.role,
                    membership.active_from,
                    membership.active_until,
                    membership.delegate_user_id
                FROM action_membership AS membership
                JOIN charity_action AS action ON action.id = membership.action_id
                WHERE membership.user_id = $1
                  AND membership.active_from <= $2
                  AND (
                    membership.active_until IS NULL
                    OR membership.active_until > $2
                  )
                ORDER BY action.starts_on DESC, action.name, membership.role
                """,
                user_id,
                now,
            )
            await connection.execute(
                """
                UPDATE user_session
                SET last_seen_at = $2,
                    updated_at = $2
                WHERE token_digest = $1
                  AND last_seen_at < $2
                """,
                token_digest,
                now,
            )
        account = account_from_record(account_row)
        principal = IdentityPrincipal(
            account=account,
            global_roles=frozenset(GlobalRole(str(row["role"])) for row in role_rows),
            action_memberships=tuple(
                ActionMembership(
                    id=row["id"],
                    action_id=row["action_id"],
                    action_name=str(row["action_name"]),
                    user_id=row["user_id"],
                    role=ActionRole(str(row["role"])),
                    active_from=row["active_from"],
                    active_until=row["active_until"],
                    delegate_user_id=row["delegate_user_id"],
                )
                for row in membership_rows
            ),
        )
        return AuthenticatedIdentity(
            principal=principal,
            session=UserSession(
                id=account_row["session_id"],
                user_id=account.id,
                created_at=account_row["session_created_at"],
                expires_at=account_row["session_expires_at"],
                last_seen_at=max(account_row["session_last_seen_at"], now),
                fresh_login_at=account_row["session_fresh_login_at"],
                revoked_at=account_row["session_revoked_at"],
            ),
        )

    async def member_directory_snapshot(
        self,
        *,
        visible_action_ids: tuple[UUID, ...] | None,
        include_global_roles: bool,
        now: datetime,
    ) -> MemberDirectorySnapshot:
        visible_ids = None if visible_action_ids is None else list(visible_action_ids)
        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read",
                readonly=True,
            ):
                account_rows = await connection.fetch(
                    """
                    SELECT
                        account.id,
                        account.email,
                        account.display_name,
                        account.status,
                        account.email_verified_at,
                        account.revision
                    FROM user_account AS account
                    WHERE $1::uuid[] IS NULL
                       OR EXISTS (
                            SELECT 1
                            FROM action_membership AS membership
                            WHERE membership.user_id = account.id
                              AND membership.action_id = ANY($1::uuid[])
                              AND membership.active_from <= $2
                              AND (
                                membership.active_until IS NULL
                                OR membership.active_until > $2
                              )
                       )
                    ORDER BY lower(account.display_name), account.id
                    """,
                    visible_ids,
                    now,
                )
                user_ids = [row["id"] for row in account_rows]
                role_rows = (
                    await connection.fetch(
                        """
                        SELECT user_id, role
                        FROM user_global_role
                        WHERE user_id = ANY($1::uuid[])
                        ORDER BY user_id, role
                        """,
                        user_ids,
                    )
                    if include_global_roles and user_ids
                    else []
                )
                membership_rows = (
                    await connection.fetch(
                        """
                        SELECT
                            membership.user_id,
                            membership.action_id,
                            action.name AS action_name,
                            membership.role
                        FROM action_membership AS membership
                        JOIN charity_action AS action
                          ON action.id = membership.action_id
                        WHERE membership.user_id = ANY($1::uuid[])
                          AND membership.active_from <= $2
                          AND (
                            membership.active_until IS NULL
                            OR membership.active_until > $2
                          )
                          AND (
                            $3::uuid[] IS NULL
                            OR membership.action_id = ANY($3::uuid[])
                          )
                        ORDER BY
                            membership.user_id,
                            action.starts_on DESC,
                            action.name,
                            membership.role
                        """,
                        user_ids,
                        now,
                        visible_ids,
                    )
                    if user_ids
                    else []
                )
                session_rows = (
                    await connection.fetch(
                        """
                        SELECT
                            user_id,
                            max(created_at) AS last_login_at,
                            count(*) FILTER (
                                WHERE revoked_at IS NULL
                                  AND expires_at > $2
                            ) AS active_session_count
                        FROM user_session
                        WHERE user_id = ANY($1::uuid[])
                        GROUP BY user_id
                        """,
                        user_ids,
                        now,
                    )
                    if user_ids
                    else []
                )
                if visible_ids is None:
                    action_rows = await connection.fetch(
                        """
                        SELECT
                            action.id,
                            action.name,
                            EXISTS (
                                SELECT 1
                                FROM charity_action_capability AS capability
                                WHERE capability.action_id = action.id
                                  AND capability.capability = 'delivery'
                            ) AS has_delivery
                        FROM charity_action AS action
                        ORDER BY action.starts_on DESC, action.name, action.id
                        """
                    )
                else:
                    action_rows = await connection.fetch(
                        """
                        SELECT
                            action.id,
                            action.name,
                            EXISTS (
                                SELECT 1
                                FROM charity_action_capability AS capability
                                WHERE capability.action_id = action.id
                                  AND capability.capability = 'delivery'
                            ) AS has_delivery
                        FROM charity_action AS action
                        WHERE action.id = ANY($1::uuid[])
                        ORDER BY action.starts_on DESC, action.name, action.id
                        """,
                        visible_ids,
                    )

        roles_by_user: dict[UUID, list[GlobalRole]] = {}
        for row in role_rows:
            roles_by_user.setdefault(row["user_id"], []).append(
                GlobalRole(str(row["role"]))
            )
        memberships_by_user: dict[UUID, list[MemberDirectoryMembership]] = {}
        for row in membership_rows:
            role = ActionRole(str(row["role"]))
            memberships_by_user.setdefault(row["user_id"], []).append(
                MemberDirectoryMembership(
                    action_id=row["action_id"],
                    action_name=str(row["action_name"]),
                    role=role,
                    role_label=ROLE_LABELS[role],
                )
            )
        sessions_by_user = {
            row["user_id"]: (
                row["last_login_at"],
                int(row["active_session_count"]),
            )
            for row in session_rows
        }
        members: list[MemberDirectoryMember] = []
        for row in account_rows:
            account = account_from_record(row)
            roles = tuple(roles_by_user.get(account.id, ()))
            last_login_at, active_session_count = sessions_by_user.get(
                account.id,
                (None, 0),
            )
            members.append(
                MemberDirectoryMember(
                    user_id=account.id,
                    display_name=account.display_name,
                    email=account.email,
                    status=account.status,
                    status_label=STATUS_LABELS[account.status],
                    revision=account.revision,
                    global_roles=roles,
                    global_role_labels=tuple(ROLE_LABELS[role] for role in roles),
                    action_memberships=tuple(memberships_by_user.get(account.id, ())),
                    last_login_at=last_login_at,
                    active_session_count=active_session_count,
                )
            )
        return MemberDirectorySnapshot(
            members=tuple(members),
            actions=tuple(
                MemberDirectoryAction(
                    action_id=row["id"],
                    action_name=str(row["name"]),
                    available_roles=(
                        ActionRole.CHARITY_ADMIN,
                        ActionRole.ACQUIRER,
                        ActionRole.FINANCE_READER,
                        *((ActionRole.DRIVER,) if bool(row["has_delivery"]) else ()),
                    ),
                )
                for row in action_rows
            ),
        )

    async def transition_account_status(
        self,
        user_id: UUID,
        target: AccountStatus,
        *,
        actor_user_id: UUID,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> AccountStatusChange | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    "identity.account.status",
                )
                inserted = await connection.fetchval(
                    """
                    INSERT INTO command_receipt (
                        idempotency_key, command_type, request_hash
                    )
                    VALUES ($1, 'identity.account.status.change', $2)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING true
                    """,
                    idempotency_key,
                    request_hash,
                )
                if not inserted:
                    receipt = await connection.fetchrow(
                        """
                        SELECT command_type, request_hash, result
                        FROM command_receipt
                        WHERE idempotency_key = $1
                        FOR UPDATE
                        """,
                        idempotency_key,
                    )
                    if receipt is None:
                        raise RuntimeError(
                            "Der Beleg der Kontostatusänderung ist verschwunden."
                        )
                    if (
                        str(receipt["command_type"]) != "identity.account.status.change"
                        or str(receipt["request_hash"]) != request_hash
                    ):
                        raise Conflict(
                            "idempotency_conflict",
                            "Diese Vorgangs-ID wurde bereits für eine andere "
                            "Statusänderung verwendet.",
                        )
                    if receipt["result"] is None:
                        raise Conflict(
                            "idempotency_incomplete",
                            "Die vorherige Statusänderung ist noch nicht "
                            "abgeschlossen. Bitte versuche es erneut.",
                        )
                    return replayed_status_change(receipt["result"])
                row = await connection.fetchrow(
                    """
                    SELECT
                        id, email, display_name, status, email_verified_at,
                        revision
                    FROM user_account
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    user_id,
                )
                if row is None:
                    await connection.execute(
                        """
                        DELETE FROM command_receipt
                        WHERE idempotency_key = $1
                          AND command_type = 'identity.account.status.change'
                          AND result IS NULL
                        """,
                        idempotency_key,
                    )
                    return None
                current = account_from_record(row)
                if current.revision != expected_revision:
                    raise Conflict(
                        "account_revision_conflict",
                        "Der Zugang wurde zwischenzeitlich geändert. "
                        "Bitte lade den aktuellen Stand.",
                    )
                if current.status is AccountStatus.INVITED:
                    raise Conflict(
                        "account_invitation_activation_forbidden",
                        "Ein eingeladener Zugang wird ausschließlich durch "
                        "Annahme der Einladung aktiviert.",
                    )
                changed = current.transition_to(target)
                if changed.status is current.status:
                    raise Conflict(
                        "account_status_unchanged",
                        "Der Zugang besitzt diesen Status bereits.",
                    )
                if (
                    target is AccountStatus.ARCHIVED
                    and current.status is AccountStatus.ACTIVE
                    and await connection.fetchval(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM user_global_role
                            WHERE user_id = $1
                              AND role = 'system_admin'
                        )
                        """,
                        user_id,
                    )
                ):
                    active_system_admins = int(
                        await connection.fetchval(
                            """
                            SELECT count(*)
                            FROM user_global_role AS role
                            JOIN user_account AS account
                              ON account.id = role.user_id
                            WHERE role.role = 'system_admin'
                              AND account.status = 'active'
                            """
                        )
                    )
                    if active_system_admins <= 1:
                        raise Conflict(
                            "last_system_admin_archival_forbidden",
                            "Der letzte aktive System-Admin kann nicht "
                            "archiviert werden.",
                        )
                revision = await connection.fetchval(
                    """
                    UPDATE user_account
                    SET status = $2,
                        revision = revision + 1,
                        updated_at = $3
                    WHERE id = $1
                      AND revision = $4
                    RETURNING revision
                    """,
                    user_id,
                    target.value,
                    occurred_at,
                    expected_revision,
                )
                if revision is None:
                    raise Conflict(
                        "account_revision_conflict",
                        "Der Zugang wurde zwischenzeitlich geändert. "
                        "Bitte lade den aktuellen Stand.",
                    )
                if int(revision) != changed.revision:
                    raise RuntimeError(
                        "PostgreSQL lieferte eine unerwartete Kontorevision."
                    )
                revoked_session_count = 0
                if target in {AccountStatus.SUSPENDED, AccountStatus.ARCHIVED}:
                    revoked_session_count = int(
                        await connection.fetchval(
                            """
                            WITH revoked AS (
                                UPDATE user_session
                                SET revoked_at = COALESCE(revoked_at, $2),
                                    updated_at = $2
                                WHERE user_id = $1
                                  AND revoked_at IS NULL
                                RETURNING 1
                            )
                            SELECT count(*) FROM revoked
                            """,
                            user_id,
                            occurred_at,
                        )
                    )
                result = AccountStatusChange(
                    account=changed,
                    previous_status=current.status,
                    revoked_session_count=revoked_session_count,
                )
                await self._audit(
                    connection,
                    action_id=None,
                    actor_user_id=actor_user_id,
                    event_type="identity.account.status_changed",
                    entity_type="user_account",
                    entity_id=user_id,
                    request_id=request_id,
                    payload={
                        "previousStatus": current.status.value,
                        "newStatus": target.value,
                        "previousRevision": current.revision,
                        "revision": changed.revision,
                        "revokedSessionCount": revoked_session_count,
                        "idempotencyKey": idempotency_key,
                    },
                    occurred_at=occurred_at,
                )
                receipt_status = await connection.execute(
                    """
                    UPDATE command_receipt
                    SET result = $2::jsonb,
                        completed_at = $3
                    WHERE idempotency_key = $1
                      AND command_type = 'identity.account.status.change'
                      AND result IS NULL
                    """,
                    idempotency_key,
                    json.dumps(
                        status_change_receipt(result),
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
                if receipt_status != "UPDATE 1":
                    raise RuntimeError(
                        "Der Beleg der Kontostatusänderung konnte nicht "
                        "abgeschlossen werden."
                    )
                return result

    async def grant_global_role(
        self,
        user_id: UUID,
        role: GlobalRole,
        *,
        enabled: bool,
        actor_user_id: UUID,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> RoleAssignmentChange | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    "identity.role.assignment",
                )
                replayed = await self._begin_role_command(
                    connection,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return replayed
                account = await connection.fetchrow(
                    """
                    SELECT revision
                    FROM user_account
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    user_id,
                )
                if account is None:
                    await self._discard_role_command(connection, idempotency_key)
                    return None
                if int(account["revision"]) != expected_revision:
                    raise Conflict(
                        "account_revision_conflict",
                        "Die Rollen wurden zwischenzeitlich geändert. "
                        "Bitte lade den aktuellen Stand.",
                    )
                currently_enabled = bool(
                    await connection.fetchval(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM user_global_role
                            WHERE user_id = $1 AND role = $2
                        )
                        """,
                        user_id,
                        role.value,
                    )
                )
                if currently_enabled == enabled:
                    raise Conflict(
                        "role_assignment_unchanged",
                        "Diese Rolle besitzt bereits den gewünschten Stand.",
                    )
                active_system_admin_count = int(
                    await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM user_global_role AS role
                        JOIN user_account AS account
                          ON account.id = role.user_id
                        WHERE role.role = 'system_admin'
                          AND account.status = 'active'
                        """
                    )
                )
                if removes_last_active_system_admin(
                    role=role,
                    enabled=enabled,
                    active_admin_count=active_system_admin_count,
                ):
                    raise Conflict(
                        "last_system_admin_role_forbidden",
                        "Die Rolle des letzten aktiven System-Admins kann "
                        "nicht entfernt werden.",
                    )
                if enabled:
                    await connection.execute(
                        """
                        INSERT INTO user_global_role (user_id, role, granted_at)
                        VALUES ($1, $2, $3)
                        """,
                        user_id,
                        role.value,
                        occurred_at,
                    )
                else:
                    await connection.execute(
                        """
                        DELETE FROM user_global_role
                        WHERE user_id = $1 AND role = $2
                        """,
                        user_id,
                        role.value,
                    )
                revision = await self._advance_account_revision(
                    connection,
                    user_id=user_id,
                    expected_revision=expected_revision,
                    occurred_at=occurred_at,
                )
                result = RoleAssignmentChange(
                    user_id=user_id,
                    revision=revision,
                    role=role,
                    enabled=enabled,
                )
                await self._audit(
                    connection,
                    action_id=None,
                    actor_user_id=actor_user_id,
                    event_type=(
                        "identity.global_role.granted"
                        if enabled
                        else "identity.global_role.revoked"
                    ),
                    entity_type="user_global_role",
                    entity_id=user_id,
                    request_id=request_id,
                    payload={
                        "role": role.value,
                        "enabled": enabled,
                        "previousRevision": expected_revision,
                        "revision": revision,
                        "idempotencyKey": idempotency_key,
                    },
                    occurred_at=occurred_at,
                )
                await self._complete_role_command(
                    connection,
                    idempotency_key=idempotency_key,
                    result=result,
                    occurred_at=occurred_at,
                )
                return result

    async def grant_action_membership(
        self,
        user_id: UUID,
        action_id: UUID,
        role: ActionRole,
        *,
        enabled: bool,
        actor: IdentityPrincipal,
        actor_user_id: UUID,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> RoleAssignmentChange | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    "identity.role.assignment",
                )
                replayed = await self._begin_role_command(
                    connection,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return replayed
                account = await connection.fetchrow(
                    """
                    SELECT revision
                    FROM user_account
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    user_id,
                )
                action = await connection.fetchrow(
                    """
                    SELECT id, name, status
                    FROM charity_action
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    action_id,
                )
                if account is None or action is None:
                    await self._discard_role_command(connection, idempotency_key)
                    return None
                if int(account["revision"]) != expected_revision:
                    raise Conflict(
                        "account_revision_conflict",
                        "Die Rollen wurden zwischenzeitlich geändert. "
                        "Bitte lade den aktuellen Stand.",
                    )
                if not actor.is_system_admin:
                    actor_still_manages = bool(
                        await connection.fetchval(
                            """
                            SELECT EXISTS (
                                SELECT 1
                                FROM action_membership
                                WHERE action_id = $1
                                  AND user_id = $2
                                  AND role = 'charity_admin'
                                  AND active_from <= $3
                                  AND (
                                    active_until IS NULL OR active_until > $3
                                  )
                            )
                            """,
                            action_id,
                            actor_user_id,
                            occurred_at,
                        )
                    )
                    if not actor_still_manages:
                        raise Conflict(
                            "role_action_scope_changed",
                            "Deine Verwaltungsrolle wurde zwischenzeitlich "
                            "geändert. Bitte lade den aktuellen Stand.",
                        )
                if role is ActionRole.DRIVER and not bool(
                    await connection.fetchval(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM charity_action_capability
                            WHERE action_id = $1 AND capability = 'delivery'
                        )
                        """,
                        action_id,
                    )
                ):
                    raise Conflict(
                        "driver_role_capability_missing",
                        "Die Rolle Ausfahrer ist nur für Aktionen mit "
                        "Auslieferung verfügbar.",
                    )
                current = await connection.fetchrow(
                    """
                    SELECT id, active_from, active_until
                    FROM action_membership
                    WHERE action_id = $1 AND user_id = $2 AND role = $3
                    FOR UPDATE
                    """,
                    action_id,
                    user_id,
                    role.value,
                )
                currently_enabled = (
                    current is not None
                    and current["active_from"] <= occurred_at
                    and (
                        current["active_until"] is None
                        or current["active_until"] > occurred_at
                    )
                )
                if currently_enabled == enabled:
                    raise Conflict(
                        "role_assignment_unchanged",
                        "Diese Rolle besitzt bereits den gewünschten Stand.",
                    )
                active_charity_admin_count = int(
                    await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM action_membership
                        WHERE action_id = $1
                          AND role = 'charity_admin'
                          AND active_from <= $2
                          AND (
                            active_until IS NULL OR active_until > $2
                          )
                        """,
                        action_id,
                        occurred_at,
                    )
                )
                if removes_last_required_charity_admin(
                    action_status=CharityActionStatus(str(action["status"])),
                    role=role,
                    enabled=enabled,
                    active_admin_count=active_charity_admin_count,
                ):
                    raise Conflict(
                        "last_charity_admin_role_forbidden",
                        "Die letzte Charity-Admin-Rolle einer laufenden "
                        "Aktion kann nicht entfernt werden.",
                    )
                membership_id: UUID
                if enabled and current is None:
                    membership_id = uuid4()
                    await connection.execute(
                        """
                        INSERT INTO action_membership (
                            id, action_id, user_id, role, active_from,
                            active_until, created_at, updated_at
                        )
                        VALUES ($1, $2, $3, $4, $5, NULL, $5, $5)
                        """,
                        membership_id,
                        action_id,
                        user_id,
                        role.value,
                        occurred_at,
                    )
                elif enabled:
                    membership_id = current["id"]
                    await connection.execute(
                        """
                        UPDATE action_membership
                        SET active_from = $2,
                            active_until = NULL,
                            updated_at = $2
                        WHERE id = $1
                        """,
                        membership_id,
                        occurred_at,
                    )
                else:
                    membership_id = current["id"]
                    await connection.execute(
                        """
                        UPDATE action_membership
                        SET active_until = $2,
                            updated_at = $2
                        WHERE id = $1
                        """,
                        membership_id,
                        occurred_at,
                    )
                revision = await self._advance_account_revision(
                    connection,
                    user_id=user_id,
                    expected_revision=expected_revision,
                    occurred_at=occurred_at,
                )
                result = RoleAssignmentChange(
                    user_id=user_id,
                    revision=revision,
                    role=role,
                    enabled=enabled,
                    action_id=action_id,
                    action_name=str(action["name"]),
                )
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type=(
                        "identity.action_membership.granted"
                        if enabled
                        else "identity.action_membership.revoked"
                    ),
                    entity_type="action_membership",
                    entity_id=membership_id,
                    request_id=request_id,
                    payload={
                        "userId": str(user_id),
                        "role": role.value,
                        "enabled": enabled,
                        "previousRevision": expected_revision,
                        "revision": revision,
                        "idempotencyKey": idempotency_key,
                    },
                    occurred_at=occurred_at,
                )
                await self._complete_role_command(
                    connection,
                    idempotency_key=idempotency_key,
                    result=result,
                    occurred_at=occurred_at,
                )
                return result

    @staticmethod
    async def _begin_role_command(
        connection: asyncpg.Connection[Any],
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> RoleAssignmentChange | None:
        inserted = await connection.fetchval(
            """
            INSERT INTO command_receipt (
                idempotency_key, command_type, request_hash
            )
            VALUES ($1, 'identity.role.assignment.change', $2)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING true
            """,
            idempotency_key,
            request_hash,
        )
        if inserted:
            return None
        receipt = await connection.fetchrow(
            """
            SELECT command_type, request_hash, result
            FROM command_receipt
            WHERE idempotency_key = $1
            FOR UPDATE
            """,
            idempotency_key,
        )
        if receipt is None:
            raise RuntimeError("Der Beleg der Rollenänderung ist verschwunden.")
        if (
            str(receipt["command_type"]) != "identity.role.assignment.change"
            or str(receipt["request_hash"]) != request_hash
        ):
            raise Conflict(
                "idempotency_conflict",
                "Diese Vorgangs-ID wurde bereits für eine andere "
                "Rollenänderung verwendet.",
            )
        if receipt["result"] is None:
            raise Conflict(
                "idempotency_incomplete",
                "Die vorherige Rollenänderung ist noch nicht abgeschlossen.",
            )
        return replayed_role_assignment(receipt["result"])

    @staticmethod
    async def _discard_role_command(
        connection: asyncpg.Connection[Any],
        idempotency_key: str,
    ) -> None:
        await connection.execute(
            """
            DELETE FROM command_receipt
            WHERE idempotency_key = $1
              AND command_type = 'identity.role.assignment.change'
              AND result IS NULL
            """,
            idempotency_key,
        )

    @staticmethod
    async def _advance_account_revision(
        connection: asyncpg.Connection[Any],
        *,
        user_id: UUID,
        expected_revision: int,
        occurred_at: datetime,
    ) -> int:
        revision = await connection.fetchval(
            """
            UPDATE user_account
            SET revision = revision + 1,
                updated_at = $3
            WHERE id = $1 AND revision = $2
            RETURNING revision
            """,
            user_id,
            expected_revision,
            occurred_at,
        )
        if revision is None:
            raise Conflict(
                "account_revision_conflict",
                "Die Rollen wurden zwischenzeitlich geändert. "
                "Bitte lade den aktuellen Stand.",
            )
        return int(revision)

    @staticmethod
    async def _complete_role_command(
        connection: asyncpg.Connection[Any],
        *,
        idempotency_key: str,
        result: RoleAssignmentChange,
        occurred_at: datetime,
    ) -> None:
        status = await connection.execute(
            """
            UPDATE command_receipt
            SET result = $2::jsonb,
                completed_at = $3
            WHERE idempotency_key = $1
              AND command_type = 'identity.role.assignment.change'
              AND result IS NULL
            """,
            idempotency_key,
            json.dumps(role_assignment_receipt(result), separators=(",", ":")),
            occurred_at,
        )
        if status != "UPDATE 1":
            raise RuntimeError(
                "Der Beleg der Rollenänderung konnte nicht abgeschlossen werden."
            )

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID | None,
        actor_user_id: UUID,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        request_id: str,
        payload: dict[str, str | int | bool | None],
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id,
                action_id,
                actor_user_id,
                event_type,
                entity_type,
                entity_id,
                request_id,
                payload,
                occurred_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
            """,
            uuid4(),
            action_id,
            actor_user_id,
            event_type,
            entity_type,
            entity_id,
            request_id,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            occurred_at,
        )
