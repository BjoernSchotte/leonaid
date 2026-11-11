"""Use cases of the donation receipt ("Zuwendungsbestätigung", spec §8.5)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from leonaid.application.donations import IDEMPOTENCY_KEY, DonationRecord
from leonaid.application.errors import PermissionDenied
from leonaid.application.invoice_deliveries import (
    INVOICE_DELIVERY_NAMESPACE,
    InvoiceDelivery,
    format_money,
)
from leonaid.application.invoice_settlements import may_manage_invoice_settlements
from leonaid.application.policies import require_action_manager
from leonaid.application.rendered_documents import DocumentRendering, RenderedDocument
from leonaid.domain.documents import GeneratedDocument
from leonaid.domain.donation_receipts import (
    DonationReceiptDocument,
    ReceiptVoidEvidence,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal


@dataclass(frozen=True, slots=True)
class DonationReceiptDeliveryDraft:
    id: UUID
    action_id: UUID
    donation_id: UUID
    receipt_id: UUID
    outbox_event_id: UUID
    idempotency_key: str
    request_hash: str
    requested_by_user_id: UUID
    requested_at: datetime


def receipt_mail(
    *,
    number: str,
    action_name: str,
    donor_name: str,
    body_name: str,
    amount_minor: int,
    currency: str,
    received_on_label: str,
) -> tuple[str, str]:
    """Subject and text of the cover mail; signed with the receiving body."""

    amount = format_money(amount_minor, currency)
    return (
        f"Zuwendungsbestätigung {number} · {action_name}",
        f"Guten Tag {donor_name},\n\n"
        f"vielen Dank für Ihre Spende von {amount}, die am {received_on_label} "
        f"bei uns eingegangen ist. Anbei erhalten Sie Ihre "
        f"Zuwendungsbestätigung {number} für Ihre Steuererklärung.\n\n"
        "Die Bestätigung wurde maschinell erstellt und ist ohne Unterschrift "
        "gültig. Bitte bewahren Sie sie auf. Bei Fragen antworten Sie bitte "
        "auf diese E-Mail.\n\n"
        "Freundliche Grüße\n"
        f"{body_name}",
    )


def _request_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


class DonationReceiptRepository(Protocol):
    async def issue(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord: ...

    async def void(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        receipt_id: UUID,
        reason: str,
        evidence: ReceiptVoidEvidence,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord: ...

    async def send(
        self, draft: DonationReceiptDeliveryDraft, *, request_id: str
    ) -> InvoiceDelivery: ...


class DonationReceiptService:
    def __init__(self, repository: DonationReceiptRepository) -> None:
        self._repository = repository

    @staticmethod
    def _require_manage(actor: IdentityPrincipal, action_id: UUID) -> None:
        if may_manage_invoice_settlements(actor, action_id):
            return
        raise PermissionDenied(
            "donation_manage_required",
            "Nur ein verantwortlicher Charity-Admin oder eine Person mit "
            "Finanz-Buchungsrecht darf Zuwendungsbestätigungen ausstellen und "
            "für ungültig erklären.",
        )

    @staticmethod
    def _require_key(value: str) -> None:
        if not IDEMPOTENCY_KEY.fullmatch(value):
            raise DomainInvariantError(
                "donation_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )

    async def issue(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        *,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> DonationRecord:
        self._require_manage(actor, action_id)
        self._require_key(idempotency_key)
        return await self._repository.issue(
            action_id=action_id,
            donation_id=donation_id,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(
                {
                    "actionId": str(action_id),
                    "donationId": str(donation_id),
                    "command": "issueReceipt",
                }
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def void(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        receipt_id: UUID,
        *,
        reason: str,
        evidence: ReceiptVoidEvidence,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> DonationRecord:
        self._require_manage(actor, action_id)
        self._require_key(idempotency_key)
        return await self._repository.void(
            action_id=action_id,
            donation_id=donation_id,
            receipt_id=receipt_id,
            reason=reason,
            evidence=evidence,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(
                {
                    "actionId": str(action_id),
                    "donationId": str(donation_id),
                    "receiptId": str(receipt_id),
                    "command": "voidReceipt",
                    "reason": " ".join(reason.split()),
                    "evidence": evidence.value,
                }
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def send(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        donation_id: UUID,
        receipt_id: UUID,
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
                "Nur ein verantwortlicher Charity-Admin darf eine "
                "Zuwendungsbestätigung dieser Aktion versenden."
            ),
        )
        self._require_key(idempotency_key)
        delivery_id = uuid4()
        return await self._repository.send(
            DonationReceiptDeliveryDraft(
                id=delivery_id,
                action_id=action_id,
                donation_id=donation_id,
                receipt_id=receipt_id,
                outbox_event_id=uuid5(INVOICE_DELIVERY_NAMESPACE, str(delivery_id)),
                idempotency_key=idempotency_key,
                request_hash=_request_hash(
                    {
                        "actionId": str(action_id),
                        "donationId": str(donation_id),
                        "receiptId": str(receipt_id),
                        "command": "sendReceipt",
                    }
                ),
                requested_by_user_id=actor.account.id,
                requested_at=occurred_at or datetime.now(timezone.utc),
            ),
            request_id=request_id,
        )


# --- the receipt PDF --------------------------------------------------------


class DonationReceiptPdfRenderer(Protocol):
    def render(self, document: DonationReceiptDocument) -> RenderedDocument: ...


class DonationReceiptDocumentReader(Protocol):
    async def donation_receipt_document(
        self, donation_id: UUID, version: int
    ) -> DonationReceiptDocument | None: ...


class DonationReceiptDocumentSource:
    """The ``donation_receipt_pdf`` document: the stored receipt snapshot.

    A donation can have several receipts over time (one valid, the others
    void); the document's version says which receipt it shows.
    """

    def __init__(
        self,
        *,
        documents: DonationReceiptDocumentReader,
        renderer: DonationReceiptPdfRenderer,
    ) -> None:
        self._documents = documents
        self._renderer = renderer

    async def render(self, document: GeneratedDocument) -> DocumentRendering:
        if document.donation_id is None:
            raise RuntimeError("Die Zuwendungsbestätigung verweist auf keine Spende.")
        snapshot = await self._documents.donation_receipt_document(
            document.donation_id, document.version
        )
        if snapshot is None:
            raise RuntimeError(
                "Die Zuwendungsbestätigung des Dokuments wurde nicht gefunden."
            )
        # Typst runs as a blocking subprocess; keep the worker event loop free.
        rendered = await asyncio.to_thread(self._renderer.render, snapshot)
        return DocumentRendering(
            rendered=rendered,
            storage_path=(
                f"donations/{snapshot.donation_id}/receipts/{snapshot.receipt_id}"
            ),
            metadata={
                "donation-id": str(snapshot.donation_id),
                "donation-receipt-number": snapshot.number,
            },
        )
