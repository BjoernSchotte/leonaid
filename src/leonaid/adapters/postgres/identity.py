"""PostgreSQL identity repository with atomic audit events."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.identity import (
    ROLE_LABELS,
    STATUS_LABELS,
    AuthenticatedIdentity,
    MemberDirectoryAction,
    MemberDirectoryMember,
    MemberDirectoryMembership,
    MemberDirectorySnapshot,
)
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.sessions import UserSession


def account_from_record(row: asyncpg.Record) -> UserAccount:
    return UserAccount(
        id=row["id"],
        email=str(row["email"]),
        display_name=str(row["display_name"]),
        status=AccountStatus(str(row["status"])),
        email_verified_at=row["email_verified_at"],
    )


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
                        account.email_verified_at
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
                        SELECT id, name
                        FROM charity_action
                        ORDER BY starts_on DESC, name, id
                        """
                    )
                else:
                    action_rows = await connection.fetch(
                        """
                        SELECT id, name
                        FROM charity_action
                        WHERE id = ANY($1::uuid[])
                        ORDER BY starts_on DESC, name, id
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
        request_id: str,
        occurred_at: datetime,
    ) -> UserAccount | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT id, email, display_name, status, email_verified_at
                    FROM user_account
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    user_id,
                )
                if row is None:
                    return None
                current = account_from_record(row)
                changed = current.transition_to(target)
                if changed.status is current.status:
                    return current
                await connection.execute(
                    """
                    UPDATE user_account
                    SET status = $2,
                        updated_at = $3
                    WHERE id = $1
                    """,
                    user_id,
                    target.value,
                    occurred_at,
                )
                if target in {AccountStatus.SUSPENDED, AccountStatus.ARCHIVED}:
                    await connection.execute(
                        """
                        UPDATE user_session
                        SET revoked_at = COALESCE(revoked_at, $2),
                            updated_at = $2
                        WHERE user_id = $1
                          AND revoked_at IS NULL
                        """,
                        user_id,
                        occurred_at,
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
                    },
                    occurred_at=occurred_at,
                )
                return changed

    async def grant_global_role(
        self,
        user_id: UUID,
        role: GlobalRole,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                inserted = await connection.fetchval(
                    """
                    INSERT INTO user_global_role (user_id, role, granted_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, role) DO NOTHING
                    RETURNING true
                    """,
                    user_id,
                    role.value,
                    occurred_at,
                )
                if inserted is not True:
                    return False
                await self._audit(
                    connection,
                    action_id=None,
                    actor_user_id=actor_user_id,
                    event_type="identity.global_role.granted",
                    entity_type="user_global_role",
                    entity_id=user_id,
                    request_id=request_id,
                    payload={"role": role.value},
                    occurred_at=occurred_at,
                )
                return True

    async def revoke_global_role(
        self,
        user_id: UUID,
        role: GlobalRole,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                removed = await connection.fetchval(
                    """
                    DELETE FROM user_global_role
                    WHERE user_id = $1 AND role = $2
                    RETURNING true
                    """,
                    user_id,
                    role.value,
                )
                if removed is not True:
                    return False
                await self._audit(
                    connection,
                    action_id=None,
                    actor_user_id=actor_user_id,
                    event_type="identity.global_role.revoked",
                    entity_type="user_global_role",
                    entity_id=user_id,
                    request_id=request_id,
                    payload={"role": role.value},
                    occurred_at=occurred_at,
                )
                return True

    async def grant_action_membership(
        self,
        membership: ActionMembership,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                inserted = await connection.fetchval(
                    """
                    INSERT INTO action_membership (
                        id,
                        action_id,
                        user_id,
                        role,
                        active_from,
                        active_until,
                        delegate_user_id,
                        created_at,
                        updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                    ON CONFLICT (action_id, user_id, role) DO NOTHING
                    RETURNING true
                    """,
                    membership.id,
                    membership.action_id,
                    membership.user_id,
                    membership.role.value,
                    membership.active_from,
                    membership.active_until,
                    membership.delegate_user_id,
                    occurred_at,
                )
                if inserted is not True:
                    return False
                await self._audit(
                    connection,
                    action_id=membership.action_id,
                    actor_user_id=actor_user_id,
                    event_type="identity.action_membership.granted",
                    entity_type="action_membership",
                    entity_id=membership.id,
                    request_id=request_id,
                    payload={
                        "userId": str(membership.user_id),
                        "role": membership.role.value,
                    },
                    occurred_at=occurred_at,
                )
                return True

    async def revoke_action_membership(
        self,
        membership_id: UUID,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                removed = await connection.fetchrow(
                    """
                    DELETE FROM action_membership
                    WHERE id = $1
                    RETURNING action_id, user_id, role
                    """,
                    membership_id,
                )
                if removed is None:
                    return False
                await self._audit(
                    connection,
                    action_id=removed["action_id"],
                    actor_user_id=actor_user_id,
                    event_type="identity.action_membership.revoked",
                    entity_type="action_membership",
                    entity_id=membership_id,
                    request_id=request_id,
                    payload={
                        "userId": str(removed["user_id"]),
                        "role": str(removed["role"]),
                    },
                    occurred_at=occurred_at,
                )
                return True

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
        payload: dict[str, str],
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
