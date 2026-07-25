"""asyncpg repositories and Unit of Work for action-progress commands."""

from __future__ import annotations

import json
from decimal import Decimal
from types import TracebackType
from typing import Any, Self
from uuid import UUID

import asyncpg

from leonaid.application.errors import ApplicationError
from leonaid.domain.outbox import PendingOutboxEvent


class AsyncpgActionProgressRepository:
    def __init__(self, connection: asyncpg.Connection[Any]) -> None:
        self._connection = connection

    async def set_actual_value(self, action_id: UUID, value: Decimal) -> Decimal:
        updated = await self._connection.fetchval(
            """
            UPDATE charity_action
            SET actual_value = $2, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING actual_value
            """,
            action_id,
            value,
        )
        if updated is None:
            raise ApplicationError(
                "action_not_found",
                "Die Charity-Aktion wurde nicht gefunden.",
            )
        return Decimal(updated)


class AsyncpgAuditRepository:
    def __init__(self, connection: asyncpg.Connection[Any]) -> None:
        self._connection = connection

    async def append_action_progress(
        self,
        *,
        event_id: UUID,
        action_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        actual_value: Decimal,
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type,
                entity_id, request_id, payload
            )
            VALUES (
                $1, $2, $3, 'charity_action.progress.recorded',
                'charity_action', $2, $4, $5::jsonb
            )
            """,
            event_id,
            action_id,
            actor_user_id,
            request_id,
            json.dumps({"actualValue": str(actual_value)}, separators=(",", ":")),
        )


class AsyncpgTransactionalOutboxRepository:
    def __init__(self, connection: asyncpg.Connection[Any]) -> None:
        self._connection = connection

    async def append(self, event: PendingOutboxEvent) -> None:
        await self._connection.execute(
            """
            INSERT INTO outbox_event (
                id, aggregate_type, aggregate_id, event_type,
                idempotency_key, payload
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            event.id,
            event.aggregate_type,
            event.aggregate_id,
            event.event_type,
            event.idempotency_key,
            json.dumps(event.payload, separators=(",", ":")),
        )


class AsyncpgCommandReceiptRepository:
    def __init__(self, connection: asyncpg.Connection[Any]) -> None:
        self._connection = connection

    async def reserve(
        self,
        *,
        idempotency_key: str,
        command_type: str,
        request_hash: str,
    ) -> dict[str, str] | None:
        inserted = await self._connection.fetchval(
            """
            INSERT INTO command_receipt (
                idempotency_key, command_type, request_hash
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING true
            """,
            idempotency_key,
            command_type,
            request_hash,
        )
        if inserted:
            return None
        row = await self._connection.fetchrow(
            """
            SELECT command_type, request_hash, result
            FROM command_receipt
            WHERE idempotency_key = $1
            """,
            idempotency_key,
        )
        if row is None:
            raise RuntimeError("Befehlsnachweis verschwand während der Transaktion.")
        if row["command_type"] != command_type or row["request_hash"] != request_hash:
            raise ApplicationError(
                "idempotency_conflict",
                "Dieser Idempotenzschlüssel wurde für andere Eingaben verwendet.",
            )
        result = row["result"]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            raise RuntimeError("Befehlsnachweis ist noch nicht abgeschlossen.")
        return {str(key): str(value) for key, value in result.items()}

    async def complete(
        self,
        *,
        idempotency_key: str,
        result: dict[str, str],
    ) -> None:
        status = await self._connection.execute(
            """
            UPDATE command_receipt
            SET result = $2::jsonb, completed_at = CURRENT_TIMESTAMP
            WHERE idempotency_key = $1 AND result IS NULL
            """,
            idempotency_key,
            json.dumps(result, separators=(",", ":")),
        )
        if status != "UPDATE 1":
            raise RuntimeError("Befehlsnachweis konnte nicht abgeschlossen werden.")


class AsyncpgActionProgressUnitOfWork:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool
        self._connection: asyncpg.Connection[Any] | None = None
        self._transaction: asyncpg.Transaction | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        connection = await self._pool.acquire()
        transaction = connection.transaction()
        await transaction.start()
        self._connection = connection
        self._transaction = transaction
        self.actions = AsyncpgActionProgressRepository(connection)
        self.audit = AsyncpgAuditRepository(connection)
        self.outbox = AsyncpgTransactionalOutboxRepository(connection)
        self.command_receipts = AsyncpgCommandReceiptRepository(connection)
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        transaction = self._transaction
        connection = self._connection
        if transaction is None or connection is None:
            return
        try:
            if not self._committed:
                await transaction.rollback()
        finally:
            await self._pool.release(connection)
            self._transaction = None
            self._connection = None

    async def commit(self) -> None:
        if self._transaction is None:
            raise RuntimeError("Unit of Work wurde nicht gestartet.")
        await self._transaction.commit()
        self._committed = True


class AsyncpgActionProgressUnitOfWorkFactory:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    def __call__(self) -> AsyncpgActionProgressUnitOfWork:
        return AsyncpgActionProgressUnitOfWork(self._pool)
