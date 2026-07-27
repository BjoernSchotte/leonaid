"""Durable invoice delivery commands and observable delivery state."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from leonaid.application.policies import require_action_manager
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal

INVOICE_MAIL_SEND_REQUESTED = "invoice.mail.send.requested.v1"
INVOICE_DELIVERY_NAMESPACE = UUID("86073cf3-9228-41d4-831c-fef7d3baefb8")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class InvoiceDeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    RETRYING = "retrying"
    FAILED = "failed"
    SENT = "sent"


@dataclass(frozen=True, slots=True)
class InvoiceDelivery:
    id: UUID
    action_id: UUID
    invoice_id: UUID
    generated_document_id: UUID
    recipient_email: str
    subject: str
    status: InvoiceDeliveryStatus
    message_id: str | None
    attempts: int
    last_error_code: str | None
    last_error_detail: str | None
    requested_at: datetime
    sent_at: datetime | None
    can_retry: bool


@dataclass(frozen=True, slots=True)
class InvoiceDeliveryContext:
    action_id: UUID
    action_name: str
    invoice_id: UUID
    invoice_number: str
    document_id: UUID
    recipient_name: str
    recipient_email: str
    issuer_name: str
    gross_minor: int
    currency: str
    due_on: date
    payment_reference: str


@dataclass(frozen=True, slots=True)
class InvoiceDeliveryDraft:
    id: UUID
    action_id: UUID
    invoice_id: UUID
    document_id: UUID
    outbox_event_id: UUID
    idempotency_key: str
    request_hash: str
    recipient_email: str
    subject: str
    text: str
    requested_by_user_id: UUID
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class InvoiceDeliveryJob:
    delivery_id: UUID
    action_id: UUID
    invoice_id: UUID
    document_id: UUID
    recipient_email: str
    subject: str
    text: str
    filename: str
    storage_bucket: str
    object_key: str
    storage_version_id: str
    media_type: str
    size_bytes: int
    sha256: str


class InvoiceDeliveryRepository(Protocol):
    async def context(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
    ) -> InvoiceDeliveryContext: ...

    async def create(
        self,
        draft: InvoiceDeliveryDraft,
        *,
        request_id: str,
    ) -> InvoiceDelivery: ...

    async def retry(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        delivery_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceDelivery: ...


class InvoiceDeliveryWorkerRepository(Protocol):
    async def job(self, delivery_id: UUID) -> InvoiceDeliveryJob | None: ...

    async def was_sent(self, idempotency_key: str) -> bool: ...

    async def mark_sent(
        self,
        *,
        delivery_id: UUID,
        outbox_event_id: UUID,
        idempotency_key: str,
        message_id: str,
        recipient_sha256: str,
        sent_at: datetime,
    ) -> None: ...


class InvoiceDeliveryService:
    def __init__(self, repository: InvoiceDeliveryRepository) -> None:
        self._repository = repository

    async def send(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        invoice_id: UUID,
        *,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> InvoiceDelivery:
        require_action_manager(
            actor,
            action_id,
            code="invoice_delivery_required",
            message=(
                "Nur ein verantwortlicher Charity-Admin darf eine Rechnung "
                "dieser Aktion versenden."
            ),
        )
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "invoice_delivery_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        context = await self._repository.context(
            action_id=action_id,
            invoice_id=invoice_id,
        )
        now = occurred_at or datetime.now(timezone.utc)
        delivery_id = uuid4()
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "actionId": str(action_id),
                    "invoiceId": str(invoice_id),
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return await self._repository.create(
            InvoiceDeliveryDraft(
                id=delivery_id,
                action_id=action_id,
                invoice_id=invoice_id,
                document_id=context.document_id,
                outbox_event_id=uuid5(INVOICE_DELIVERY_NAMESPACE, str(delivery_id)),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                recipient_email=context.recipient_email,
                subject=(f"Rechnung {context.invoice_number} · {context.action_name}"),
                text=self._message_text(context),
                requested_by_user_id=actor.account.id,
                requested_at=now,
            ),
            request_id=request_id,
        )

    async def retry(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        invoice_id: UUID,
        delivery_id: UUID,
        *,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> InvoiceDelivery:
        require_action_manager(
            actor,
            action_id,
            code="invoice_delivery_retry_required",
            message=(
                "Nur ein verantwortlicher Charity-Admin darf einen "
                "fehlgeschlagenen Rechnungsversand neu starten."
            ),
        )
        return await self._repository.retry(
            action_id=action_id,
            invoice_id=invoice_id,
            delivery_id=delivery_id,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    @classmethod
    def _message_text(cls, context: InvoiceDeliveryContext) -> str:
        return (
            f"Guten Tag {context.recipient_name},\n\n"
            f"anbei erhalten Sie die Rechnung {context.invoice_number} "
            f"zur Charity-Aktion „{context.action_name}“.\n\n"
            f"Rechnungsbetrag: "
            f"{cls._format_money(context.gross_minor, context.currency)}\n"
            f"Zahlbar bis: {context.due_on.strftime('%d.%m.%Y')}\n"
            f"Verwendungszweck: {context.payment_reference}\n\n"
            "Vielen Dank für Ihre Unterstützung.\n\n"
            "Freundliche Grüße\n"
            f"{context.issuer_name}"
        )

    @staticmethod
    def _format_money(amount_minor: int, currency: str) -> str:
        whole, fraction = divmod(amount_minor, 100)
        grouped = f"{whole:,}".replace(",", ".")
        symbol = "€" if currency == "EUR" else currency
        return f"{grouped},{fraction:02d} {symbol}"
