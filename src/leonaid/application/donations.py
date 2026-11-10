"""Donation use cases: record, pay, cancel, and send the pledge (ADR-0016).

Rights follow the invoices: whoever reads the invoices of an action reads its
donations; the action's manager or a global finance manager records them,
books the payment and cancels. Recording a donation, taking a payment back
and cancelling need a fresh login (checked at the route); sending the pledge
needs the action's manager, as sending an invoice does.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from leonaid.application.errors import PermissionDenied
from leonaid.application.invoice_deliveries import (
    INVOICE_DELIVERY_NAMESPACE,
    InvoiceDelivery,
    format_money,
)
from leonaid.application.invoice_settlements import may_manage_invoice_settlements
from leonaid.application.invoices import may_read_invoices
from leonaid.application.policies import require_action_manager
from leonaid.application.rendered_documents import (
    DocumentRendering,
    RenderedDocument,
)
from leonaid.domain.commitments import Money
from leonaid.domain.documents import GeneratedDocument
from leonaid.domain.donation_receipts import DonationReceipt
from leonaid.domain.donations import (
    Donation,
    DonationPledgeDocument,
    DonationSource,
    DonorSnapshot,
    ReceiptSigning,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.policies import may_manage_action

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


@dataclass(frozen=True, slots=True)
class DonationReceiptRecord:
    receipt: DonationReceipt
    # The receipt PDF, written in the transaction of the receipt.
    document: GeneratedDocument
    deliveries: tuple[InvoiceDelivery, ...] = ()


@dataclass(frozen=True, slots=True)
class DonationRecord:
    donation: Donation
    # The pledge PDF; None only while its row is missing (never by design).
    # Written in the transaction of the donation: every donation has one.
    pledge_document: GeneratedDocument
    pledge_deliveries: tuple[InvoiceDelivery, ...] = ()
    # Newest first; at most one of them is not void.
    receipts: tuple[DonationReceiptRecord, ...] = ()

    @property
    def valid_receipt(self) -> DonationReceiptRecord | None:
        return next((item for item in self.receipts if item.receipt.valid), None)


@dataclass(frozen=True, slots=True)
class DonationList:
    action_id: UUID
    action_name: str
    records: tuple[DonationRecord, ...]
    # Name of the receiving body of the active legal configuration; None
    # when no body is configured and no donation can be recorded.
    receiving_body_name: str | None
    may_manage: bool
    may_send: bool
    # How the active receiving body signs receipts, and the last day its
    # notice carries one (§ 63 Abs. 5 AO); None without a receiving body.
    receipt_signing: ReceiptSigning | None = None
    receipt_notice_valid_until: date | None = None

    @property
    def received_total(self) -> Money:
        return Money(
            sum(
                record.donation.payment.amount.amount_minor
                for record in self.records
                if record.donation.payment is not None
            ),
            "EUR",
        )

    @property
    def pledged_open_total(self) -> Money:
        return Money(
            sum(
                record.donation.pledged.amount_minor
                for record in self.records
                if record.donation.payment is None
                and record.donation.cancellation is None
            ),
            "EUR",
        )


@dataclass(frozen=True, slots=True)
class DonationDraft:
    donor: DonorSnapshot
    pledged: Money
    note: str | None = None
    source: DonationSource = DonationSource.ADMIN
    commitment_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DonationPledgeDeliveryContext:
    action_id: UUID
    action_name: str
    donation_id: UUID
    number: str
    document_id: UUID
    donor_name: str
    donor_email: str
    body_name: str
    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class DonationPledgeDeliveryDraft:
    id: UUID
    action_id: UUID
    donation_id: UUID
    document_id: UUID
    outbox_event_id: UUID
    idempotency_key: str
    request_hash: str
    recipient_email: str
    subject: str
    text: str
    requested_by_user_id: UUID
    requested_at: datetime


def pledge_delivery_draft(
    context: DonationPledgeDeliveryContext,
    *,
    idempotency_key: str,
    requested_by_user_id: UUID,
    requested_at: datetime,
) -> DonationPledgeDeliveryDraft:
    """The cover mail of a donation pledge; sender is the receiving body."""

    delivery_id = uuid4()
    amount = format_money(context.amount_minor, context.currency)
    return DonationPledgeDeliveryDraft(
        id=delivery_id,
        action_id=context.action_id,
        donation_id=context.donation_id,
        document_id=context.document_id,
        outbox_event_id=uuid5(INVOICE_DELIVERY_NAMESPACE, str(delivery_id)),
        idempotency_key=idempotency_key,
        request_hash=_request_hash(
            {
                "actionId": str(context.action_id),
                "donationId": str(context.donation_id),
                "command": "sendPledge",
            }
        ),
        recipient_email=context.donor_email,
        subject=f"Spendenzusage {context.number} · {context.action_name}",
        text=(
            f"Guten Tag {context.donor_name},\n\n"
            f"vielen Dank für Ihre Spende von {amount} für die Aktion "
            f"„{context.action_name}“. Anbei erhalten Sie Ihre Spendenzusage "
            f"{context.number} mit der Bankverbindung.\n\n"
            f"Bitte geben Sie bei der Überweisung den Verwendungszweck "
            f"{context.number} an. Nach Eingang Ihrer Zahlung erhalten Sie eine "
            "Zuwendungsbestätigung für Ihre Steuererklärung.\n\n"
            "Dieses Schreiben ist keine Rechnung. Bei Fragen antworten Sie "
            "bitte auf diese E-Mail.\n\n"
            "Freundliche Grüße\n"
            f"{context.body_name}"
        ),
        requested_by_user_id=requested_by_user_id,
        requested_at=requested_at,
    )


class DonationRepository(Protocol):
    async def list_for_action(self, *, action_id: UUID) -> DonationList: ...

    async def create(
        self,
        *,
        action_id: UUID,
        draft: DonationDraft,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord: ...

    async def record_payment(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        amount: Money,
        received_on: date,
        note: str | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord: ...

    async def withdraw_payment(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        reason: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord: ...

    async def cancel(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        reason: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord: ...

    async def pledge_delivery_context(
        self, *, action_id: UUID, donation_id: UUID
    ) -> DonationPledgeDeliveryContext: ...

    async def send_pledge(
        self, draft: DonationPledgeDeliveryDraft, *, request_id: str
    ) -> InvoiceDelivery: ...

    async def retry_pledge_delivery(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        delivery_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceDelivery: ...


def _request_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


class DonationService:
    def __init__(self, repository: DonationRepository) -> None:
        self._repository = repository

    @staticmethod
    def _require_read(actor: IdentityPrincipal, action_id: UUID) -> None:
        if may_read_invoices(actor, action_id):
            return
        raise PermissionDenied(
            "donation_read_required",
            "Für die Spenden dieser Charity-Aktion fehlt die Leseberechtigung.",
        )

    @staticmethod
    def _require_manage(actor: IdentityPrincipal, action_id: UUID) -> None:
        if may_manage_invoice_settlements(actor, action_id):
            return
        raise PermissionDenied(
            "donation_manage_required",
            "Nur ein verantwortlicher Charity-Admin oder eine Person mit "
            "Finanz-Buchungsrecht darf Spenden erfassen und buchen.",
        )

    @staticmethod
    def _require_key(value: str) -> None:
        if not IDEMPOTENCY_KEY.fullmatch(value):
            raise DomainInvariantError(
                "donation_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )

    async def list_for_action(
        self, actor: IdentityPrincipal, action_id: UUID
    ) -> DonationList:
        self._require_read(actor, action_id)
        listing = await self._repository.list_for_action(action_id=action_id)
        return DonationList(
            action_id=listing.action_id,
            action_name=listing.action_name,
            records=listing.records,
            receiving_body_name=listing.receiving_body_name,
            may_manage=may_manage_invoice_settlements(actor, action_id),
            may_send=_may_send(actor, action_id),
            receipt_signing=listing.receipt_signing,
            receipt_notice_valid_until=listing.receipt_notice_valid_until,
        )

    async def create(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        draft: DonationDraft,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> DonationRecord:
        self._require_manage(actor, action_id)
        self._require_key(idempotency_key)
        return await self._repository.create(
            action_id=action_id,
            draft=draft,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(
                {
                    "actionId": str(action_id),
                    "donor": draft.donor.payload(),
                    "pledgedMinor": draft.pledged.amount_minor,
                    "currency": draft.pledged.currency,
                    "note": " ".join((draft.note or "").split()) or None,
                    "source": draft.source.value,
                }
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def record_payment(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        *,
        amount_minor: int,
        received_on: date,
        note: str | None,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> DonationRecord:
        self._require_manage(actor, action_id)
        self._require_key(idempotency_key)
        normalized_note = " ".join((note or "").split()) or None
        return await self._repository.record_payment(
            action_id=action_id,
            donation_id=donation_id,
            amount=Money(amount_minor, "EUR"),
            received_on=received_on,
            note=normalized_note,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(
                {
                    "actionId": str(action_id),
                    "donationId": str(donation_id),
                    "command": "recordPayment",
                    "amountMinor": amount_minor,
                    "receivedOn": received_on.isoformat(),
                    "note": normalized_note,
                }
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def withdraw_payment(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        *,
        reason: str,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> DonationRecord:
        self._require_manage(actor, action_id)
        self._require_key(idempotency_key)
        return await self._repository.withdraw_payment(
            action_id=action_id,
            donation_id=donation_id,
            reason=reason,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(
                {
                    "actionId": str(action_id),
                    "donationId": str(donation_id),
                    "command": "withdrawPayment",
                    "reason": " ".join(reason.split()),
                }
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def cancel(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        *,
        reason: str,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> DonationRecord:
        self._require_manage(actor, action_id)
        self._require_key(idempotency_key)
        return await self._repository.cancel(
            action_id=action_id,
            donation_id=donation_id,
            reason=reason,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(
                {
                    "actionId": str(action_id),
                    "donationId": str(donation_id),
                    "command": "cancel",
                    "reason": " ".join(reason.split()),
                }
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def send_pledge(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        *,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> InvoiceDelivery:
        require_action_manager(
            actor,
            action_id,
            code="donation_delivery_required",
            message=(
                "Nur ein verantwortlicher Charity-Admin darf eine Spendenzusage "
                "dieser Aktion versenden."
            ),
        )
        self._require_key(idempotency_key)
        context = await self._repository.pledge_delivery_context(
            action_id=action_id, donation_id=donation_id
        )
        return await self._repository.send_pledge(
            pledge_delivery_draft(
                context,
                idempotency_key=idempotency_key,
                requested_by_user_id=actor.account.id,
                requested_at=occurred_at or datetime.now(timezone.utc),
            ),
            request_id=request_id,
        )

    async def retry_pledge_delivery(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        delivery_id: UUID,
        *,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> InvoiceDelivery:
        require_action_manager(
            actor,
            action_id,
            code="donation_delivery_retry_required",
            message=(
                "Nur ein verantwortlicher Charity-Admin darf einen "
                "fehlgeschlagenen Versand neu starten."
            ),
        )
        return await self._repository.retry_pledge_delivery(
            action_id=action_id,
            donation_id=donation_id,
            delivery_id=delivery_id,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )


def _may_send(actor: IdentityPrincipal, action_id: UUID) -> bool:
    return actor.account.can_authenticate and may_manage_action(actor, action_id)


# --- the pledge PDF ---------------------------------------------------------


class DonationPledgePdfRenderer(Protocol):
    def render(self, document: DonationPledgeDocument) -> RenderedDocument: ...


class DonationPledgeDocumentReader(Protocol):
    async def donation_pledge_document(
        self, donation_id: UUID
    ) -> DonationPledgeDocument | None: ...


class DonationPledgeDocumentSource:
    """The ``donation_pledge_pdf`` document: the stored pledge snapshot."""

    def __init__(
        self,
        *,
        documents: DonationPledgeDocumentReader,
        renderer: DonationPledgePdfRenderer,
    ) -> None:
        self._documents = documents
        self._renderer = renderer

    async def render(self, document: GeneratedDocument) -> DocumentRendering:
        if document.donation_id is None:
            raise RuntimeError("Die Spendenzusage verweist auf keine Spende.")
        snapshot = await self._documents.donation_pledge_document(document.donation_id)
        if snapshot is None:
            raise RuntimeError("Die Spende des Dokuments wurde nicht gefunden.")
        # Typst runs as a blocking subprocess; keep the worker event loop free.
        rendered = await asyncio.to_thread(self._renderer.render, snapshot)
        return DocumentRendering(
            rendered=rendered,
            storage_path=f"donations/{snapshot.donation_id}/pledge",
            metadata={
                "donation-id": str(snapshot.donation_id),
                "donation-number": snapshot.number,
            },
        )
