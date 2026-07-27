"""Transactional PostgreSQL adapter for payments and invoice cancellations."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.invoice_settlements import InvoiceSettlementRepository
from leonaid.domain.commitments import Money
from leonaid.domain.invoice_settlements import (
    InvoiceCancellation,
    InvoiceSettlementState,
    PaymentRecord,
)
from leonaid.domain.invoices import InvoiceStatus

PAYMENT_COMMAND = "record_invoice_payment_v1"
CANCELLATION_COMMAND = "cancel_invoice_v1"


class AsyncpgInvoiceSettlementRepository(InvoiceSettlementRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def record_payment(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        amount: Money,
        received_on: date,
        reference: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentRecord:
        async with self._pool.acquire() as connection:
            for attempt in range(3):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._record_payment_once(
                            connection,
                            action_id=action_id,
                            invoice_id=invoice_id,
                            amount=amount,
                            received_on=received_on,
                            reference=reference,
                            actor_user_id=actor_user_id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except asyncpg.SerializationError:
                    if attempt == 2:
                        raise Conflict(
                            "invoice_payment_concurrent_retry",
                            "Der Zahlungseingang wurde gleichzeitig bearbeitet. "
                            "Bitte versuche denselben Vorgang erneut.",
                        ) from None
        raise RuntimeError("Die Zahlungstransaktion wurde nicht ausgeführt.")

    async def cancel(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        reason: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceCancellation:
        async with self._pool.acquire() as connection:
            for attempt in range(3):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._cancel_once(
                            connection,
                            action_id=action_id,
                            invoice_id=invoice_id,
                            reason=reason,
                            actor_user_id=actor_user_id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except asyncpg.SerializationError:
                    if attempt == 2:
                        raise Conflict(
                            "invoice_cancellation_concurrent_retry",
                            "Das Storno wurde gleichzeitig bearbeitet. Bitte "
                            "versuche denselben Vorgang erneut.",
                        ) from None
        raise RuntimeError("Die Stornotransaktion wurde nicht ausgeführt.")

    async def _record_payment_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        invoice_id: UUID,
        amount: Money,
        received_on: date,
        reference: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentRecord:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"invoice-payment:{invoice_id}",
        )
        replayed_id = await self._existing_command(
            connection,
            command_type=PAYMENT_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result_key="paymentId",
        )
        if replayed_id is not None:
            return await self._get_payment(
                connection,
                action_id=action_id,
                payment_id=replayed_id,
                replayed=True,
            )

        invoice = await self._invoice_state(
            connection,
            action_id=action_id,
            invoice_id=invoice_id,
        )
        existing = await connection.fetchval(
            "SELECT id FROM payment_record WHERE invoice_id = $1",
            invoice_id,
        )
        if existing is not None:
            raise Conflict(
                "invoice_payment_already_recorded",
                "Für diese Rechnung ist bereits eine Vollzahlung verbucht.",
            )
        if invoice.status is InvoiceStatus.CANCELLED:
            raise Conflict(
                "invoice_payment_cancelled",
                "Eine stornierte Rechnung kann nicht als bezahlt markiert werden.",
            )
        if invoice.status is InvoiceStatus.PAID:
            raise Conflict(
                "invoice_payment_already_recorded",
                "Diese Rechnung ist bereits als bezahlt markiert.",
            )

        payment = PaymentRecord.record_full(
            id=uuid4(),
            invoice=invoice,
            amount=amount,
            received_on=received_on,
            reference=reference,
            recorded_by_user_id=actor_user_id,
            recorded_at=occurred_at,
        )
        await connection.execute(
            """
            INSERT INTO payment_record (
                id, invoice_id, amount_minor, currency, received_on,
                recorded_by_user_id, reference, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            payment.id,
            payment.invoice_id,
            payment.amount.amount_minor,
            payment.amount.currency,
            payment.received_on,
            payment.recorded_by_user_id,
            payment.reference,
            payment.recorded_at,
        )
        updated = await connection.execute(
            """
            UPDATE invoice
            SET status = 'paid',
                updated_at = $2
            WHERE id = $1
              AND status IN ('issued', 'sent')
            """,
            invoice_id,
            occurred_at,
        )
        if updated != "UPDATE 1":
            raise Conflict(
                "invoice_payment_state_changed",
                "Der Rechnungsstatus hat sich gleichzeitig geändert. Bitte "
                "lade den Beleg neu.",
            )
        await self._audit(
            connection,
            action_id=action_id,
            actor_user_id=actor_user_id,
            event_type="invoice_payment_recorded",
            entity_type="payment_record",
            entity_id=payment.id,
            request_id=request_id,
            payload={
                "invoiceId": str(invoice_id),
                "invoiceNumber": invoice.number,
                "amountMinor": payment.amount.amount_minor,
                "currency": payment.amount.currency,
                "receivedOn": payment.received_on.isoformat(),
                "reference": payment.reference,
                "previousStatus": invoice.status.value,
                "status": InvoiceStatus.PAID.value,
            },
            occurred_at=occurred_at,
        )
        await self._complete_command(
            connection,
            command_type=PAYMENT_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"paymentId": str(payment.id)},
            occurred_at=occurred_at,
        )
        return await self._get_payment(
            connection,
            action_id=action_id,
            payment_id=payment.id,
            replayed=False,
        )

    async def _cancel_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        invoice_id: UUID,
        reason: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceCancellation:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"invoice-cancellation:{invoice_id}",
        )
        replayed_id = await self._existing_command(
            connection,
            command_type=CANCELLATION_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result_key="cancellationId",
        )
        if replayed_id is not None:
            return await self._get_cancellation(
                connection,
                action_id=action_id,
                cancellation_id=replayed_id,
                replayed=True,
            )

        invoice = await self._invoice_state(
            connection,
            action_id=action_id,
            invoice_id=invoice_id,
        )
        existing = await connection.fetchval(
            "SELECT id FROM invoice_cancellation WHERE invoice_id = $1",
            invoice_id,
        )
        if existing is not None or invoice.status is InvoiceStatus.CANCELLED:
            raise Conflict(
                "invoice_cancellation_already_recorded",
                "Diese Rechnung ist bereits dauerhaft storniert.",
            )

        cancellation = InvoiceCancellation.cancel(
            id=uuid4(),
            invoice=invoice,
            reason=reason,
            requested_by_user_id=actor_user_id,
            requested_at=occurred_at,
        )
        await connection.execute(
            """
            INSERT INTO invoice_cancellation (
                id, action_id, invoice_id, original_status,
                reason_snapshot, requested_by_user_id, idempotency_key,
                requested_at, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
            """,
            cancellation.id,
            cancellation.action_id,
            cancellation.invoice_id,
            cancellation.original_status.value,
            cancellation.reason,
            cancellation.requested_by_user_id,
            idempotency_key,
            cancellation.requested_at,
        )
        updated = await connection.execute(
            """
            UPDATE invoice
            SET status = 'cancelled',
                updated_at = $2
            WHERE id = $1
              AND status IN ('issued', 'sent', 'paid')
            """,
            invoice_id,
            occurred_at,
        )
        if updated != "UPDATE 1":
            raise Conflict(
                "invoice_cancellation_state_changed",
                "Der Rechnungsstatus hat sich gleichzeitig geändert. Bitte "
                "lade den Beleg neu.",
            )
        await self._audit(
            connection,
            action_id=action_id,
            actor_user_id=actor_user_id,
            event_type="invoice_cancelled",
            entity_type="invoice_cancellation",
            entity_id=cancellation.id,
            request_id=request_id,
            payload={
                "invoiceId": str(invoice_id),
                "invoiceNumber": invoice.number,
                "previousStatus": invoice.status.value,
                "status": InvoiceStatus.CANCELLED.value,
                "reason": cancellation.reason,
            },
            occurred_at=occurred_at,
        )
        await self._complete_command(
            connection,
            command_type=CANCELLATION_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"cancellationId": str(cancellation.id)},
            occurred_at=occurred_at,
        )
        return await self._get_cancellation(
            connection,
            action_id=action_id,
            cancellation_id=cancellation.id,
            replayed=False,
        )

    @staticmethod
    async def _invoice_state(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        invoice_id: UUID,
    ) -> InvoiceSettlementState:
        row = await connection.fetchrow(
            """
            SELECT
                id, action_id, number, status, issued_at,
                gross_minor, currency
            FROM invoice
            WHERE id = $1
              AND action_id = $2
            FOR UPDATE
            """,
            invoice_id,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "invoice_settlement_not_found",
                "Die Rechnung wurde in dieser Charity-Aktion nicht gefunden.",
            )
        return InvoiceSettlementState(
            id=row["id"],
            action_id=row["action_id"],
            number=str(row["number"]),
            status=InvoiceStatus(str(row["status"])),
            issued_at=row["issued_at"],
            gross=Money(int(row["gross_minor"]), str(row["currency"])),
        )

    @staticmethod
    async def _existing_command(
        connection: asyncpg.Connection[Any],
        *,
        command_type: str,
        idempotency_key: str,
        request_hash: str,
        result_key: str,
    ) -> UUID | None:
        inserted = await connection.fetchval(
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
        row = await connection.fetchrow(
            """
            SELECT command_type, request_hash, result
            FROM command_receipt
            WHERE idempotency_key = $1
            FOR UPDATE
            """,
            idempotency_key,
        )
        if row is None:
            raise RuntimeError("Der Finanz-Befehlsnachweis ist verschwunden.")
        if (
            str(row["command_type"]) != command_type
            or str(row["request_hash"]) != request_hash
        ):
            raise Conflict(
                "idempotency_conflict",
                "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
            )
        result = row["result"]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict) or result_key not in result:
            raise RuntimeError("Der Finanz-Befehlsnachweis ist unvollständig.")
        return UUID(str(result[result_key]))

    @staticmethod
    async def _complete_command(
        connection: asyncpg.Connection[Any],
        *,
        command_type: str,
        idempotency_key: str,
        request_hash: str,
        result: dict[str, str],
        occurred_at: datetime,
    ) -> None:
        updated = await connection.execute(
            """
            UPDATE command_receipt
            SET result = $4::jsonb,
                completed_at = $5
            WHERE idempotency_key = $1
              AND command_type = $2
              AND request_hash = $3
              AND completed_at IS NULL
            """,
            idempotency_key,
            command_type,
            request_hash,
            json.dumps(result, separators=(",", ":")),
            occurred_at,
        )
        if updated != "UPDATE 1":
            raise RuntimeError("Der Finanz-Befehlsnachweis blieb unvollständig.")

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        request_id: str,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type,
                entity_type, entity_id, request_id, payload, occurred_at
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
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )

    @staticmethod
    async def _get_payment(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        payment_id: UUID,
        replayed: bool,
    ) -> PaymentRecord:
        row = await connection.fetchrow(
            """
            SELECT
                payment.*,
                invoice.action_id,
                account.display_name AS recorded_by_display_name
            FROM payment_record AS payment
            JOIN invoice ON invoice.id = payment.invoice_id
            JOIN user_account AS account
              ON account.id = payment.recorded_by_user_id
            WHERE payment.id = $1
              AND invoice.action_id = $2
            """,
            payment_id,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "invoice_payment_not_found",
                "Der Zahlungseingang wurde nicht gefunden.",
            )
        return PaymentRecord(
            id=row["id"],
            action_id=row["action_id"],
            invoice_id=row["invoice_id"],
            amount=Money(int(row["amount_minor"]), str(row["currency"])),
            received_on=row["received_on"],
            reference=str(row["reference"]),
            recorded_by_user_id=row["recorded_by_user_id"],
            recorded_at=row["created_at"],
            recorded_by_display_name=str(row["recorded_by_display_name"]),
            replayed=replayed,
        )

    @staticmethod
    async def _get_cancellation(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        cancellation_id: UUID,
        replayed: bool,
    ) -> InvoiceCancellation:
        row = await connection.fetchrow(
            """
            SELECT
                cancellation.*,
                account.display_name AS requested_by_display_name
            FROM invoice_cancellation AS cancellation
            JOIN user_account AS account
              ON account.id = cancellation.requested_by_user_id
            WHERE cancellation.id = $1
              AND cancellation.action_id = $2
            """,
            cancellation_id,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "invoice_cancellation_not_found",
                "Das Storno wurde nicht gefunden.",
            )
        return InvoiceCancellation(
            id=row["id"],
            action_id=row["action_id"],
            invoice_id=row["invoice_id"],
            original_status=InvoiceStatus(str(row["original_status"])),
            reason=str(row["reason_snapshot"]),
            requested_by_user_id=row["requested_by_user_id"],
            requested_at=row["requested_at"],
            requested_by_display_name=str(row["requested_by_display_name"]),
            replayed=replayed,
        )
