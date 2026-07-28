"""Atomic PostgreSQL adapter for confirmed login-email changes."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.email_changes import (
    EmailChangeConfirmation,
    EmailChangeConfirmResult,
    EmailChangeContext,
    EmailChangeCreateResult,
)
from leonaid.domain.email_changes import EmailChangeStatus, PendingEmailChange
from leonaid.domain.outbox import PendingOutboxEvent


class AsyncpgEmailChangeRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def context(self, user_id: UUID) -> EmailChangeContext | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, email, display_name
                FROM user_account
                WHERE id = $1
                  AND status = 'active'
                """,
                user_id,
            )
        if row is None:
            return None
        return EmailChangeContext(
            user_id=row["id"],
            email=str(row["email"]),
            display_name=str(row["display_name"]),
        )

    async def create(
        self,
        change: PendingEmailChange,
        mail_events: tuple[PendingOutboxEvent, ...],
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> EmailChangeCreateResult:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                authorized = await connection.fetchval(
                    """
                    SELECT true
                    FROM user_account AS actor
                    JOIN user_global_role AS role
                      ON role.user_id = actor.id
                     AND role.role = 'system_admin'
                    WHERE actor.id = $1
                      AND actor.status = 'active'
                    """,
                    actor_user_id,
                )
                if authorized is not True:
                    return EmailChangeCreateResult.CONTEXT_CHANGED
                target = await connection.fetchrow(
                    """
                    SELECT id, email, display_name
                    FROM user_account
                    WHERE id = $1
                      AND status = 'active'
                    FOR UPDATE
                    """,
                    change.user_id,
                )
                if target is None:
                    return EmailChangeCreateResult.TARGET_NOT_FOUND
                if (
                    target["email"] != change.old_email_snapshot
                    or target["display_name"] != change.display_name_snapshot
                    or change.requested_by_user_id != actor_user_id
                ):
                    return EmailChangeCreateResult.CONTEXT_CHANGED
                await connection.execute(
                    """
                    UPDATE email_change_request
                    SET status = 'expired',
                        expired_at = $2,
                        updated_at = $2
                    WHERE user_id = $1
                      AND status = 'pending'
                      AND expires_at <= $2
                    """,
                    change.user_id,
                    occurred_at,
                )
                if await connection.fetchval(
                    """
                    SELECT true
                    FROM email_change_request
                    WHERE user_id = $1
                      AND status = 'pending'
                    FOR UPDATE
                    """,
                    change.user_id,
                ):
                    return EmailChangeCreateResult.CHANGE_PENDING
                if await connection.fetchval(
                    "SELECT true FROM user_account WHERE email = $1",
                    change.new_email_snapshot,
                ):
                    return EmailChangeCreateResult.ADDRESS_IN_USE
                await connection.execute(
                    """
                    INSERT INTO email_change_request (
                      id, user_id, requested_by_user_id,
                      old_email_snapshot, new_email_snapshot,
                      display_name_snapshot, status, token_digest, code_digest,
                      expires_at, created_at, updated_at
                    )
                    VALUES (
                      $1, $2, $3, $4, $5, $6, 'pending', $7, $8, $9, $10, $10
                    )
                    """,
                    change.id,
                    change.user_id,
                    change.requested_by_user_id,
                    change.old_email_snapshot,
                    change.new_email_snapshot,
                    change.display_name_snapshot,
                    change.token_digest,
                    change.code_digest,
                    change.expires_at,
                    occurred_at,
                )
                await self._insert_events(connection, mail_events, occurred_at)
                await self._audit(
                    connection,
                    actor_user_id=actor_user_id,
                    event_type="identity.email_change.requested",
                    entity_id=change.id,
                    request_id=request_id,
                    payload={"targetUserId": str(change.user_id)},
                    occurred_at=occurred_at,
                )
                return EmailChangeCreateResult.CREATED

    async def confirm(
        self,
        *,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        completion_mail_events: Callable[
            [PendingEmailChange], tuple[PendingOutboxEvent, ...]
        ],
        request_id: str,
        occurred_at: datetime,
    ) -> tuple[EmailChangeConfirmResult, EmailChangeConfirmation | None]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                if token_digest is not None:
                    row = await connection.fetchrow(
                        """
                        SELECT *
                        FROM email_change_request
                        WHERE token_digest = $1
                        FOR UPDATE
                        """,
                        token_digest,
                    )
                else:
                    row = await connection.fetchrow(
                        """
                        SELECT *
                        FROM email_change_request
                        WHERE new_email_snapshot = $1
                          AND code_digest = $2
                        FOR UPDATE
                        """,
                        email,
                        code_digest,
                    )
                if row is None:
                    if email is not None:
                        await self._failed_code(
                            connection,
                            email=email,
                            occurred_at=occurred_at,
                        )
                    return EmailChangeConfirmResult.INVALID, None
                if row["status"] != "pending":
                    return EmailChangeConfirmResult.INVALID, None
                if occurred_at >= row["expires_at"]:
                    await connection.execute(
                        """
                        UPDATE email_change_request
                        SET status = 'expired', expired_at = $2, updated_at = $2
                        WHERE id = $1
                        """,
                        row["id"],
                        occurred_at,
                    )
                    return EmailChangeConfirmResult.INVALID, None
                account = await connection.fetchrow(
                    """
                    SELECT id, email
                    FROM user_account
                    WHERE id = $1
                      AND status = 'active'
                    FOR UPDATE
                    """,
                    row["user_id"],
                )
                if account is None or account["email"] != row["old_email_snapshot"]:
                    return EmailChangeConfirmResult.INVALID, None
                occupied = await connection.fetchval(
                    """
                    SELECT true
                    FROM user_account
                    WHERE email = $1
                      AND id <> $2
                    """,
                    row["new_email_snapshot"],
                    row["user_id"],
                )
                if occupied is True:
                    await connection.execute(
                        """
                        UPDATE email_change_request
                        SET status = 'revoked', revoked_at = $2, updated_at = $2
                        WHERE id = $1
                        """,
                        row["id"],
                        occurred_at,
                    )
                    return EmailChangeConfirmResult.ADDRESS_IN_USE, None
                await connection.execute(
                    """
                    UPDATE user_account
                    SET email = $2,
                        email_verified_at = $3,
                        revision = revision + 1,
                        updated_at = $3
                    WHERE id = $1
                    """,
                    row["user_id"],
                    row["new_email_snapshot"],
                    occurred_at,
                )
                sessions = await connection.fetch(
                    """
                    UPDATE user_session
                    SET revoked_at = $2, updated_at = $2
                    WHERE user_id = $1
                      AND revoked_at IS NULL
                    RETURNING id
                    """,
                    row["user_id"],
                    occurred_at,
                )
                await connection.execute(
                    """
                    UPDATE login_challenge
                    SET status = 'revoked', revoked_at = $2, updated_at = $2
                    WHERE user_id = $1
                      AND status = 'pending'
                    """,
                    row["user_id"],
                    occurred_at,
                )
                await connection.execute(
                    """
                    UPDATE email_change_request
                    SET status = 'confirmed',
                        confirmed_at = $2,
                        updated_at = $2
                    WHERE id = $1
                    """,
                    row["id"],
                    occurred_at,
                )
                change = self._change(row)
                await self._insert_events(
                    connection,
                    completion_mail_events(change),
                    occurred_at,
                )
                await self._audit(
                    connection,
                    actor_user_id=row["user_id"],
                    event_type="identity.email_change.confirmed",
                    entity_id=row["id"],
                    request_id=request_id,
                    payload={"revokedSessionCount": str(len(sessions))},
                    occurred_at=occurred_at,
                )
                return (
                    EmailChangeConfirmResult.CONFIRMED,
                    EmailChangeConfirmation(
                        user_id=row["user_id"],
                        revoked_session_count=len(sessions),
                    ),
                )

    async def _failed_code(
        self,
        connection: asyncpg.Connection[Any],
        *,
        email: str,
        occurred_at: datetime,
    ) -> None:
        rows = await connection.fetch(
            """
            SELECT id, expires_at, failed_code_attempts
            FROM email_change_request
            WHERE new_email_snapshot = $1
              AND status = 'pending'
            FOR UPDATE
            """,
            email,
        )
        for row in rows:
            if occurred_at >= row["expires_at"]:
                await connection.execute(
                    """
                    UPDATE email_change_request
                    SET status = 'expired', expired_at = $2, updated_at = $2
                    WHERE id = $1
                    """,
                    row["id"],
                    occurred_at,
                )
                continue
            attempts = int(row["failed_code_attempts"]) + 1
            locked = attempts >= 5
            await connection.execute(
                """
                UPDATE email_change_request
                SET failed_code_attempts = $2,
                    last_failed_code_at = $3,
                    status = CASE WHEN $4 THEN 'revoked' ELSE status END,
                    revoked_at = CASE WHEN $4 THEN $3 ELSE revoked_at END,
                    updated_at = $3
                WHERE id = $1
                """,
                row["id"],
                attempts,
                occurred_at,
                locked,
            )

    @staticmethod
    def _change(row: asyncpg.Record) -> PendingEmailChange:
        return PendingEmailChange(
            id=row["id"],
            user_id=row["user_id"],
            requested_by_user_id=row["requested_by_user_id"],
            old_email_snapshot=str(row["old_email_snapshot"]),
            new_email_snapshot=str(row["new_email_snapshot"]),
            display_name_snapshot=str(row["display_name_snapshot"]),
            status=EmailChangeStatus(str(row["status"])),
            token_digest=str(row["token_digest"]),
            code_digest=str(row["code_digest"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            failed_code_attempts=int(row["failed_code_attempts"]),
        )

    @staticmethod
    async def _insert_events(
        connection: asyncpg.Connection[Any],
        events: tuple[PendingOutboxEvent, ...],
        occurred_at: datetime,
    ) -> None:
        for event in events:
            await connection.execute(
                """
                INSERT INTO outbox_event (
                  id, aggregate_type, aggregate_id, event_type,
                  idempotency_key, payload, available_at, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $7)
                """,
                event.id,
                event.aggregate_type,
                event.aggregate_id,
                event.event_type,
                event.idempotency_key,
                json.dumps(event.payload, separators=(",", ":")),
                occurred_at,
            )

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        actor_user_id: UUID,
        event_type: str,
        entity_id: UUID,
        request_id: str,
        payload: dict[str, str],
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
              id, actor_user_id, event_type, entity_type, entity_id,
              request_id, payload, occurred_at
            )
            VALUES ($1, $2, $3, 'email_change_request', $4, $5, $6::jsonb, $7)
            """,
            uuid4(),
            actor_user_id,
            event_type,
            entity_id,
            request_id,
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )
