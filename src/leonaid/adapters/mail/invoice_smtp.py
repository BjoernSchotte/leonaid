"""SMTP handler for immutable invoice PDF delivery jobs."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from email.message import EmailMessage
from uuid import UUID

from leonaid.adapters.mail.smtp import SmtpMailHandler
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.application.invoice_deliveries import (
    INVOICE_MAIL_SEND_REQUESTED,
    InvoiceDeliveryWorkerRepository,
)
from leonaid.application.object_storage import ObjectLocation, ObjectStorage
from leonaid.domain.outbox import ClaimedOutboxEvent


class InvoiceSmtpHandler:
    def __init__(
        self,
        *,
        repository: InvoiceDeliveryWorkerRepository,
        storage: ObjectStorage,
        transport: SmtpTransport,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._transport = transport

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        if event.event_type != INVOICE_MAIL_SEND_REQUESTED:
            raise ValueError("Der Rechnungs-Mail-Handler erhielt ein fremdes Ereignis.")
        raw_delivery_id = event.payload.get("deliveryId")
        try:
            delivery_id = UUID(str(raw_delivery_id))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Der Rechnungsversand besitzt keine Versand-ID."
            ) from error
        if delivery_id != event.aggregate_id:
            raise ValueError(
                "Versand-ID und fachlicher Outbox-Bezug stimmen nicht überein."
            )
        if await self._repository.was_sent(event.idempotency_key):
            return
        job = await self._repository.job(delivery_id)
        if job is None:
            raise RuntimeError("Der Rechnungsversand wurde nicht gefunden.")

        retrieved = await self._storage.get(
            ObjectLocation(
                bucket=job.storage_bucket,
                key=job.object_key,
                version_id=job.storage_version_id,
            )
        )
        if (
            retrieved.stored.sha256 != job.sha256
            or retrieved.stored.size_bytes != job.size_bytes
            or retrieved.stored.media_type != job.media_type
            or len(retrieved.content) != job.size_bytes
        ):
            raise RuntimeError(
                "Das Rechnungs-PDF verletzt vor dem Versand seine "
                "gespeicherte Integrität."
            )

        message_id = SmtpMailHandler.message_id(event.idempotency_key)
        message = EmailMessage()
        message["From"] = self._transport.sender
        message["To"] = job.recipient_email
        message["Subject"] = job.subject
        message["Message-ID"] = message_id
        message["X-LeonAid-Delivery-ID"] = str(job.delivery_id)
        message.set_content(job.text)
        maintype, subtype = job.media_type.split("/", maxsplit=1)
        message.add_attachment(
            retrieved.content,
            maintype=maintype,
            subtype=subtype,
            filename=job.filename,
        )
        await asyncio.to_thread(self._send, message)

        await self._repository.mark_sent(
            delivery_id=job.delivery_id,
            outbox_event_id=event.id,
            idempotency_key=event.idempotency_key,
            message_id=message_id,
            recipient_sha256=hashlib.sha256(
                job.recipient_email.casefold().encode("utf-8")
            ).hexdigest(),
            sent_at=datetime.now(timezone.utc),
        )

    def _send(self, message: EmailMessage) -> None:
        self._transport.send(message)
