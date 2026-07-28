"""Atomic PostgreSQL invitation, membership, audit and outbox adapter."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import PermissionDenied
from leonaid.application.invitations import (
    InvitationAcceptance,
    InvitationContext,
    InvitationReissueContext,
    InvitationSummary,
    InviteableAction,
)
from leonaid.domain.identity import ActionRole
from leonaid.domain.invitations import (
    ActionInvitation,
    InvitationAcceptanceMethod,
    InvitationStatus,
    after_failed_code_attempt,
)
from leonaid.domain.outbox import PendingOutboxEvent


class AsyncpgInvitationRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def inviteable_actions(
        self,
        actor_user_id: UUID,
        *,
        now: datetime,
    ) -> tuple[InviteableAction, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT action.id, action.name, action.status
                FROM charity_action AS action
                WHERE action.status IN ('draft', 'scheduled', 'active')
                  AND (
                    EXISTS (
                      SELECT 1
                      FROM user_global_role AS global_role
                      JOIN user_account AS account
                        ON account.id = global_role.user_id
                      WHERE global_role.user_id = $1
                        AND global_role.role = 'system_admin'
                        AND account.status = 'active'
                    )
                    OR EXISTS (
                      SELECT 1
                      FROM action_membership AS membership
                      JOIN user_account AS account
                        ON account.id = membership.user_id
                      WHERE membership.action_id = action.id
                        AND membership.user_id = $1
                        AND membership.role = 'charity_admin'
                        AND membership.active_from <= $2
                        AND (
                          membership.active_until IS NULL
                          OR membership.active_until > $2
                        )
                        AND account.status = 'active'
                    )
                  )
                ORDER BY action.starts_on DESC, action.name
                """,
                actor_user_id,
                now,
            )
        return tuple(
            InviteableAction(
                id=row["id"],
                name=str(row["name"]),
                status=str(row["status"]),
            )
            for row in rows
        )

    async def invitation_context(
        self,
        actor_user_id: UUID,
        action_id: UUID,
        *,
        now: datetime,
    ) -> InvitationContext:
        async with self._pool.acquire() as connection:
            return await self._authorized_context(
                connection,
                actor_user_id,
                action_id,
                now=now,
            )

    async def list_authorized(
        self,
        actor_user_id: UUID,
        *,
        action_id: UUID | None,
        status: InvitationStatus | None,
        now: datetime,
    ) -> tuple[InvitationSummary, ...]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    UPDATE action_invitation
                    SET status = 'expired',
                        expired_at = $2,
                        updated_at = $2
                    WHERE status = 'pending'
                      AND expires_at <= $2
                      AND action_id IN (
                        SELECT action.id
                        FROM charity_action AS action
                        WHERE EXISTS (
                          SELECT 1
                          FROM user_global_role
                          WHERE user_id = $1
                            AND role = 'system_admin'
                        )
                        OR EXISTS (
                          SELECT 1
                          FROM action_membership
                          WHERE action_id = action.id
                            AND user_id = $1
                            AND role = 'charity_admin'
                            AND active_from <= $2
                            AND (
                              active_until IS NULL
                              OR active_until > $2
                            )
                        )
                      )
                    """,
                    actor_user_id,
                    now,
                )
                rows = await connection.fetch(
                    """
                    SELECT
                      invitation.id,
                      invitation.action_id,
                      invitation.action_name_snapshot,
                      invitation.email_snapshot,
                      invitation.display_name_snapshot,
                      invitation.role_snapshot,
                      invitation.status,
                      invitation.invited_by_name_snapshot,
                      invitation.created_at,
                      invitation.expires_at,
                      invitation.accepted_at,
                      invitation.revoked_at,
                      invitation.expired_at,
                      invitation.supersedes_invitation_id
                    FROM action_invitation AS invitation
                    JOIN user_account AS actor
                      ON actor.id = $1
                     AND actor.status = 'active'
                    WHERE (
                      EXISTS (
                        SELECT 1
                        FROM user_global_role
                        WHERE user_id = $1
                          AND role = 'system_admin'
                      )
                      OR EXISTS (
                        SELECT 1
                        FROM action_membership
                        WHERE action_id = invitation.action_id
                          AND user_id = $1
                          AND role = 'charity_admin'
                          AND active_from <= $4
                          AND (
                            active_until IS NULL
                            OR active_until > $4
                          )
                      )
                    )
                      AND ($2::uuid IS NULL OR invitation.action_id = $2)
                      AND ($3::text IS NULL OR invitation.status = $3)
                    ORDER BY invitation.created_at DESC, invitation.id DESC
                    LIMIT 200
                    """,
                    actor_user_id,
                    action_id,
                    status.value if status is not None else None,
                    now,
                )
        return tuple(
            InvitationSummary(
                id=row["id"],
                action_id=row["action_id"],
                action_name=str(row["action_name_snapshot"]),
                email=str(row["email_snapshot"]),
                display_name=str(row["display_name_snapshot"]),
                role=ActionRole(str(row["role_snapshot"])),
                status=InvitationStatus(str(row["status"])),
                invited_by_name=str(row["invited_by_name_snapshot"]),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                accepted_at=row["accepted_at"],
                revoked_at=row["revoked_at"],
                expired_at=row["expired_at"],
                supersedes_invitation_id=row["supersedes_invitation_id"],
            )
            for row in rows
        )

    async def reissue_context(
        self,
        invitation_id: UUID,
        *,
        actor_user_id: UUID,
        now: datetime,
    ) -> InvitationReissueContext | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT
                  invitation.action_id,
                  invitation.action_name_snapshot,
                  invitation.email_snapshot,
                  invitation.display_name_snapshot,
                  invitation.role_snapshot,
                  actor.display_name AS invited_by_name
                FROM action_invitation AS invitation
                JOIN user_account AS actor
                  ON actor.id = $2
                 AND actor.status = 'active'
                WHERE invitation.id = $1
                  AND invitation.status = 'pending'
                  AND invitation.expires_at > $3
                  AND (
                    EXISTS (
                      SELECT 1
                      FROM user_global_role
                      WHERE user_id = $2
                        AND role = 'system_admin'
                    )
                    OR EXISTS (
                      SELECT 1
                      FROM action_membership
                      WHERE action_id = invitation.action_id
                        AND user_id = $2
                        AND role = 'charity_admin'
                        AND active_from <= $3
                        AND (
                          active_until IS NULL
                          OR active_until > $3
                        )
                    )
                  )
                """,
                invitation_id,
                actor_user_id,
                now,
            )
        if row is None:
            return None
        return InvitationReissueContext(
            action_id=row["action_id"],
            action_name=str(row["action_name_snapshot"]),
            email=str(row["email_snapshot"]),
            display_name=str(row["display_name_snapshot"]),
            role=ActionRole(str(row["role_snapshot"])),
            invited_by_name=str(row["invited_by_name"]),
        )

    async def create(
        self,
        invitation: ActionInvitation,
        mail_event: PendingOutboxEvent,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> UUID:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                context = await self._authorized_context(
                    connection,
                    actor_user_id,
                    invitation.action_id,
                    now=occurred_at,
                )
                if (
                    invitation.invited_by_user_id != actor_user_id
                    or invitation.action_name_snapshot != context.action.name
                    or invitation.invited_by_name_snapshot != context.invited_by_name
                ):
                    raise PermissionDenied(
                        "invitation_context_changed",
                        "Die Einladungsberechtigung hat sich geändert.",
                    )
                expired = await connection.fetchrow(
                    """
                    SELECT id
                    FROM action_invitation
                    WHERE action_id = $1
                      AND email_snapshot = $2
                      AND role_snapshot = $3
                      AND status = 'pending'
                      AND expires_at <= $4
                    FOR UPDATE
                    """,
                    invitation.action_id,
                    invitation.email_snapshot,
                    invitation.role_snapshot.value,
                    occurred_at,
                )
                if expired is not None:
                    await connection.execute(
                        """
                        UPDATE action_invitation
                        SET status = 'expired',
                            expired_at = $2,
                            updated_at = $2
                        WHERE id = $1
                        """,
                        expired["id"],
                        occurred_at,
                    )
                    await self._audit(
                        connection,
                        action_id=invitation.action_id,
                        actor_user_id=actor_user_id,
                        event_type="identity.invitation.expired",
                        entity_type="action_invitation",
                        entity_id=expired["id"],
                        request_id=request_id,
                        payload={},
                        occurred_at=occurred_at,
                    )
                inserted_id = await connection.fetchval(
                    """
                    INSERT INTO action_invitation (
                        id,
                        action_id,
                        invited_by_user_id,
                        email_snapshot,
                        display_name_snapshot,
                        action_name_snapshot,
                        invited_by_name_snapshot,
                        role_snapshot,
                        status,
                        token_digest,
                        code_digest,
                        expires_at,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        'pending', $9, $10, $11, $12, $12
                    )
                    ON CONFLICT (
                        action_id,
                        email_snapshot,
                        role_snapshot
                    ) WHERE status = 'pending'
                    DO NOTHING
                    RETURNING id
                    """,
                    invitation.id,
                    invitation.action_id,
                    invitation.invited_by_user_id,
                    invitation.email_snapshot,
                    invitation.display_name_snapshot,
                    invitation.action_name_snapshot,
                    invitation.invited_by_name_snapshot,
                    invitation.role_snapshot.value,
                    invitation.token_digest,
                    invitation.code_digest,
                    invitation.expires_at,
                    occurred_at,
                )
                if inserted_id is None:
                    existing_id = await connection.fetchval(
                        """
                        SELECT id
                        FROM action_invitation
                        WHERE action_id = $1
                          AND email_snapshot = $2
                          AND role_snapshot = $3
                          AND status = 'pending'
                        """,
                        invitation.action_id,
                        invitation.email_snapshot,
                        invitation.role_snapshot.value,
                    )
                    if existing_id is None:
                        raise RuntimeError(
                            "Konkurrierende Einladung konnte nicht aufgelöst werden."
                        )
                    return UUID(str(existing_id))
                await self._audit(
                    connection,
                    action_id=invitation.action_id,
                    actor_user_id=actor_user_id,
                    event_type="identity.invitation.created",
                    entity_type="action_invitation",
                    entity_id=invitation.id,
                    request_id=request_id,
                    payload={
                        "role": invitation.role_snapshot.value,
                        "expiresAt": invitation.expires_at.isoformat(),
                    },
                    occurred_at=occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO outbox_event (
                        id,
                        aggregate_type,
                        aggregate_id,
                        event_type,
                        idempotency_key,
                        payload,
                        available_at,
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $7)
                    """,
                    mail_event.id,
                    mail_event.aggregate_type,
                    mail_event.aggregate_id,
                    mail_event.event_type,
                    mail_event.idempotency_key,
                    json.dumps(mail_event.payload, separators=(",", ":")),
                    occurred_at,
                )
                return invitation.id

    async def accept(
        self,
        *,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        method: InvitationAcceptanceMethod,
        request_id: str,
        occurred_at: datetime,
    ) -> InvitationAcceptance | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                if method is InvitationAcceptanceMethod.MAGIC_LINK:
                    row = await connection.fetchrow(
                        """
                        SELECT *
                        FROM action_invitation
                        WHERE token_digest = $1
                        FOR UPDATE
                        """,
                        token_digest,
                    )
                else:
                    row = await connection.fetchrow(
                        """
                        SELECT *
                        FROM action_invitation
                        WHERE email_snapshot = $1
                          AND code_digest = $2
                        FOR UPDATE
                        """,
                        email,
                        code_digest,
                    )
                if row is None:
                    if method is InvitationAcceptanceMethod.CODE and email is not None:
                        await self._record_invalid_code(
                            connection,
                            email=email,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                    return None
                if row["status"] != "pending":
                    return None
                invitation_id = row["id"]
                action_id = row["action_id"]
                if occurred_at >= row["expires_at"]:
                    await connection.execute(
                        """
                        UPDATE action_invitation
                        SET status = 'expired',
                            expired_at = $2,
                            updated_at = $2
                        WHERE id = $1
                        """,
                        invitation_id,
                        occurred_at,
                    )
                    await self._audit(
                        connection,
                        action_id=action_id,
                        actor_user_id=None,
                        event_type="identity.invitation.expired",
                        entity_type="action_invitation",
                        entity_id=invitation_id,
                        request_id=request_id,
                        payload={},
                        occurred_at=occurred_at,
                    )
                    return None

                account = await connection.fetchrow(
                    """
                    SELECT id, status
                    FROM user_account
                    WHERE email = $1
                    FOR UPDATE
                    """,
                    row["email_snapshot"],
                )
                if account is None:
                    user_id = uuid4()
                    await connection.execute(
                        """
                        INSERT INTO user_account (
                            id,
                            email,
                            display_name,
                            status,
                            email_verified_at,
                            created_at,
                            updated_at
                        )
                        VALUES ($1, $2, $3, 'active', $4, $4, $4)
                        """,
                        user_id,
                        row["email_snapshot"],
                        row["display_name_snapshot"],
                        occurred_at,
                    )
                else:
                    user_id = account["id"]
                    account_status = str(account["status"])
                    if account_status in {"invited", "active"}:
                        await connection.execute(
                            """
                            UPDATE user_account
                            SET status = 'active',
                                email_verified_at = COALESCE(
                                  email_verified_at,
                                  $2
                                ),
                                updated_at = $2
                            WHERE id = $1
                            """,
                            user_id,
                            occurred_at,
                        )
                        if account_status == "invited":
                            await self._audit(
                                connection,
                                action_id=action_id,
                                actor_user_id=user_id,
                                event_type="identity.account.status_changed",
                                entity_type="user_account",
                                entity_id=user_id,
                                request_id=request_id,
                                payload={
                                    "previousStatus": "invited",
                                    "newStatus": "active",
                                },
                                occurred_at=occurred_at,
                            )
                    elif account_status != "active":
                        return None

                membership_id = uuid4()
                membership_inserted = await connection.fetchval(
                    """
                    INSERT INTO action_membership (
                        id,
                        action_id,
                        user_id,
                        role,
                        active_from,
                        created_at,
                        updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $5, $5)
                    ON CONFLICT (action_id, user_id, role) DO NOTHING
                    RETURNING true
                    """,
                    membership_id,
                    action_id,
                    user_id,
                    row["role_snapshot"],
                    occurred_at,
                )
                if membership_inserted is True:
                    await self._audit(
                        connection,
                        action_id=action_id,
                        actor_user_id=user_id,
                        event_type="identity.action_membership.granted",
                        entity_type="action_membership",
                        entity_id=membership_id,
                        request_id=request_id,
                        payload={
                            "userId": str(user_id),
                            "role": str(row["role_snapshot"]),
                        },
                        occurred_at=occurred_at,
                    )
                await connection.execute(
                    """
                    UPDATE action_invitation
                    SET status = 'accepted',
                        accepted_at = $2,
                        accepted_user_id = $3,
                        accepted_via = $4,
                        updated_at = $2
                    WHERE id = $1
                    """,
                    invitation_id,
                    occurred_at,
                    user_id,
                    method.value,
                )
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=user_id,
                    event_type="identity.invitation.accepted",
                    entity_type="action_invitation",
                    entity_id=invitation_id,
                    request_id=request_id,
                    payload={
                        "role": str(row["role_snapshot"]),
                        "method": method.value,
                    },
                    occurred_at=occurred_at,
                )
                return InvitationAcceptance(
                    user_id=user_id,
                    action_id=action_id,
                    action_name=str(row["action_name_snapshot"]),
                    role=ActionRole(str(row["role_snapshot"])),
                )

    async def _record_invalid_code(
        self,
        connection: asyncpg.Connection[Any],
        *,
        email: str,
        request_id: str,
        occurred_at: datetime,
    ) -> None:
        rows = await connection.fetch(
            """
            SELECT id, action_id, expires_at, failed_code_attempts
            FROM action_invitation
            WHERE email_snapshot = $1
              AND status = 'pending'
            FOR UPDATE
            """,
            email,
        )
        for row in rows:
            invitation_id = row["id"]
            action_id = row["action_id"]
            if occurred_at >= row["expires_at"]:
                await connection.execute(
                    """
                    UPDATE action_invitation
                    SET status = 'expired',
                        expired_at = $2,
                        updated_at = $2
                    WHERE id = $1
                    """,
                    invitation_id,
                    occurred_at,
                )
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=None,
                    event_type="identity.invitation.expired",
                    entity_type="action_invitation",
                    entity_id=invitation_id,
                    request_id=request_id,
                    payload={},
                    occurred_at=occurred_at,
                )
                continue
            decision = after_failed_code_attempt(int(row["failed_code_attempts"]))
            await connection.execute(
                """
                UPDATE action_invitation
                SET failed_code_attempts = $2,
                    last_failed_code_at = $3,
                    status = CASE WHEN $4 THEN 'revoked' ELSE status END,
                    revoked_at = CASE WHEN $4 THEN $3 ELSE revoked_at END,
                    updated_at = $3
                WHERE id = $1
                """,
                invitation_id,
                decision.attempts,
                occurred_at,
                decision.locked,
            )
            if decision.locked:
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=None,
                    event_type="identity.invitation.code_locked",
                    entity_type="action_invitation",
                    entity_id=invitation_id,
                    request_id=request_id,
                    payload={"attempts": str(decision.attempts)},
                    occurred_at=occurred_at,
                )

    async def revoke(
        self,
        invitation_id: UUID,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT id, action_id, status, expires_at
                    FROM action_invitation
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    invitation_id,
                )
                if row is None:
                    return False
                await self._authorized_context(
                    connection,
                    actor_user_id,
                    row["action_id"],
                    now=occurred_at,
                )
                if row["status"] != "pending":
                    return False
                if occurred_at >= row["expires_at"]:
                    await connection.execute(
                        """
                        UPDATE action_invitation
                        SET status = 'expired',
                            expired_at = $2,
                            updated_at = $2
                        WHERE id = $1
                        """,
                        invitation_id,
                        occurred_at,
                    )
                    return False
                await connection.execute(
                    """
                    UPDATE action_invitation
                    SET status = 'revoked',
                        revoked_at = $2,
                        updated_at = $2
                    WHERE id = $1
                    """,
                    invitation_id,
                    occurred_at,
                )
                await self._audit(
                    connection,
                    action_id=row["action_id"],
                    actor_user_id=actor_user_id,
                    event_type="identity.invitation.revoked",
                    entity_type="action_invitation",
                    entity_id=invitation_id,
                    request_id=request_id,
                    payload={},
                    occurred_at=occurred_at,
                )
                return True

    async def replace(
        self,
        replaced_invitation_id: UUID,
        replacement: ActionInvitation,
        mail_event: PendingOutboxEvent,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        minimum_age: timedelta,
    ) -> UUID | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT *
                    FROM action_invitation
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    replaced_invitation_id,
                )
                if row is None:
                    return None
                context = await self._authorized_context(
                    connection,
                    actor_user_id,
                    row["action_id"],
                    now=occurred_at,
                )
                if (
                    row["status"] != "pending"
                    or occurred_at >= row["expires_at"]
                    or occurred_at - row["created_at"] < minimum_age
                    or replacement.action_id != row["action_id"]
                    or replacement.action_name_snapshot != row["action_name_snapshot"]
                    or replacement.display_name_snapshot != row["display_name_snapshot"]
                    or replacement.role_snapshot.value != row["role_snapshot"]
                    or replacement.invited_by_user_id != actor_user_id
                    or replacement.invited_by_name_snapshot != context.invited_by_name
                ):
                    return None
                await connection.execute(
                    """
                    UPDATE action_invitation
                    SET status = 'revoked',
                        revoked_at = $2,
                        updated_at = $2
                    WHERE id = $1
                    """,
                    replaced_invitation_id,
                    occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO action_invitation (
                        id,
                        action_id,
                        invited_by_user_id,
                        email_snapshot,
                        display_name_snapshot,
                        action_name_snapshot,
                        invited_by_name_snapshot,
                        role_snapshot,
                        status,
                        token_digest,
                        code_digest,
                        expires_at,
                        created_at,
                        updated_at,
                        supersedes_invitation_id
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        'pending', $9, $10, $11, $12, $12, $13
                    )
                    """,
                    replacement.id,
                    replacement.action_id,
                    replacement.invited_by_user_id,
                    replacement.email_snapshot,
                    replacement.display_name_snapshot,
                    replacement.action_name_snapshot,
                    replacement.invited_by_name_snapshot,
                    replacement.role_snapshot.value,
                    replacement.token_digest,
                    replacement.code_digest,
                    replacement.expires_at,
                    occurred_at,
                    replaced_invitation_id,
                )
                await self._audit(
                    connection,
                    action_id=replacement.action_id,
                    actor_user_id=actor_user_id,
                    event_type="identity.invitation.revoked",
                    entity_type="action_invitation",
                    entity_id=replaced_invitation_id,
                    request_id=request_id,
                    payload={"replacementId": str(replacement.id)},
                    occurred_at=occurred_at,
                )
                await self._audit(
                    connection,
                    action_id=replacement.action_id,
                    actor_user_id=actor_user_id,
                    event_type="identity.invitation.reissued",
                    entity_type="action_invitation",
                    entity_id=replacement.id,
                    request_id=request_id,
                    payload={
                        "previousInvitationId": str(replaced_invitation_id),
                        "addressCorrected": str(
                            replacement.email_snapshot != row["email_snapshot"]
                        ).lower(),
                    },
                    occurred_at=occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO outbox_event (
                        id,
                        aggregate_type,
                        aggregate_id,
                        event_type,
                        idempotency_key,
                        payload,
                        available_at,
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $7)
                    """,
                    mail_event.id,
                    mail_event.aggregate_type,
                    mail_event.aggregate_id,
                    mail_event.event_type,
                    mail_event.idempotency_key,
                    json.dumps(mail_event.payload, separators=(",", ":")),
                    occurred_at,
                )
                return replacement.id

    @staticmethod
    async def _authorized_context(
        connection: asyncpg.Connection[Any],
        actor_user_id: UUID,
        action_id: UUID,
        *,
        now: datetime,
    ) -> InvitationContext:
        row = await connection.fetchrow(
            """
            SELECT
                action.id,
                action.name,
                action.status,
                actor.display_name AS invited_by_name
            FROM charity_action AS action
            JOIN user_account AS actor
              ON actor.id = $1
             AND actor.status = 'active'
            WHERE action.id = $2
              AND action.status IN ('draft', 'scheduled', 'active')
              AND (
                EXISTS (
                  SELECT 1
                  FROM user_global_role
                  WHERE user_id = $1 AND role = 'system_admin'
                )
                OR EXISTS (
                  SELECT 1
                  FROM action_membership
                  WHERE action_id = $2
                    AND user_id = $1
                    AND role = 'charity_admin'
                    AND active_from <= $3
                    AND (active_until IS NULL OR active_until > $3)
                )
              )
            """,
            actor_user_id,
            action_id,
            now,
        )
        if row is None:
            raise PermissionDenied(
                "invitation_action_forbidden",
                "Du darfst für diese Charity-Aktion keine Mitglieder einladen.",
            )
        return InvitationContext(
            action=InviteableAction(
                id=row["id"],
                name=str(row["name"]),
                status=str(row["status"]),
            ),
            invited_by_name=str(row["invited_by_name"]),
        )

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID | None,
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
            VALUES ($1, $2, $3, $4, 'action_invitation', $5, $6, $7::jsonb, $8)
            """,
            uuid4(),
            action_id,
            actor_user_id,
            event_type,
            entity_id,
            request_id,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            occurred_at,
        )
