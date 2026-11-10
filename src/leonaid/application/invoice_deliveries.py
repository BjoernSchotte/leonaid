"""Durable invoice delivery commands and observable delivery state."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from leonaid.application.outbox import OutboxDeferred
from leonaid.application.policies import require_action_manager
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal

INVOICE_MAIL_SEND_REQUESTED = "invoice.mail.send.requested.v1"
INVOICE_DELIVERY_NAMESPACE = UUID("86073cf3-9228-41d4-831c-fef7d3baefb8")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
# How long a mail job waits before it looks for its PDF again.
DOCUMENT_WAIT = timedelta(seconds=5)


class InvoiceDeliveryKind(StrEnum):
    """Which document of an invoice a delivery carries."""

    INVOICE = "invoice"
    INVOICE_CANCELLATION = "invoice_cancellation"
    # A delivery of a donation's pledge; it belongs to a donation, not to
    # an invoice (application/donations.py).
    DONATION_PLEDGE = "donation_pledge"
    # A delivery of a donation receipt (application/donation_receipts.py).
    DONATION_RECEIPT = "donation_receipt"


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
    invoice_id: UUID | None
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
    kind: InvoiceDeliveryKind = InvoiceDeliveryKind.INVOICE
    donation_id: UUID | None = None


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
class InvoiceCancellationDeliveryContext:
    action_id: UUID
    action_name: str
    invoice_id: UUID
    invoice_number: str
    cancellation_number: str
    document_id: UUID
    recipient_name: str
    recipient_email: str
    issuer_name: str
    # What had been received for the invoice when it was cancelled.
    received_minor: int
    currency: str


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
    kind: InvoiceDeliveryKind = InvoiceDeliveryKind.INVOICE
    # A cancellation invoice sent with the cancel command is still being
    # rendered: the mail job waits for the PDF.
    document_may_be_pending: bool = False


@dataclass(frozen=True, slots=True)
class InvoiceDeliveryJob:
    delivery_id: UUID
    action_id: UUID
    invoice_id: UUID | None
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


class InvoiceDeliveryDocumentPending(OutboxDeferred):
    """The mail's PDF is still being rendered: the mail job waits for it."""

    def __init__(self) -> None:
        super().__init__("invoice_delivery_document_pending", DOCUMENT_WAIT)


class InvoiceDeliveryDocumentFailed(RuntimeError):
    """The PDF of the mail will not come: its render job failed for good.

    Not retryable: the delivery shows as failed at once. After the render
    job is repaired, the delivery is started again by hand.
    """

    code = "invoice_delivery_document_failed"
    retryable = False


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

    async def cancellation_context(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
    ) -> InvoiceCancellationDeliveryContext: ...

    async def retry(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        delivery_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        kind: InvoiceDeliveryKind = InvoiceDeliveryKind.INVOICE,
    ) -> InvoiceDelivery: ...


def format_money(amount_minor: int, currency: str) -> str:
    whole, fraction = divmod(amount_minor, 100)
    grouped = f"{whole:,}".replace(",", ".")
    symbol = "€" if currency == "EUR" else currency
    return f"{grouped},{fraction:02d} {symbol}"


def delivery_request_hash(
    action_id: UUID, invoice_id: UUID, kind: InvoiceDeliveryKind
) -> str:
    payload = {"actionId": str(action_id), "invoiceId": str(invoice_id)}
    # Invoice deliveries keep the hash they had before a second kind existed.
    if kind is not InvoiceDeliveryKind.INVOICE:
        payload["kind"] = kind.value
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def cancellation_delivery_draft(
    context: InvoiceCancellationDeliveryContext,
    *,
    idempotency_key: str,
    requested_by_user_id: UUID,
    requested_at: datetime,
    document_may_be_pending: bool = False,
) -> InvoiceDeliveryDraft:
    """The cover mail of a cancellation invoice (spec Appendix A.2)."""

    delivery_id = uuid4()
    if context.received_minor > 0:
        closing = (
            f"Auf die Rechnung {context.invoice_number} haben wir "
            f"{format_money(context.received_minor, context.currency)} erhalten. "
            "Die Erstattung erfolgt gesondert."
        )
    else:
        closing = (
            f"Aus der Rechnung {context.invoice_number} ist kein Betrag mehr zu zahlen."
        )
    return InvoiceDeliveryDraft(
        id=delivery_id,
        action_id=context.action_id,
        invoice_id=context.invoice_id,
        document_id=context.document_id,
        outbox_event_id=uuid5(INVOICE_DELIVERY_NAMESPACE, str(delivery_id)),
        idempotency_key=idempotency_key,
        request_hash=delivery_request_hash(
            context.action_id,
            context.invoice_id,
            InvoiceDeliveryKind.INVOICE_CANCELLATION,
        ),
        recipient_email=context.recipient_email,
        subject=(
            f"Stornorechnung {context.cancellation_number} zur Rechnung "
            f"{context.invoice_number} · {context.action_name}"
        ),
        text=(
            f"Guten Tag {context.recipient_name},\n\n"
            f"anbei erhalten Sie die Stornorechnung zu Ihrer Rechnung "
            f"{context.invoice_number}. Die Rechnung ist damit aufgehoben.\n\n"
            f"{closing}\n\n"
            "Bei Fragen zu dieser Stornorechnung antworten Sie bitte auf "
            "diese E-Mail.\n\n"
            "Freundliche Grüße\n"
            f"{context.issuer_name}"
        ),
        requested_by_user_id=requested_by_user_id,
        requested_at=requested_at,
        kind=InvoiceDeliveryKind.INVOICE_CANCELLATION,
        document_may_be_pending=document_may_be_pending,
    )


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
        request_hash = delivery_request_hash(
            action_id, invoice_id, InvoiceDeliveryKind.INVOICE
        )
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

    async def send_cancellation(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        invoice_id: UUID,
        *,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> InvoiceDelivery:
        """Sends the cancellation invoice to the invoice's recipient."""

        require_action_manager(
            actor,
            action_id,
            code="invoice_delivery_required",
            message=(
                "Nur ein verantwortlicher Charity-Admin darf eine "
                "Stornorechnung dieser Aktion versenden."
            ),
        )
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "invoice_delivery_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        context = await self._repository.cancellation_context(
            action_id=action_id,
            invoice_id=invoice_id,
        )
        return await self._repository.create(
            cancellation_delivery_draft(
                context,
                idempotency_key=idempotency_key,
                requested_by_user_id=actor.account.id,
                requested_at=occurred_at or datetime.now(timezone.utc),
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
        kind: InvoiceDeliveryKind = InvoiceDeliveryKind.INVOICE,
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
            kind=kind,
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
            "Bei Fragen zu dieser Rechnung antworten Sie bitte auf "
            "diese E-Mail.\n\n"
            "Vielen Dank für Ihre Unterstützung.\n\n"
            "Freundliche Grüße\n"
            f"{context.issuer_name}"
        )

    @staticmethod
    def _format_money(amount_minor: int, currency: str) -> str:
        return format_money(amount_minor, currency)
