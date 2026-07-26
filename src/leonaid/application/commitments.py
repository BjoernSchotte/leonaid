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
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentSource,
    CommitmentStatus,
    InvoiceRecipientSnapshot,
    Money,
    Offering,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import ActionRole, IdentityPrincipal
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

    def __post_init__(self) -> None:
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
        payload = {
            "actionId": str(action_id),
            "source": source.value,
            "status": status.value,
            "buyer": self.buyer.payload(),
            "invoiceRecipient": (
                self.invoice_recipient.payload()
                if self.invoice_recipient is not None
                else None
            ),
            # An unverbindlicher Clientpreis ist absichtlich kein Bestandteil
            # des fachlichen Befehls. Ausschließlich Offering-ID, Menge und
            # Einheit bestimmen die Serverberechnung.
            "lines": [
                {
                    "offeringId": str(line.offering_id),
                    "quantity": line.quantity,
                    "unit": line.unit.value,
                }
                for line in self.lines
            ],
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


@dataclass(frozen=True, slots=True)
class CommitmentRecord:
    commitment: Commitment
    created_at: datetime
    captured_by_display_name: str | None


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


class CommitmentRepository(Protocol):
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

    async def capture_context(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        evaluated_at: datetime | None = None,
    ) -> CommitmentCaptureContext:
        if not actor.account.can_authenticate or (
            ActionRole.ACQUIRER not in actor.roles_for(action_id)
            and not may_manage_action(actor, action_id)
        ):
            raise PermissionDenied(
                "commitment_capture_required",
                "Für diese Aktion darfst du keine Bestellung erfassen.",
            )
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
        totals: dict[str, Money] = {}
        for record in records:
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
            total_boxes=sum(record.commitment.total_boxes for record in records),
            total_pieces=sum(record.commitment.total_pieces for record in records),
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
