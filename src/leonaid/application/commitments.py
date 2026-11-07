"""Commitment creation use cases with server-authoritative pricing."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import PermissionDenied
from leonaid.application.policies import require_action_manager
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.captures import bounded_captured_at
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
    Money,
    Offering,
    UnitQuantity,
)
from leonaid.domain.delivery import DeliveryContactSnapshot, DeliveryConfiguration
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.order_cancellation import OrderCancellation, OrderInvoiceState
from leonaid.domain.policies import may_manage_action

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


@dataclass(frozen=True, slots=True)
class CommitmentLineDraft:
    offering_id: UUID
    quantity: int
    unit: OfferingUnit
    quoted_unit_price_minor: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.quantity, bool) or self.quantity <= 0:
            raise DomainInvariantError(
                "commitment_line_quantity_invalid",
                "Die Bestellmenge muss positiv sein.",
            )
        if self.quoted_unit_price_minor is not None and (
            isinstance(self.quoted_unit_price_minor, bool)
            or self.quoted_unit_price_minor < 0
        ):
            raise DomainInvariantError(
                "commitment_client_quote_invalid",
                "Ein angezeigter Clientpreis darf nicht negativ sein.",
            )


@dataclass(frozen=True, slots=True)
class CommitmentDraft:
    buyer: BuyerSnapshot
    invoice_recipient: InvoiceRecipientSnapshot | None
    lines: tuple[CommitmentLineDraft, ...]
    delivery_recipient: DeliveryRecipientSnapshot | None = None
    message: str | None = None

    delivery_window_id: UUID | None = None
    delivery_contact: DeliveryContactSnapshot | None = None
    # Confirms booking a window marked "ausgebucht". Not order content, so
    # it stays out of the request hash: a refused attempt stores nothing and
    # the confirmed resend may reuse its idempotency key.
    allow_full_window: bool = False
    # Set by the PWA offline queue (PLAN §11.2/§11.3): when the order was
    # saved on the device. It switches on the price guard, so each line then
    # needs the price the acquirer saw.
    captured_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.delivery_contact is not None and self.delivery_contact.empty:
            object.__setattr__(self, "delivery_contact", None)
        if self.captured_at is not None and any(
            line.quoted_unit_price_minor is None for line in self.lines
        ):
            raise DomainInvariantError(
                "commitment_client_quote_required",
                "Eine nachgereichte Bestellung benötigt je Position den "
                "angezeigten Preis.",
            )
        if not self.lines:
            raise DomainInvariantError(
                "commitment_lines_required",
                "Eine Bestellung benötigt mindestens eine Position.",
            )
        offering_ids = [line.offering_id for line in self.lines]
        if len(offering_ids) != len(set(offering_ids)):
            raise DomainInvariantError(
                "commitment_offering_duplicate",
                "Ein Angebot darf nur einmal je Bestellung vorkommen.",
            )

    def fingerprint(
        self,
        *,
        action_id: UUID,
        source: CommitmentSource,
        status: CommitmentStatus,
    ) -> str:
        payload: dict[str, object] = {
            "actionId": str(action_id),
            "source": source.value,
            "status": status.value,
            "buyer": self.buyer.payload(),
            "invoiceRecipient": (
                self.invoice_recipient.payload()
                if self.invoice_recipient is not None
                else None
            ),
            "deliveryRecipient": (
                self.delivery_recipient.payload()
                if self.delivery_recipient is not None
                else None
            ),
            "message": self.message,
            # The non-binding client price is deliberately not part of the
            # domain command. Only offering ID, quantity and unit drive the
            # server-side calculation.
            "lines": [
                {
                    "offeringId": str(line.offering_id),
                    "quantity": line.quantity,
                    "unit": line.unit.value,
                }
                for line in self.lines
            ],
        }
        # Omit absent new fields to retain the exact pre-upgrade request hash.
        if self.delivery_window_id is not None:
            payload["deliveryWindowId"] = str(self.delivery_window_id)
        if self.delivery_contact is not None:
            payload["deliveryContact"] = self.delivery_contact.payload()
        if self.captured_at is not None:
            # A queued order is bound to the price it was captured with: a
            # confirmed new price is new content and needs a new key.
            payload["capturedAt"] = self.captured_at.astimezone(
                timezone.utc
            ).isoformat()
            payload["quotedUnitPricesMinor"] = {
                str(line.offering_id): line.quoted_unit_price_minor
                for line in self.lines
            }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CommitmentCaptureContext:
    action_id: UUID
    action_name: str
    offerings: tuple[Offering, ...]
    delivery_configuration: DeliveryConfiguration | None = None


@dataclass(frozen=True, slots=True)
class CommitmentCompletion:
    """Delivery details for the single, irreversible draft-to-review transition."""

    delivery_recipient: DeliveryRecipientSnapshot | None = None
    delivery_window_id: UUID | None = None
    delivery_contact: DeliveryContactSnapshot | None = None
    # Confirms booking a window marked "ausgebucht". Not order content, so
    # it stays out of the request hash: a refused attempt stores nothing and
    # the confirmed resend may reuse its idempotency key.
    allow_full_window: bool = False
    # When the completion was saved on the device (PWA queue); recorded in
    # the audit event, the order keeps the capture time of its creation.
    captured_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.delivery_contact is not None and self.delivery_contact.empty:
            object.__setattr__(self, "delivery_contact", None)

    def fingerprint(
        self, *, action_id: UUID, commitment_id: UUID, actor_user_id: UUID
    ) -> str:
        payload: dict[str, object] = {
            "actionId": str(action_id),
            "commitmentId": str(commitment_id),
            "actorUserId": str(actor_user_id),
            "deliveryRecipient": (
                self.delivery_recipient.payload() if self.delivery_recipient else None
            ),
            "deliveryWindowId": str(self.delivery_window_id)
            if self.delivery_window_id
            else None,
            "deliveryContact": self.delivery_contact.payload()
            if self.delivery_contact
            else None,
        }
        # Omitted when absent to retain the exact pre-upgrade request hash.
        if self.captured_at is not None:
            payload["capturedAt"] = self.captured_at.astimezone(
                timezone.utc
            ).isoformat()
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CommitmentRecord:
    commitment: Commitment
    created_at: datetime
    captured_by_display_name: str | None
    cancellation: OrderCancellation | None = None
    invoice: OrderInvoiceState | None = None
    delivered: bool = False


@dataclass(frozen=True, slots=True)
class CommitmentCurrencyTotal:
    currency: str
    total: Money


@dataclass(frozen=True, slots=True)
class CommitmentList:
    action_id: UUID
    records: tuple[CommitmentRecord, ...]
    currency_totals: tuple[CommitmentCurrencyTotal, ...]
    total_boxes: int
    total_pieces: int
    quantities: tuple[UnitQuantity, ...] = ()


class CommitmentRepository(Protocol):
    async def get_internal(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        as_manager: bool,
    ) -> Commitment: ...

    async def complete_draft(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        as_manager: bool,
        completion: CommitmentCompletion,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Commitment: ...

    async def capture_context(
        self,
        *,
        action_id: UUID,
        evaluated_at: datetime,
    ) -> CommitmentCaptureContext: ...

    async def list_for_action(
        self,
        *,
        action_id: UUID,
    ) -> tuple[CommitmentRecord, ...]: ...

    async def create(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        source: CommitmentSource,
        status: CommitmentStatus,
        draft: CommitmentDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Commitment: ...


class CommitmentService:
    def __init__(self, repository: CommitmentRepository) -> None:
        self._repository = repository

    @staticmethod
    def _require_capture(actor: IdentityPrincipal, action_id: UUID) -> None:
        if not actor.account.can_authenticate or (
            ActionRole.ACQUIRER not in actor.roles_for(action_id)
            and not may_manage_action(actor, action_id)
        ):
            raise PermissionDenied(
                "commitment_capture_required",
                "Für diese Aktion fehlt die Berechtigung, Bestellungen zu erfassen.",
            )

    async def get_internal(
        self, actor: IdentityPrincipal, action_id: UUID, commitment_id: UUID
    ) -> Commitment:
        self._require_capture(actor, action_id)
        return await self._repository.get_internal(
            action_id=action_id,
            commitment_id=commitment_id,
            actor_user_id=actor.account.id,
            as_manager=may_manage_action(actor, action_id),
        )

    async def complete_draft(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        commitment_id: UUID,
        *,
        completion: CommitmentCompletion,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> Commitment:
        self._require_capture(actor, action_id)
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "commitment_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        moment = occurred_at or datetime.now(timezone.utc)
        if completion.captured_at is not None:
            bounded_captured_at(completion.captured_at, received_at=moment)
        return await self._repository.complete_draft(
            action_id=action_id,
            commitment_id=commitment_id,
            actor_user_id=actor.account.id,
            as_manager=may_manage_action(actor, action_id),
            completion=completion,
            idempotency_key=idempotency_key,
            request_hash=completion.fingerprint(
                action_id=action_id,
                commitment_id=commitment_id,
                actor_user_id=actor.account.id,
            ),
            request_id=request_id,
            occurred_at=moment,
        )

    async def capture_context(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        evaluated_at: datetime | None = None,
    ) -> CommitmentCaptureContext:
        self._require_capture(actor, action_id)
        return await self._repository.capture_context(
            action_id=action_id,
            evaluated_at=evaluated_at or datetime.now(timezone.utc),
        )

    async def list_for_action(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> CommitmentList:
        require_action_manager(actor, action_id)
        records = await self._repository.list_for_action(action_id=action_id)
        # Cancelled orders stay in the list but count for nothing.
        counted = tuple(
            record
            for record in records
            if record.commitment.status is not CommitmentStatus.CANCELLED
        )
        totals: dict[str, Money] = {}
        for record in counted:
            total = record.commitment.total
            totals[total.currency] = totals.get(
                total.currency,
                Money(0, total.currency),
            ).plus(total)
        return CommitmentList(
            action_id=action_id,
            records=records,
            currency_totals=tuple(
                CommitmentCurrencyTotal(currency=currency, total=totals[currency])
                for currency in sorted(totals)
            ),
            total_boxes=sum(record.commitment.total_boxes for record in counted),
            total_pieces=sum(record.commitment.total_pieces for record in counted),
            quantities=UnitQuantity.summarize(
                (item.unit, item.quantity)
                for record in counted
                for item in record.commitment.quantities
            ),
        )

    async def create_internal(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        source: CommitmentSource,
        ready_for_review: bool,
        draft: CommitmentDraft,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> Commitment:
        if source is CommitmentSource.PUBLIC_FORM:
            raise PermissionDenied(
                "commitment_source_forbidden",
                "Öffentliche Bestellungen dürfen nur über das öffentliche Formular entstehen.",
            )
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "commitment_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        if source is CommitmentSource.ADMIN:
            require_action_manager(actor, action_id)
        elif (
            not actor.account.can_authenticate
            or ActionRole.ACQUIRER not in actor.roles_for(action_id)
        ):
            raise PermissionDenied(
                "commitment_acquisition_required",
                "Nur zugeordnete Akquisiteure dürfen Akquise-Bestellungen erfassen.",
            )
        status = (
            CommitmentStatus.REVIEW_READY
            if ready_for_review
            else CommitmentStatus.DRAFT
        )
        moment = occurred_at or datetime.now(timezone.utc)
        if draft.captured_at is not None:
            if source is not CommitmentSource.ACQUISITION:
                raise DomainInvariantError(
                    "captured_at_source_invalid",
                    "Nur Akquise-Bestellungen können nachgereicht werden.",
                )
            bounded_captured_at(draft.captured_at, received_at=moment)
        return await self._repository.create(
            action_id=action_id,
            actor_user_id=actor.account.id,
            source=source,
            status=status,
            draft=draft,
            idempotency_key=idempotency_key,
            request_hash=draft.fingerprint(
                action_id=action_id,
                source=source,
                status=status,
            ),
            request_id=request_id,
            occurred_at=moment,
        )
