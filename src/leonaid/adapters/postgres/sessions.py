"""Atomic PostgreSQL passwordless-login and session adapter."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.sessions import LoginAccount, SessionCompletion
from leonaid.domain.outbox import PendingOutboxEvent
from leonaid.domain.sessions import (
    LoginChallenge,
    LoginPurpose,
    after_failed_login_code,
)


class AsyncpgSessionRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def active_account_for_email(self, email: str) -> LoginAccount | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, email, display_name
                FROM user_account
                WHERE email = $1
                  AND status = 'active'
                """,
                email,
            )
        return self._account(row)

    async def create_challenge(
        self,
        challenge: LoginChallenge,
        mail_event: PendingOutboxEvent,
        *,
        requested_by_user_id: UUID | None,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                account = await connection.fetchrow(
                    """
                    SELECT id
                    FROM user_account
                    WHERE id = $1
                      AND email = $2
                      AND status = 'active'
                    FOR UPDATE
                    """,
                    challenge.user_id,
                    challenge.email_snapshot,
                )
                if account is None:
                    return False
                expired_rows = await connection.fetch(
                    """
                    UPDATE login_challenge
                    SET status = 'expired',
                        expired_at = $3,
                        updated_at = $3
                    WHERE user_id = $1
                      AND purpose = $2
                      AND status = 'pending'
                      AND expires_at <= $3
                    RETURNING id
                    """,
                    challenge.user_id,
                    challenge.purpose.value,
                    occurred_at,
                )
                for row in expired_rows:
                    await self._audit(
                        connection,
                        actor_user_id=requested_by_user_id,
                        event_type="identity.login_challenge.expired",
                        entity_type="login_challenge",
                        entity_id=row["id"],
                        request_id=request_id,
                        payload={"purpose": challenge.purpose.value},
                        occurred_at=occurred_at,
                    )
                existing = await connection.fetchval(
                    """
                    SELECT id
                    FROM login_challenge
                    WHERE user_id = $1
                      AND purpose = $2
                      AND status = 'pending'
                    FOR UPDATE
                    """,
                    challenge.user_id,
                    challenge.purpose.value,
                )
                if existing is not None:
                    return False
                await connection.execute(
                    """
                    INSERT INTO login_challenge (
                        id,
                        user_id,
                        purpose,
                        email_snapshot,
                        token_digest,
                        code_digest,
                        status,
                        expires_at,
                        failed_code_attempts,
                        created_at,
                        updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, 0, $8, $8)
                    """,
                    challenge.id,
                    challenge.user_id,
                    challenge.purpose.value,
                    challenge.email_snapshot,
                    challenge.token_digest,
                    challenge.code_digest,
                    challenge.expires_at,
                    occurred_at,
                )
                await self._audit(
                    connection,
                    actor_user_id=requested_by_user_id,
                    event_type="identity.login_challenge.created",
                    entity_type="login_challenge",
                    entity_id=challenge.id,
                    request_id=request_id,
                    payload={"purpose": challenge.purpose.value},
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
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                    """,
                    mail_event.id,
                    mail_event.aggregate_type,
                    mail_event.aggregate_id,
                    mail_event.event_type,
                    mail_event.idempotency_key,
                    json.dumps(mail_event.payload, separators=(",", ":")),
                    occurred_at,
                )
                return True

    async def complete_login(
        self,
        *,
        purpose: LoginPurpose,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
        session_id: UUID,
        session_token_digest: str,
        session_expires_at: datetime,
        current_session_digest: str | None,
        device_hint: str | None,
        request_id: str,
        occurred_at: datetime,
    ) -> SessionCompletion | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await self._challenge_for_update(
                    connection,
                    purpose=purpose,
                    token_digest=token_digest,
                    email=email,
                    code_digest=code_digest,
                )
                if row is None:
                    if email is not None and code_digest is not None:
                        await self._record_invalid_code(
                            connection,
                            email=email,
                            purpose=purpose,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                    return None
                if row["status"] != "pending":
                    return None
                if occurred_at >= row["expires_at"]:
                    await self._expire_challenge(
                        connection,
                        row["id"],
                        row["user_id"],
                        purpose,
                        request_id=request_id,
                        occurred_at=occurred_at,
                    )
                    return None
                account_row = await connection.fetchrow(
                    """
                    SELECT id, email, display_name
                    FROM user_account
                    WHERE id = $1
                      AND email = $2
                      AND status = 'active'
                    FOR UPDATE
                    """,
                    row["user_id"],
                    row["email_snapshot"],
                )
                if account_row is None:
                    return None
                user_id = account_row["id"]
                if purpose is LoginPurpose.LOGIN:
                    await connection.execute(
                        """
                        INSERT INTO user_session (
                            id,
                            user_id,
                            token_digest,
                            expires_at,
                            last_seen_at,
                            fresh_login_at,
                            device_hint,
                            created_at,
                            updated_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $5, $6, $5, $5)
                        """,
                        session_id,
                        user_id,
                        session_token_digest,
                        session_expires_at,
                        occurred_at,
                        device_hint,
                    )
                    session_entity_id = session_id
                    absolute_expiry = session_expires_at
                    session_event = "identity.session.created"
                else:
                    current = await connection.fetchrow(
                        """
                        SELECT id, expires_at
                        FROM user_session
                        WHERE token_digest = $1
                          AND user_id = $2
                          AND revoked_at IS NULL
                          AND expires_at > $3
                        FOR UPDATE
                        """,
                        current_session_digest,
                        user_id,
                        occurred_at,
                    )
                    if current is None:
                        return None
                    session_entity_id = current["id"]
                    absolute_expiry = current["expires_at"]
                    await connection.execute(
                        """
                        UPDATE user_session
                        SET token_digest = $2,
                            last_seen_at = $3,
                            fresh_login_at = $3,
                            device_hint = COALESCE($4, device_hint),
                            updated_at = $3
                        WHERE id = $1
                        """,
                        session_entity_id,
                        session_token_digest,
                        occurred_at,
                        device_hint,
                    )
                    session_event = "identity.session.fresh_login"
                await connection.execute(
                    """
                    UPDATE login_challenge
                    SET status = 'consumed',
                        consumed_at = $2,
                        updated_at = $2
                    WHERE id = $1
                    """,
                    row["id"],
                    occurred_at,
                )
                await self._audit(
                    connection,
                    actor_user_id=user_id,
                    event_type="identity.login_challenge.consumed",
                    entity_type="login_challenge",
                    entity_id=row["id"],
                    request_id=request_id,
                    payload={"purpose": purpose.value},
                    occurred_at=occurred_at,
                )
                await self._audit(
                    connection,
                    actor_user_id=user_id,
                    event_type=session_event,
                    entity_type="user_session",
                    entity_id=session_entity_id,
                    request_id=request_id,
                    payload={},
                    occurred_at=occurred_at,
                )
                account = self._account(account_row)
                if account is None:
                    return None
                return SessionCompletion(
                    account=account,
                    session_id=session_entity_id,
                    expires_at=absolute_expiry,
                )

    async def issue_session(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        token_digest: str,
        expires_at: datetime,
        device_hint: str | None,
        request_id: str,
        occurred_at: datetime,
    ) -> LoginAccount | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                account_row = await connection.fetchrow(
                    """
                    SELECT id, email, display_name
                    FROM user_account
                    WHERE id = $1
                      AND status = 'active'
                    FOR UPDATE
                    """,
                    user_id,
                )
                if account_row is None:
                    return None
                await connection.execute(
                    """
                    INSERT INTO user_session (
                        id,
                        user_id,
                        token_digest,
                        expires_at,
                        last_seen_at,
                        fresh_login_at,
                        device_hint,
                        created_at,
                        updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $5, $6, $5, $5)
                    """,
                    session_id,
                    user_id,
                    token_digest,
                    expires_at,
                    occurred_at,
                    device_hint,
                )
                await self._audit(
                    connection,
                    actor_user_id=user_id,
                    event_type="identity.session.created",
                    entity_type="user_session",
                    entity_id=session_id,
                    request_id=request_id,
                    payload={"source": "invitation"},
                    occurred_at=occurred_at,
                )
                return self._account(account_row)

    async def revoke_session(
        self,
        *,
        token_digest: str,
        request_id: str,
        occurred_at: datetime,
    ) -> bool:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE user_session
                    SET revoked_at = $2,
                        updated_at = $2
                    WHERE token_digest = $1
                      AND revoked_at IS NULL
                    RETURNING id, user_id
                    """,
                    token_digest,
                    occurred_at,
                )
                if row is None:
                    return False
                await self._audit(
                    connection,
                    actor_user_id=row["user_id"],
                    event_type="identity.session.revoked",
                    entity_type="user_session",
                    entity_id=row["id"],
                    request_id=request_id,
                    payload={"reason": "logout"},
                    occurred_at=occurred_at,
                )
                return True

    async def revoke_user_sessions(
        self,
        *,
        target_user_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                exists = await connection.fetchval(
                    "SELECT true FROM user_account WHERE id = $1 FOR UPDATE",
                    target_user_id,
                )
                if exists is not True:
                    return None
                rows = await connection.fetch(
                    """
                    UPDATE user_session
                    SET revoked_at = $2,
                        updated_at = $2
                    WHERE user_id = $1
                      AND revoked_at IS NULL
                    RETURNING id
                    """,
                    target_user_id,
                    occurred_at,
                )
                await self._audit(
                    connection,
                    actor_user_id=actor_user_id,
                    event_type="identity.user_sessions.revoked",
                    entity_type="user_account",
                    entity_id=target_user_id,
                    request_id=request_id,
                    payload={"revokedCount": str(len(rows))},
                    occurred_at=occurred_at,
                )
                return len(rows)

    async def _challenge_for_update(
        self,
        connection: asyncpg.Connection[Any],
        *,
        purpose: LoginPurpose,
        token_digest: str | None,
        email: str | None,
        code_digest: str | None,
    ) -> asyncpg.Record | None:
        if token_digest is not None:
            return await connection.fetchrow(
                """
                SELECT *
                FROM login_challenge
                WHERE purpose = $1
                  AND token_digest = $2
                FOR UPDATE
                """,
                purpose.value,
                token_digest,
            )
        return await connection.fetchrow(
            """
            SELECT *
            FROM login_challenge
            WHERE purpose = $1
              AND email_snapshot = $2
              AND code_digest = $3
            FOR UPDATE
            """,
            purpose.value,
            email,
            code_digest,
        )

    async def _record_invalid_code(
        self,
        connection: asyncpg.Connection[Any],
        *,
        email: str,
        purpose: LoginPurpose,
        request_id: str,
        occurred_at: datetime,
    ) -> None:
        rows = await connection.fetch(
            """
            SELECT id, user_id, expires_at, failed_code_attempts
            FROM login_challenge
            WHERE email_snapshot = $1
              AND purpose = $2
              AND status = 'pending'
            FOR UPDATE
            """,
            email,
            purpose.value,
        )
        for row in rows:
            if occurred_at >= row["expires_at"]:
                await self._expire_challenge(
                    connection,
                    row["id"],
                    row["user_id"],
                    purpose,
                    request_id=request_id,
                    occurred_at=occurred_at,
                )
                continue
            decision = after_failed_login_code(int(row["failed_code_attempts"]))
            await connection.execute(
                """
                UPDATE login_challenge
                SET failed_code_attempts = $2,
                    last_failed_code_at = $3,
                    status = CASE WHEN $4 THEN 'revoked' ELSE status END,
                    revoked_at = CASE WHEN $4 THEN $3 ELSE revoked_at END,
                    updated_at = $3
                WHERE id = $1
                """,
                row["id"],
                decision.attempts,
                occurred_at,
                decision.locked,
            )
            if decision.locked:
                await self._audit(
                    connection,
                    actor_user_id=None,
                    event_type="identity.login_challenge.code_locked",
                    entity_type="login_challenge",
                    entity_id=row["id"],
                    request_id=request_id,
                    payload={
                        "purpose": purpose.value,
                        "attempts": str(decision.attempts),
                    },
                    occurred_at=occurred_at,
                )

    async def _expire_challenge(
        self,
        connection: asyncpg.Connection[Any],
        challenge_id: UUID,
        user_id: UUID,
        purpose: LoginPurpose,
        *,
        request_id: str,
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            UPDATE login_challenge
            SET status = 'expired',
                expired_at = $2,
                updated_at = $2
            WHERE id = $1
            """,
            challenge_id,
            occurred_at,
        )
        await self._audit(
            connection,
            actor_user_id=user_id,
            event_type="identity.login_challenge.expired",
            entity_type="login_challenge",
            entity_id=challenge_id,
            request_id=request_id,
            payload={"purpose": purpose.value},
            occurred_at=occurred_at,
        )

    @staticmethod
    def _account(row: asyncpg.Record | None) -> LoginAccount | None:
        if row is None:
            return None
        return LoginAccount(
            id=row["id"],
            email=str(row["email"]),
            display_name=str(row["display_name"]),
        )

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
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
                actor_user_id,
                event_type,
                entity_type,
                entity_id,
                request_id,
                payload,
                occurred_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
            """,
            uuid4(),
            actor_user_id,
            event_type,
            entity_type,
            entity_id,
            request_id,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            occurred_at,
        )
