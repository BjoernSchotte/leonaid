"""Manager completion of delivery and billing details on unconfirmed orders.

Orders captured before delivery planning was enabled, or drafts saved without
delivery details, must be completed before an invoice can be issued. Only
action managers may do this. The command never changes buyer, lines or prices,
keeps an already booked delivery window immutable and is guarded by an
optimistic version of exactly the fields it may change.

Unlike order capture, a manager may select a window that has already started
(retired or not) to record when the order was actually delivered; the audit
event marks such completions as historical.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.commitments import IDEMPOTENCY_KEY
from leonaid.application.order_mails import OrderMailLinkResolver, OrderMailLinks
from leonaid.application.policies import require_action_manager
from leonaid.domain.commitments import (
    Commitment,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.delivery import DeliveryContactSnapshot
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal

VERSION_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def delivery_completion_version(order: Commitment) -> str:
    """Optimistic version of the status and every field the completion may change."""
    return _hash(
        {
            "id": str(order.id),
            "status": order.status.value,
            "deliveryRecipient": order.delivery_recipient.payload()
            if order.delivery_recipient
            else None,
            "invoiceRecipient": order.invoice_recipient.payload()
            if order.invoice_recipient
            else None,
            "deliveryWindowId": str(order.delivery_window_id)
            if order.delivery_window_id
            else None,
            "deliveryWindowSnapshot": order.delivery_window_snapshot,
            "deliveryContact": order.delivery_contact.payload()
            if order.delivery_contact
            else None,
        }
    )


@dataclass(frozen=True, slots=True)
class DeliveryCompletionDraft:
    expected_version: str
    invoice_recipient: InvoiceRecipientSnapshot
    delivery_recipient: DeliveryRecipientSnapshot | None = None
    delivery_window_id: UUID | None = None
    delivery_contact: DeliveryContactSnapshot | None = None
    # Confirms booking a window marked "ausgebucht". Not order content, so
    # it stays out of the request hash: a refused attempt stores nothing and
    # the confirmed resend may reuse its idempotency key.
    allow_full_window: bool = False

    def __post_init__(self) -> None:
        if not VERSION_PATTERN.fullmatch(self.expected_version):
            raise DomainInvariantError(
                "delivery_completion_version_invalid",
                "Bitte die Bestellung neu laden.",
            )
        if self.delivery_contact is not None and self.delivery_contact.empty:
            object.__setattr__(self, "delivery_contact", None)

    def fingerprint(
        self, *, action_id: UUID, commitment_id: UUID, actor_user_id: UUID
    ) -> str:
        return _hash(
            {
                "actionId": str(action_id),
                "commitmentId": str(commitment_id),
                "actorUserId": str(actor_user_id),
                "expectedVersion": self.expected_version,
                "invoiceRecipient": self.invoice_recipient.payload(),
                "deliveryRecipient": self.delivery_recipient.payload()
                if self.delivery_recipient
                else None,
                "deliveryWindowId": str(self.delivery_window_id)
                if self.delivery_window_id
                else None,
                "deliveryContact": self.delivery_contact.payload()
                if self.delivery_contact
                else None,
            }
        )


class DeliveryCompletionRepository(Protocol):
    async def complete_delivery(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        draft: DeliveryCompletionDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
        mail_links: OrderMailLinks | None = None,
    ) -> Commitment: ...


class DeliveryCompletionService:
    def __init__(
        self,
        repository: DeliveryCompletionRepository,
        *,
        mail_links: OrderMailLinkResolver | None = None,
    ) -> None:
        self._repository = repository
        # Without a resolver a completed draft queues no order confirmation.
        self._mail_links = mail_links

    async def complete(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        commitment_id: UUID,
        *,
        draft: DeliveryCompletionDraft,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> Commitment:
        require_action_manager(
            actor,
            action_id,
            code="delivery_completion_manager_required",
            message="Nur die Aktionsverwaltung darf Liefer- und Rechnungsangaben ergänzen.",
        )
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "commitment_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        return await self._repository.complete_delivery(
            action_id=action_id,
            commitment_id=commitment_id,
            actor_user_id=actor.account.id,
            draft=draft,
            idempotency_key=idempotency_key,
            request_hash=draft.fingerprint(
                action_id=action_id,
                commitment_id=commitment_id,
                actor_user_id=actor.account.id,
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            # Resolved before the transaction holds a connection.
            mail_links=(
                await self._mail_links.for_action(action_id)
                if self._mail_links is not None
                else None
            ),
        )
