"""Manager cancellation of an order that is not delivered yet.

The same people who manage the action's orders may cancel them (no new role).
The command is idempotent per key and guarded by the order's optimistic
version, the one the delivery completion uses: a stale view answers 409.

In one transaction the order becomes ``cancelled``, leaves the delivery board,
an open "Nachliefern" task closes, and an issued, unpaid invoice is cancelled
under ADR-0009. The invoice part changes a financial record, so it needs a
confirmed fresh login, like the invoice journal's own cancellation. The buyer
gets a cancellation notice when ``order_mails.mail_not_due_reason`` says so:
always for an order of the public form, for an order a member entered only
while the action has ``internal_order_mails`` on.
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
from leonaid.domain.commitments import Commitment
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.order_cancellation import (
    OrderCancellation,
    normalize_note,
    normalize_reason,
)

VERSION_PATTERN = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class OrderCancellationRequest:
    expected_version: str
    reason: str
    note: str | None = None
    # Also mail the cancellation invoice of the order's invoice to the
    # invoice recipient ("Stornorechnung gleich senden").
    send_invoice_cancellation: bool = False
    # Also cancel the unpaid donation that came with the order ("Spende
    # ebenfalls stornieren", on by default). A paid donation always stays.
    cancel_donation: bool = True

    def __post_init__(self) -> None:
        if not VERSION_PATTERN.fullmatch(self.expected_version):
            raise DomainInvariantError(
                "commitment_cancellation_version_invalid",
                "Bitte die Bestellung neu laden.",
            )
        object.__setattr__(self, "reason", normalize_reason(self.reason))
        object.__setattr__(self, "note", normalize_note(self.note))

    def fingerprint(
        self, *, action_id: UUID, commitment_id: UUID, actor_user_id: UUID
    ) -> str:
        payload: dict[str, object] = {
            "actionId": str(action_id),
            "commitmentId": str(commitment_id),
            "actorUserId": str(actor_user_id),
            "expectedVersion": self.expected_version,
            "reason": self.reason,
            "note": self.note,
        }
        # Only present when set: commands keep the fingerprint they had.
        if self.send_invoice_cancellation:
            payload["sendInvoiceCancellation"] = True
        if not self.cancel_donation:
            payload["keepDonation"] = True
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OrderCancellationResult:
    commitment: Commitment
    cancellation: OrderCancellation
    replayed: bool = False


class OrderCancellationRepository(Protocol):
    async def cancel(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        request: OrderCancellationRequest,
        fresh_login: bool,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
        mail_links: OrderMailLinks | None = None,
    ) -> OrderCancellationResult: ...


class OrderCancellationService:
    def __init__(
        self,
        repository: OrderCancellationRepository,
        *,
        mail_links: OrderMailLinkResolver | None = None,
    ) -> None:
        self._repository = repository
        # Without a resolver no cancellation notice is queued.
        self._mail_links = mail_links

    async def cancel(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        commitment_id: UUID,
        *,
        request: OrderCancellationRequest,
        fresh_login: bool,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> OrderCancellationResult:
        require_action_manager(
            actor,
            action_id,
            code="commitment_cancellation_manager_required",
            message="Nur die Aktionsverwaltung darf Bestellungen stornieren.",
        )
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "commitment_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        # Resolved before the cancellation transaction holds a connection.
        mail_links = (
            await self._mail_links.for_action(action_id)
            if self._mail_links is not None
            else None
        )
        return await self._repository.cancel(
            action_id=action_id,
            commitment_id=commitment_id,
            actor_user_id=actor.account.id,
            request=request,
            fresh_login=fresh_login,
            idempotency_key=idempotency_key,
            request_hash=request.fingerprint(
                action_id=action_id,
                commitment_id=commitment_id,
                actor_user_id=actor.account.id,
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            mail_links=mail_links,
        )
