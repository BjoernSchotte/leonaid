"""Authorized completion of delivery and billing data on unconfirmed orders."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.commitments import IDEMPOTENCY_KEY
from leonaid.application.policies import require_action_manager
from leonaid.domain.commitments import (
    Commitment,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal


def delivery_completion_version(order: Commitment) -> str:
    """Optimistic comparison of precisely the mutable completion fields."""
    return _hash(
        {
            "id": str(order.id),
            "status": order.status.value,
            "delivery": order.delivery_recipient.payload()
            if order.delivery_recipient
            else None,
            "invoice": order.invoice_recipient.payload()
            if order.invoice_recipient
            else None,
            "windowId": str(order.delivery_window_id)
            if order.delivery_window_id
            else None,
            "window": order.delivery_window_snapshot,
        }
    )


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class DeliveryCompletionDraft:
    expected_version: str
    delivery_recipient: DeliveryRecipientSnapshot
    invoice_recipient: InvoiceRecipientSnapshot
    window_id: UUID | None
    confirm_historical_delivery: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", self.expected_version):
            raise DomainInvariantError(
                "delivery_completion_version_invalid", "Bitte die Bestellung neu laden."
            )

    def fingerprint(self, action_id: UUID, order_id: UUID) -> str:
        return _hash(
            {
                "actionId": str(action_id),
                "orderId": str(order_id),
                "expectedVersion": self.expected_version,
                "delivery": self.delivery_recipient.payload(),
                "invoice": self.invoice_recipient.payload(),
                "windowId": str(self.window_id) if self.window_id else None,
                **(
                    {"confirmHistoricalDelivery": True}
                    if self.confirm_historical_delivery
                    else {}
                ),
            }
        )


class DeliveryCompletionRepository(Protocol):
    async def complete(
        self,
        *,
        action_id: UUID,
        order_id: UUID,
        actor_id: UUID,
        draft: DeliveryCompletionDraft,
        key: str,
        request_id: str,
        now: datetime,
    ) -> Commitment: ...


class DeliveryCompletionService:
    def __init__(self, repository: DeliveryCompletionRepository) -> None:
        self.repository = repository

    async def complete(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        order_id: UUID,
        *,
        draft: DeliveryCompletionDraft,
        key: str,
        request_id: str,
        now: datetime | None = None,
    ) -> Commitment:
        require_action_manager(actor, action_id)
        if not IDEMPOTENCY_KEY.fullmatch(key):
            raise DomainInvariantError(
                "commitment_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        return await self.repository.complete(
            action_id=action_id,
            order_id=order_id,
            actor_id=actor.account.id,
            draft=draft,
            key=key,
            request_id=request_id,
            now=now or datetime.now(timezone.utc),
        )
