"""Transactional PostgreSQL adapter for payments, reversals and cancellations."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.invoice_cancellation_rows import cancellation_from_row
from leonaid.adapters.postgres.invoice_cancellation_documents import (
    document_columns,
    prepare_cancellation_document,
    request_cancellation_render,
)
from leonaid.adapters.postgres.invoice_deliveries import (
    AsyncpgInvoiceDeliveryRepository,
)
from leonaid.adapters.postgres.invoice_payment_state import ACTIVE_PAID_MINOR_SQL
from leonaid.adapters.postgres.invoice_payments import (
    payment_by_id,
    payment_by_reversal_id,
    payments_for_invoice,
)
from leonaid.adapters.postgres.retry import (
    RETRYABLE_ERRORS,
    SERIALIZABLE_ATTEMPTS,
    serialization_pause,
)
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.invoice_deliveries import cancellation_delivery_draft
from leonaid.application.invoice_settlements import InvoiceSettlementRepository
from leonaid.domain.commitments import Money
from leonaid.domain.invoice_settlements import (
    InvoiceBalance,
    InvoiceCancellation,
    InvoiceSettlementState,
    PaymentRecord,
    PaymentReversal,
    settlement_version,
)
from leonaid.domain.invoices import InvoiceStatus

PAYMENT_COMMAND = "record_invoice_payment_v1"
REVERSAL_COMMAND = "reverse_invoice_payment_v1"
CANCELLATION_COMMAND = "cancel_invoice_v1"
CANCELLATION_DOCUMENT_COMMAND = "issue_invoice_cancellation_document_v1"


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
        note: str | None,
        expected_version: int | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentRecord:
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._record_payment_once(
                            connection,
                            action_id=action_id,
                            invoice_id=invoice_id,
                            amount=amount,
                            received_on=received_on,
                            reference=reference,
                            note=note,
                            expected_version=expected_version,
                            actor_user_id=actor_user_id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except RETRYABLE_ERRORS:
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise Conflict(
                            "invoice_payment_concurrent_retry",
                            "Der Zahlungseingang wurde gleichzeitig bearbeitet. "
                            "Bitte denselben Vorgang erneut ausführen.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Zahlungstransaktion wurde nicht ausgeführt.")

    async def reverse_payment(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        payment_id: UUID,
        reason: str,
        expected_version: int | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentReversal:
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._reverse_payment_once(
                            connection,
                            action_id=action_id,
                            invoice_id=invoice_id,
                            payment_id=payment_id,
                            reason=reason,
                            expected_version=expected_version,
                            actor_user_id=actor_user_id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except RETRYABLE_ERRORS:
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise Conflict(
                            "invoice_payment_concurrent_retry",
                            "Der Zahlungseingang wurde gleichzeitig bearbeitet. "
                            "Bitte denselben Vorgang erneut ausführen.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Rückbuchung wurde nicht ausgeführt.")

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
        send_document: bool = False,
    ) -> InvoiceCancellation:
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
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
                            send_document=send_document,
                        )
                except RETRYABLE_ERRORS:
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise Conflict(
                            "invoice_cancellation_concurrent_retry",
                            "Das Storno wurde gleichzeitig bearbeitet. "
                            "Bitte denselben Vorgang erneut ausführen.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Stornotransaktion wurde nicht ausgeführt.")

    async def issue_cancellation_document(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceCancellation:
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._issue_document_once(
                            connection,
                            action_id=action_id,
                            invoice_id=invoice_id,
                            actor_user_id=actor_user_id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except RETRYABLE_ERRORS:
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise Conflict(
                            "invoice_cancellation_concurrent_retry",
                            "Das Storno wurde gleichzeitig bearbeitet. "
                            "Bitte denselben Vorgang erneut ausführen.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Stornorechnung wurde nicht ausgestellt.")

    async def settle_refund(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        settled_on: date,
        note: str | None,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceCancellation:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._lock_invoice(connection, invoice_id)
                row = await connection.fetchrow(
                    """
                    SELECT cancellation.id
                    FROM invoice_cancellation AS cancellation
                    WHERE cancellation.invoice_id = $1
                      AND cancellation.action_id = $2
                    FOR UPDATE
                    """,
                    invoice_id,
                    action_id,
                )
                if row is None:
                    raise ResourceNotFound(
                        "invoice_cancellation_not_found",
                        "Für diese Rechnung ist kein Storno erfasst.",
                    )
                cancellation = await self._get_cancellation(
                    connection,
                    action_id=action_id,
                    cancellation_id=row["id"],
                    replayed=False,
                )
                if cancellation.refund is not None:
                    raise Conflict(
                        "invoice_refund_already_settled",
                        "Die Erstattung ist bereits als erledigt vermerkt.",
                    )
                if not cancellation.refund_open:
                    raise Conflict(
                        "invoice_refund_not_due",
                        "Für diese Rechnung ist kein Zahlungseingang erfasst; "
                        "es gibt nichts zu erstatten.",
                    )
                refund = cancellation.settle_refund(
                    settled_on=settled_on,
                    note=note,
                    settled_by_user_id=actor_user_id,
                    settled_at=occurred_at,
                )
                await connection.execute(
                    """
                    UPDATE invoice_cancellation
                    SET refund_settled_on = $2,
                        refund_note = $3,
                        refund_settled_by_user_id = $4,
                        refund_settled_at = $5
                    WHERE id = $1
                    """,
                    cancellation.id,
                    refund.settled_on,
                    refund.note,
                    refund.settled_by_user_id,
                    refund.settled_at,
                )
                # The note stays out of the audit trail, as payment notes do.
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="invoice_refund_settled",
                    entity_type="invoice_cancellation",
                    entity_id=cancellation.id,
                    request_id=request_id,
                    payload={
                        "invoiceId": str(invoice_id),
                        "cancellationNumber": cancellation.number,
                        "settledOn": refund.settled_on.isoformat(),
                        "receivedMinor": (
                            cancellation.received.amount_minor
                            if cancellation.received is not None
                            else 0
                        ),
                        "hasNote": refund.note is not None,
                    },
                    occurred_at=occurred_at,
                )
                return await self._get_cancellation(
                    connection,
                    action_id=action_id,
                    cancellation_id=cancellation.id,
                    replayed=False,
                )

    @staticmethod
    async def _lock_invoice(
        connection: asyncpg.Connection[Any],
        invoice_id: UUID,
    ) -> None:
        """Payment lock, then cancellation lock (lock order in ``retry.py``).

        A cancellation reads what was received; no payment may move then.
        """

        for key in (
            f"invoice-payment:{invoice_id}",
            f"invoice-cancellation:{invoice_id}",
        ):
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", key
            )

    async def _issue_document_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        invoice_id: UUID,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceCancellation:
        """The cancellation invoice of a cancellation that has none yet."""

        await self._lock_invoice(connection, invoice_id)
        replayed_id = await self._existing_command(
            connection,
            command_type=CANCELLATION_DOCUMENT_COMMAND,
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
        await self._invoice_state(
            connection,
            action_id=action_id,
            invoice_id=invoice_id,
        )
        row = await connection.fetchrow(
            """
            SELECT id, number
            FROM invoice_cancellation
            WHERE invoice_id = $1 AND action_id = $2
            FOR UPDATE
            """,
            invoice_id,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "invoice_cancellation_not_found",
                "Für diese Rechnung ist kein Storno erfasst.",
            )
        if row["number"] is not None:
            raise Conflict(
                "invoice_cancellation_document_exists",
                "Für dieses Storno gibt es bereits eine Stornorechnung.",
            )
        document = await prepare_cancellation_document(
            connection,
            cancellation_id=row["id"],
            action_id=action_id,
            invoice_id=invoice_id,
            occurred_at=occurred_at,
        )
        number, issued_on, issued_at, snapshot, version = document_columns(document)
        updated = await connection.execute(
            """
            UPDATE invoice_cancellation
            SET number = $2,
                issued_on = $3,
                issued_at = $4,
                issued_by_user_id = $5,
                snapshot = $6::jsonb,
                document_version = $7
            WHERE id = $1
              AND number IS NULL
            """,
            row["id"],
            number,
            issued_on,
            issued_at,
            actor_user_id,
            snapshot,
            version,
        )
        if updated != "UPDATE 1":
            raise RuntimeError("Das gesperrte Storno hat sich verändert.")
        await request_cancellation_render(
            connection,
            document=document,
            action_id=action_id,
            occurred_at=occurred_at,
        )
        await self._audit(
            connection,
            action_id=action_id,
            actor_user_id=actor_user_id,
            event_type="invoice_cancellation_document_issued",
            entity_type="invoice_cancellation",
            entity_id=row["id"],
            request_id=request_id,
            payload={
                "invoiceId": str(invoice_id),
                "invoiceNumber": document.original_number,
                "cancellationNumber": document.number,
                "issuedOn": document.issued_on.isoformat(),
                "receivedMinor": document.received.amount_minor,
            },
            occurred_at=occurred_at,
        )
        await self._complete_command(
            connection,
            command_type=CANCELLATION_DOCUMENT_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"cancellationId": str(row["id"])},
            occurred_at=occurred_at,
        )
        return await self._get_cancellation(
            connection,
            action_id=action_id,
            cancellation_id=row["id"],
            replayed=False,
        )

    async def _record_payment_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        invoice_id: UUID,
        amount: Money,
        received_on: date,
        reference: str,
        note: str | None,
        expected_version: int | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentRecord:
        await self._lock_payments(connection, invoice_id)
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
        if invoice.status is InvoiceStatus.CANCELLED:
            raise Conflict(
                "invoice_payment_cancelled",
                "Für eine stornierte Rechnung kann keine Zahlung erfasst werden.",
            )
        payments = await payments_for_invoice(connection, invoice_id)
        self._require_version(payments, expected_version)

        payment = PaymentRecord.record(
            id=uuid4(),
            invoice=invoice,
            amount=amount,
            received_on=received_on,
            reference=reference,
            recorded_by_user_id=actor_user_id,
            recorded_at=occurred_at,
            note=note,
        )
        await connection.execute(
            """
            INSERT INTO payment_record (
                id, invoice_id, amount_minor, currency, received_on,
                recorded_by_user_id, reference, note, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            payment.id,
            payment.invoice_id,
            payment.amount.amount_minor,
            payment.amount.currency,
            payment.received_on,
            payment.recorded_by_user_id,
            payment.reference,
            payment.note,
            payment.recorded_at,
        )
        balance = InvoiceBalance.of(invoice.gross, (*payments, payment))
        status = await self._settle_status(
            connection,
            invoice=invoice,
            balance=balance,
            occurred_at=occurred_at,
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
                "hasNote": payment.note is not None,
                "previousStatus": invoice.status.value,
                "status": status.value,
                **self._balance_payload(balance),
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

    async def _reverse_payment_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        invoice_id: UUID,
        payment_id: UUID,
        reason: str,
        expected_version: int | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentReversal:
        await self._lock_payments(connection, invoice_id)
        replayed_id = await self._existing_command(
            connection,
            command_type=REVERSAL_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result_key="reversalId",
        )
        if replayed_id is not None:
            return await self._get_reversal(
                connection,
                action_id=action_id,
                reversal_id=replayed_id,
                replayed=True,
            )

        invoice = await self._invoice_state(
            connection,
            action_id=action_id,
            invoice_id=invoice_id,
        )
        if invoice.status is InvoiceStatus.CANCELLED:
            # A cancelled invoice is closed: its payment history stays as is.
            raise Conflict(
                "invoice_payment_cancelled",
                "Bei einer stornierten Rechnung kann keine Zahlung "
                "zurückgebucht werden.",
            )
        payments = await payments_for_invoice(connection, invoice_id)
        payment = next((item for item in payments if item.id == payment_id), None)
        if payment is None:
            raise ResourceNotFound(
                "invoice_payment_not_found",
                "Der Zahlungseingang wurde bei dieser Rechnung nicht gefunden.",
            )
        if not payment.active:
            raise Conflict(
                "invoice_payment_already_reversed",
                "Dieser Zahlungseingang ist bereits zurückgebucht.",
            )
        self._require_version(payments, expected_version)

        reversal = payment.reverse(
            id=uuid4(),
            reason=reason,
            reversed_by_user_id=actor_user_id,
            reversed_at=occurred_at,
        )
        await connection.execute(
            """
            INSERT INTO payment_reversal (
                id, payment_id, invoice_id, reason_snapshot,
                reversed_by_user_id, reversed_at, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $6)
            """,
            reversal.id,
            reversal.payment_id,
            reversal.invoice_id,
            reversal.reason,
            reversal.reversed_by_user_id,
            reversal.reversed_at,
        )
        balance = InvoiceBalance.of(
            invoice.gross,
            (
                replace(item, reversal=reversal) if item.id == payment_id else item
                for item in payments
            ),
        )
        status = await self._settle_status(
            connection,
            invoice=invoice,
            balance=balance,
            occurred_at=occurred_at,
        )
        await self._audit(
            connection,
            action_id=action_id,
            actor_user_id=actor_user_id,
            event_type="invoice_payment_reversed",
            entity_type="payment_reversal",
            entity_id=reversal.id,
            request_id=request_id,
            payload={
                "invoiceId": str(invoice_id),
                "invoiceNumber": invoice.number,
                "paymentId": str(payment_id),
                "amountMinor": payment.amount.amount_minor,
                "currency": payment.amount.currency,
                "receivedOn": payment.received_on.isoformat(),
                "reason": reversal.reason,
                "previousStatus": invoice.status.value,
                "status": status.value,
                **self._balance_payload(balance),
            },
            occurred_at=occurred_at,
        )
        await self._complete_command(
            connection,
            command_type=REVERSAL_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            result={"reversalId": str(reversal.id)},
            occurred_at=occurred_at,
        )
        return await self._get_reversal(
            connection,
            action_id=action_id,
            reversal_id=reversal.id,
            replayed=False,
        )

    @staticmethod
    async def _lock_payments(
        connection: asyncpg.Connection[Any],
        invoice_id: UUID,
    ) -> None:
        # Payments and reversals of one invoice run strictly one after another.
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"invoice-payment:{invoice_id}",
        )

    @staticmethod
    def _require_version(
        payments: tuple[PaymentRecord, ...],
        expected_version: int | None,
    ) -> None:
        if expected_version is None:
            return
        if settlement_version(payments) != expected_version:
            raise Conflict(
                "invoice_settlement_stale",
                "Die Zahlungen dieser Rechnung wurden inzwischen geändert. "
                "Laden Sie die Rechnung neu und prüfen Sie den offenen Betrag.",
            )

    @staticmethod
    def _balance_payload(balance: InvoiceBalance) -> dict[str, object]:
        return {
            "paidMinor": balance.paid.amount_minor,
            "openMinor": balance.open_amount.amount_minor,
            "overpaidMinor": balance.overpaid_amount.amount_minor,
            "settlementStatus": balance.status.value,
        }

    @staticmethod
    async def _settle_status(
        connection: asyncpg.Connection[Any],
        *,
        invoice: InvoiceSettlementState,
        balance: InvoiceBalance,
        occurred_at: datetime,
    ) -> InvoiceStatus:
        """Stores the invoice status that follows from the new balance."""

        if invoice.status is InvoiceStatus.CANCELLED:
            return invoice.status
        # A sent invoice stays sent; a paid one was sent when the mail
        # server confirmed one of its deliveries.
        delivered = invoice.status is InvoiceStatus.SENT or bool(
            await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM invoice_delivery AS delivery
                    JOIN mail_delivery AS mail
                      ON mail.outbox_event_id = delivery.outbox_event_id
                    WHERE delivery.invoice_id = $1
                      AND mail.status = 'sent'
                )
                """,
                invoice.id,
            )
        )
        target = balance.invoice_status(delivered=delivered)
        updated = await connection.execute(
            """
            UPDATE invoice
            SET status = $2,
                updated_at = $3
            WHERE id = $1
              AND status = $4
            """,
            invoice.id,
            target.value,
            occurred_at,
            invoice.status.value,
        )
        if updated != "UPDATE 1":
            raise Conflict(
                "invoice_payment_state_changed",
                "Der Rechnungsstatus hat sich gleichzeitig geändert. Bitte den Beleg neu laden.",
            )
        return target

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
        send_document: bool = False,
    ) -> InvoiceCancellation:
        """Cancels the invoice and issues its cancellation invoice.

        One transaction: the status, the cancellation record, the number of
        the invoice series, the document snapshot, its render job and, when
        asked for, the delivery. ``cancelCommitment`` runs it inside its own.
        """

        await self._lock_invoice(connection, invoice_id)
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
        document = await prepare_cancellation_document(
            connection,
            cancellation_id=cancellation.id,
            action_id=action_id,
            invoice_id=invoice_id,
            occurred_at=occurred_at,
        )
        number, issued_on, issued_at, snapshot, version = document_columns(document)
        await connection.execute(
            """
            INSERT INTO invoice_cancellation (
                id, action_id, invoice_id, original_status,
                reason_snapshot, requested_by_user_id, idempotency_key,
                requested_at, created_at, number, issued_on, issued_at,
                issued_by_user_id, snapshot, document_version
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, $9, $10, $11, $6,
                    $12::jsonb, $13)
            """,
            cancellation.id,
            cancellation.action_id,
            cancellation.invoice_id,
            cancellation.original_status.value,
            cancellation.reason,
            cancellation.requested_by_user_id,
            idempotency_key,
            cancellation.requested_at,
            number,
            issued_on,
            issued_at,
            snapshot,
            version,
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
                "Der Rechnungsstatus hat sich gleichzeitig geändert. Bitte den Beleg neu laden.",
            )
        await request_cancellation_render(
            connection,
            document=document,
            action_id=action_id,
            occurred_at=occurred_at,
        )
        if send_document:
            # The PDF is not rendered yet; the mail job waits for it.
            deliveries = AsyncpgInvoiceDeliveryRepository(self._pool)
            await deliveries.create_in(
                connection,
                cancellation_delivery_draft(
                    await deliveries.read_cancellation_context(
                        connection,
                        action_id=action_id,
                        invoice_id=invoice_id,
                        document_may_be_pending=True,
                    ),
                    idempotency_key=f"invoice-cancellation-delivery:{cancellation.id}",
                    requested_by_user_id=actor_user_id,
                    requested_at=occurred_at,
                    document_may_be_pending=True,
                ),
                request_id=request_id,
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
                "cancellationNumber": document.number,
                "issuedOn": document.issued_on.isoformat(),
                "receivedMinor": document.received.amount_minor,
                "documentSent": send_document,
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
                id, action_id, number, status, issued_at, issued_on,
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
            issued_on=row["issued_on"],
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
        payment = await payment_by_id(
            connection,
            action_id=action_id,
            payment_id=payment_id,
            replayed=replayed,
        )
        if payment is None:
            raise ResourceNotFound(
                "invoice_payment_not_found",
                "Der Zahlungseingang wurde nicht gefunden.",
            )
        return payment

    @staticmethod
    async def _get_reversal(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        reversal_id: UUID,
        replayed: bool,
    ) -> PaymentReversal:
        payment = await payment_by_reversal_id(
            connection,
            action_id=action_id,
            reversal_id=reversal_id,
        )
        if payment is None or payment.reversal is None:
            raise ResourceNotFound(
                "invoice_payment_reversal_not_found",
                "Die Rückbuchung wurde nicht gefunden.",
            )
        return replace(payment.reversal, replayed=replayed)

    @staticmethod
    async def _get_cancellation(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        cancellation_id: UUID,
        replayed: bool,
    ) -> InvoiceCancellation:
        row = await connection.fetchrow(
            f"""
            SELECT
                cancellation.*,
                account.display_name AS requested_by_display_name,
                refund_account.display_name AS refund_settled_by_display_name,
                invoice.currency AS invoice_currency,
                {ACTIVE_PAID_MINOR_SQL} AS received_minor
            FROM invoice_cancellation AS cancellation
            JOIN invoice ON invoice.id = cancellation.invoice_id
            JOIN user_account AS account
              ON account.id = cancellation.requested_by_user_id
            LEFT JOIN user_account AS refund_account
              ON refund_account.id = cancellation.refund_settled_by_user_id
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
        return cancellation_from_row(
            row,
            requested_by_display_name=str(row["requested_by_display_name"]),
            received=Money(int(row["received_minor"]), str(row["invoice_currency"])),
            replayed=replayed,
        )
