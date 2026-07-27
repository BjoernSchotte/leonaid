"""PostgreSQL adapter for durable invoice delivery and SMTP projections."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.invoice_deliveries import (
    INVOICE_MAIL_SEND_REQUESTED,
    InvoiceDelivery,
    InvoiceDeliveryContext,
    InvoiceDeliveryDraft,
    InvoiceDeliveryJob,
    InvoiceDeliveryStatus,
)

COMMAND_TYPE = "send_invoice_v1"
MAIL_DELIVERY_NAMESPACE = UUID("8a30d44c-d313-4cc6-af6a-237af95a4d4c")


class AsyncpgInvoiceDeliveryRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def context(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
    ) -> InvoiceDeliveryContext:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT
                    invoice.id,
                    invoice.action_id,
                    invoice.number,
                    invoice.status,
                    invoice.recipient_snapshot ->> 'recipientName'
                        AS recipient_name,
                    invoice.recipient_snapshot ->> 'email'
                        AS recipient_email,
                    invoice.issuer_snapshot ->> 'legalName' AS issuer_name,
                    invoice.gross_minor,
                    invoice.currency,
                    invoice.due_on,
                    invoice.payment_reference,
                    action.name AS action_name,
                    document.id AS document_id
                FROM invoice
                JOIN charity_action AS action ON action.id = invoice.action_id
                LEFT JOIN LATERAL (
                    SELECT id
                    FROM generated_document
                    WHERE generated_document.invoice_id = invoice.id
                      AND generated_document.action_id = invoice.action_id
                      AND generated_document.document_type = 'invoice_pdf'
                      AND generated_document.status = 'available'
                    ORDER BY generated_document.version DESC
                    LIMIT 1
                ) AS document ON true
                WHERE invoice.id = $1
                  AND invoice.action_id = $2
                """,
                invoice_id,
                action_id,
            )
        if row is None:
            raise ResourceNotFound(
                "invoice_delivery_invoice_not_found",
                "Die Rechnung wurde in dieser Charity-Aktion nicht gefunden.",
            )
        if str(row["status"]) == "cancelled":
            raise Conflict(
                "invoice_delivery_cancelled",
                "Eine stornierte Rechnung kann nicht versendet werden.",
            )
        if row["document_id"] is None:
            raise Conflict(
                "invoice_delivery_document_not_ready",
                "Das Rechnungs-PDF ist noch nicht versandbereit.",
            )
        recipient_email = str(row["recipient_email"] or "").strip().casefold()
        if not recipient_email:
            raise Conflict(
                "invoice_delivery_recipient_missing",
                "Für diese Rechnung ist keine Empfänger-E-Mail gespeichert.",
            )
        return InvoiceDeliveryContext(
            action_id=row["action_id"],
            action_name=str(row["action_name"]),
            invoice_id=row["id"],
            invoice_number=str(row["number"]),
            document_id=row["document_id"],
            recipient_name=str(row["recipient_name"]),
            recipient_email=recipient_email,
            issuer_name=str(row["issuer_name"]),
            gross_minor=int(row["gross_minor"]),
            currency=str(row["currency"]),
            due_on=row["due_on"],
            payment_reference=str(row["payment_reference"]),
        )

    async def create(
        self,
        draft: InvoiceDeliveryDraft,
        *,
        request_id: str,
    ) -> InvoiceDelivery:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    draft.idempotency_key,
                )
                replayed = await self._existing_command(
                    connection,
                    idempotency_key=draft.idempotency_key,
                    request_hash=draft.request_hash,
                )
                if replayed is not None:
                    return await self._get(connection, replayed)

                current = await connection.fetchrow(
                    """
                    SELECT
                        invoice.status,
                        invoice.recipient_snapshot ->> 'email'
                            AS recipient_email,
                        document.status AS document_status
                    FROM invoice
                    JOIN generated_document AS document
                      ON document.id = $3
                     AND document.invoice_id = invoice.id
                     AND document.action_id = invoice.action_id
                    WHERE invoice.id = $1
                      AND invoice.action_id = $2
                    FOR UPDATE OF invoice, document
                    """,
                    draft.invoice_id,
                    draft.action_id,
                    draft.document_id,
                )
                if current is None:
                    raise ResourceNotFound(
                        "invoice_delivery_context_changed",
                        "Rechnung und Dokument gehören nicht mehr zusammen.",
                    )
                if str(current["status"]) == "cancelled":
                    raise Conflict(
                        "invoice_delivery_cancelled",
                        "Eine stornierte Rechnung kann nicht versendet werden.",
                    )
                if str(current["document_status"]) != "available":
                    raise Conflict(
                        "invoice_delivery_document_not_ready",
                        "Das Rechnungs-PDF ist noch nicht versandbereit.",
                    )
                current_email = str(current["recipient_email"] or "").casefold()
                if current_email != draft.recipient_email:
                    raise Conflict(
                        "invoice_delivery_recipient_changed",
                        "Der Rechnungsempfänger stimmt nicht mehr mit dem "
                        "Versandauftrag überein.",
                    )

                await connection.execute(
                    """
                    INSERT INTO outbox_event (
                        id, aggregate_type, aggregate_id, event_type,
                        idempotency_key, payload, available_at, created_at
                    )
                    VALUES (
                        $1, 'invoice_delivery', $2, $3, $4, $5::jsonb, $6, $6
                    )
                    """,
                    draft.outbox_event_id,
                    draft.id,
                    INVOICE_MAIL_SEND_REQUESTED,
                    f"invoice-delivery:{draft.id}:v1",
                    json.dumps(
                        {"deliveryId": str(draft.id)},
                        separators=(",", ":"),
                    ),
                    draft.requested_at,
                )
                await connection.execute(
                    """
                    INSERT INTO invoice_delivery (
                        id, action_id, invoice_id, generated_document_id,
                        outbox_event_id, idempotency_key,
                        recipient_email_snapshot, subject_snapshot,
                        text_snapshot, requested_by_user_id,
                        requested_at, created_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11
                    )
                    """,
                    draft.id,
                    draft.action_id,
                    draft.invoice_id,
                    draft.document_id,
                    draft.outbox_event_id,
                    draft.idempotency_key,
                    draft.recipient_email,
                    draft.subject,
                    draft.text,
                    draft.requested_by_user_id,
                    draft.requested_at,
                )
                await self._audit(
                    connection,
                    action_id=draft.action_id,
                    actor_user_id=draft.requested_by_user_id,
                    event_type="invoice.delivery.requested",
                    entity_id=draft.id,
                    request_id=request_id,
                    payload={
                        "invoiceId": str(draft.invoice_id),
                        "documentId": str(draft.document_id),
                    },
                    occurred_at=draft.requested_at,
                )
                await self._complete_command(
                    connection,
                    delivery_id=draft.id,
                    idempotency_key=draft.idempotency_key,
                    request_hash=draft.request_hash,
                    completed_at=draft.requested_at,
                )
                return await self._get(connection, draft.id)

    async def retry(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        delivery_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceDelivery:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT
                        delivery.outbox_event_id,
                        event.status,
                        mail.sent_at
                    FROM invoice_delivery AS delivery
                    JOIN outbox_event AS event
                      ON event.id = delivery.outbox_event_id
                    LEFT JOIN mail_delivery AS mail
                      ON mail.outbox_event_id = event.id
                    WHERE delivery.id = $1
                      AND delivery.action_id = $2
                      AND delivery.invoice_id = $3
                    FOR UPDATE OF delivery, event
                    """,
                    delivery_id,
                    action_id,
                    invoice_id,
                )
                if row is None:
                    raise ResourceNotFound(
                        "invoice_delivery_not_found",
                        "Der Rechnungsversand wurde nicht gefunden.",
                    )
                if row["sent_at"] is not None:
                    raise Conflict(
                        "invoice_delivery_already_sent",
                        "Dieser Versand wurde bereits bestätigt und wird nicht "
                        "noch einmal zugestellt.",
                    )
                if str(row["status"]) != "dead_letter":
                    raise Conflict(
                        "invoice_delivery_not_retryable",
                        "Nur ein endgültig fehlgeschlagener Versand kann "
                        "manuell neu gestartet werden.",
                    )
                updated = await connection.execute(
                    """
                    UPDATE outbox_event
                    SET status = 'pending',
                        available_at = $2,
                        dead_lettered_at = NULL,
                        claim_token = NULL,
                        claimed_by = NULL,
                        completed_at = NULL,
                        manual_retry_count = manual_retry_count + 1,
                        last_manual_retry_at = $2,
                        last_manual_retry_by = $3
                    WHERE id = $1
                      AND status = 'dead_letter'
                    """,
                    row["outbox_event_id"],
                    occurred_at,
                    str(actor_user_id),
                )
                if updated != "UPDATE 1":
                    raise Conflict(
                        "invoice_delivery_retry_raced",
                        "Der Versandstatus wurde gleichzeitig geändert. Bitte "
                        "lade die Rechnung neu.",
                    )
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="invoice.delivery.retried",
                    entity_id=delivery_id,
                    request_id=request_id,
                    payload={"invoiceId": str(invoice_id)},
                    occurred_at=occurred_at,
                )
                return await self._get(connection, delivery_id)

    async def job(self, delivery_id: UUID) -> InvoiceDeliveryJob | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT
                    delivery.id AS delivery_id,
                    delivery.action_id,
                    delivery.invoice_id,
                    delivery.generated_document_id AS document_id,
                    delivery.recipient_email_snapshot,
                    delivery.subject_snapshot,
                    delivery.text_snapshot,
                    document.filename,
                    document.storage_bucket,
                    document.object_key,
                    document.storage_version_id,
                    document.media_type,
                    document.size_bytes,
                    document.sha256,
                    document.status AS document_status
                FROM invoice_delivery AS delivery
                JOIN generated_document AS document
                  ON document.id = delivery.generated_document_id
                WHERE delivery.id = $1
                """,
                delivery_id,
            )
        if row is None:
            return None
        if str(row["document_status"]) != "available":
            raise RuntimeError("Das Rechnungs-PDF ist nicht mehr versandbereit.")
        required = (
            "filename",
            "storage_bucket",
            "object_key",
            "storage_version_id",
            "media_type",
            "size_bytes",
            "sha256",
        )
        if any(row[field] is None for field in required):
            raise RuntimeError(
                "Das Rechnungs-PDF besitzt keinen vollständigen Speicherbezug."
            )
        return InvoiceDeliveryJob(
            delivery_id=row["delivery_id"],
            action_id=row["action_id"],
            invoice_id=row["invoice_id"],
            document_id=row["document_id"],
            recipient_email=str(row["recipient_email_snapshot"]),
            subject=str(row["subject_snapshot"]),
            text=str(row["text_snapshot"]),
            filename=str(row["filename"]),
            storage_bucket=str(row["storage_bucket"]),
            object_key=str(row["object_key"]),
            storage_version_id=str(row["storage_version_id"]),
            media_type=str(row["media_type"]),
            size_bytes=int(row["size_bytes"]),
            sha256=str(row["sha256"]),
        )

    async def was_sent(self, idempotency_key: str) -> bool:
        async with self._pool.acquire() as connection:
            return bool(
                await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM mail_delivery
                        WHERE idempotency_key = $1
                          AND status = 'sent'
                    )
                    """,
                    idempotency_key,
                )
            )

    async def mark_sent(
        self,
        *,
        delivery_id: UUID,
        outbox_event_id: UUID,
        idempotency_key: str,
        message_id: str,
        recipient_sha256: str,
        sent_at: datetime,
    ) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                delivery = await connection.fetchrow(
                    """
                    SELECT action_id, invoice_id, generated_document_id
                    FROM invoice_delivery
                    WHERE id = $1
                      AND outbox_event_id = $2
                    FOR UPDATE
                    """,
                    delivery_id,
                    outbox_event_id,
                )
                if delivery is None:
                    raise RuntimeError(
                        "Der bestätigte SMTP-Versand besitzt keinen Auftrag."
                    )
                inserted = await connection.fetchval(
                    """
                    INSERT INTO mail_delivery (
                        id, outbox_event_id, idempotency_key, message_id,
                        recipient_sha256, status, sent_at
                    )
                    VALUES ($1, $2, $3, $4, $5, 'sent', $6)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING true
                    """,
                    uuid5(MAIL_DELIVERY_NAMESPACE, idempotency_key),
                    outbox_event_id,
                    idempotency_key,
                    message_id,
                    recipient_sha256,
                    sent_at,
                )
                if inserted is not True:
                    existing = await connection.fetchrow(
                        """
                        SELECT outbox_event_id, message_id, recipient_sha256
                        FROM mail_delivery
                        WHERE idempotency_key = $1
                        """,
                        idempotency_key,
                    )
                    if (
                        existing is None
                        or existing["outbox_event_id"] != outbox_event_id
                        or str(existing["message_id"]) != message_id
                        or str(existing["recipient_sha256"]) != recipient_sha256
                    ):
                        raise RuntimeError(
                            "Der SMTP-Zustellnachweis ist widersprüchlich."
                        )
                    return
                await connection.execute(
                    """
                    UPDATE invoice
                    SET status = 'sent'
                    WHERE id = $1
                      AND status = 'issued'
                    """,
                    delivery["invoice_id"],
                )
                await connection.execute(
                    """
                    UPDATE generated_document
                    SET sent_at = $2,
                        updated_at = $2
                    WHERE id = $1
                      AND sent_at IS NULL
                    """,
                    delivery["generated_document_id"],
                    sent_at,
                )
                await self._audit(
                    connection,
                    action_id=delivery["action_id"],
                    actor_user_id=None,
                    event_type="invoice.delivery.sent",
                    entity_id=delivery_id,
                    request_id=f"invoice-delivery:{delivery_id}",
                    payload={
                        "invoiceId": str(delivery["invoice_id"]),
                        "messageId": message_id,
                    },
                    occurred_at=sent_at,
                )

    @staticmethod
    async def _existing_command(
        connection: asyncpg.Connection[Any],
        *,
        idempotency_key: str,
        request_hash: str,
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
            COMMAND_TYPE,
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
            raise RuntimeError("Der Versand-Befehlsnachweis ist verschwunden.")
        if (
            str(row["command_type"]) != COMMAND_TYPE
            or str(row["request_hash"]) != request_hash
        ):
            raise Conflict(
                "idempotency_conflict",
                "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
            )
        result = row["result"]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict) or result.get("deliveryId") is None:
            raise RuntimeError("Der Versand-Befehlsnachweis ist unvollständig.")
        return UUID(str(result["deliveryId"]))

    @staticmethod
    async def _complete_command(
        connection: asyncpg.Connection[Any],
        *,
        delivery_id: UUID,
        idempotency_key: str,
        request_hash: str,
        completed_at: datetime,
    ) -> None:
        updated = await connection.execute(
            """
            UPDATE command_receipt
            SET result = $2::jsonb,
                completed_at = $3
            WHERE idempotency_key = $1
              AND command_type = $4
              AND request_hash = $5
              AND result IS NULL
            """,
            idempotency_key,
            json.dumps({"deliveryId": str(delivery_id)}, separators=(",", ":")),
            completed_at,
            COMMAND_TYPE,
            request_hash,
        )
        if updated != "UPDATE 1":
            raise RuntimeError("Der Versand-Befehlsnachweis wurde nicht abgeschlossen.")

    @classmethod
    async def _get(
        cls,
        connection: asyncpg.Connection[Any],
        delivery_id: UUID,
    ) -> InvoiceDelivery:
        row = await connection.fetchrow(
            """
            SELECT
                delivery.*,
                event.status AS outbox_status,
                event.attempts,
                event.last_error_code,
                event.last_error_detail,
                mail.message_id,
                mail.sent_at
            FROM invoice_delivery AS delivery
            JOIN outbox_event AS event
              ON event.id = delivery.outbox_event_id
            LEFT JOIN mail_delivery AS mail
              ON mail.outbox_event_id = event.id
            WHERE delivery.id = $1
            """,
            delivery_id,
        )
        if row is None:
            raise RuntimeError("Der Rechnungsversand ist nicht mehr vorhanden.")
        return cls._delivery(row)

    @classmethod
    def deliveries_from_rows(
        cls,
        rows: tuple[asyncpg.Record, ...],
    ) -> tuple[InvoiceDelivery, ...]:
        return tuple(cls._delivery(row) for row in rows)

    @staticmethod
    def _delivery(row: asyncpg.Record) -> InvoiceDelivery:
        sent_at = row["sent_at"]
        outbox_status = str(row["outbox_status"])
        attempts = int(row["attempts"])
        if sent_at is not None:
            status = InvoiceDeliveryStatus.SENT
        elif outbox_status == "dead_letter":
            status = InvoiceDeliveryStatus.FAILED
        elif outbox_status == "processing":
            status = InvoiceDeliveryStatus.SENDING
        elif attempts > 0:
            status = InvoiceDeliveryStatus.RETRYING
        else:
            status = InvoiceDeliveryStatus.QUEUED
        return InvoiceDelivery(
            id=row["id"],
            action_id=row["action_id"],
            invoice_id=row["invoice_id"],
            generated_document_id=row["generated_document_id"],
            recipient_email=str(row["recipient_email_snapshot"]),
            subject=str(row["subject_snapshot"]),
            status=status,
            message_id=(
                str(row["message_id"]) if row["message_id"] is not None else None
            ),
            attempts=attempts,
            last_error_code=(
                str(row["last_error_code"])
                if row["last_error_code"] is not None
                else None
            ),
            last_error_detail=(
                str(row["last_error_detail"])
                if row["last_error_detail"] is not None
                else None
            ),
            requested_at=row["requested_at"],
            sent_at=sent_at,
            can_retry=outbox_status == "dead_letter" and sent_at is None,
        )

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID | None,
        event_type: str,
        entity_id: UUID,
        request_id: str,
        payload: dict[str, str],
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type,
                entity_id, request_id, payload, occurred_at
            )
            VALUES (
                gen_random_uuid(), $1, $2, $3, 'invoice_delivery',
                $4, $5, $6::jsonb, $7
            )
            """,
            action_id,
            actor_user_id,
            event_type,
            entity_id,
            request_id,
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )
