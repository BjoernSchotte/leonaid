"""Invoice query and issue use cases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import PermissionDenied
from leonaid.application.invoice_deliveries import InvoiceDelivery
from leonaid.application.invoice_settlements import may_manage_invoice_settlements
from leonaid.application.policies import require_action_manager
from leonaid.domain.commitments import Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import ActionRole, GlobalRole, IdentityPrincipal
from leonaid.domain.invoice_settlements import (
    InvoiceCancellation,
    PaymentRecord,
)
from leonaid.domain.invoices import Invoice, InvoiceProfile
from leonaid.domain.policies import may_manage_action

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


@dataclass(frozen=True, slots=True)
class InvoiceContext:
    action_id: UUID
    action_name: str
    starts_on: date
    ends_on: date
    profile: InvoiceProfile | None
    may_issue: bool
    may_manage_settlements: bool


@dataclass(frozen=True, slots=True)
class InvoiceRecord:
    invoice: Invoice
    buyer_display_name: str
    open_amount: Money
    payment: PaymentRecord | None = None
    cancellation: InvoiceCancellation | None = None
    deliveries: tuple[InvoiceDelivery, ...] = ()


@dataclass(frozen=True, slots=True)
class InvoiceCurrencyTotal:
    currency: str
    gross_total: Money
    open_total: Money


@dataclass(frozen=True, slots=True)
class InvoiceList:
    action_id: UUID
    records: tuple[InvoiceRecord, ...]
    currency_totals: tuple[InvoiceCurrencyTotal, ...]


class InvoiceRepository(Protocol):
    async def context(
        self,
        *,
        action_id: UUID,
    ) -> InvoiceContext: ...

    async def list_for_action(
        self,
        *,
        action_id: UUID,
    ) -> tuple[InvoiceRecord, ...]: ...

    async def issue(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        service_on: date,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Invoice: ...


def may_read_invoices(actor: IdentityPrincipal, action_id: UUID) -> bool:
    if not actor.account.can_authenticate:
        return False
    return (
        may_manage_action(actor, action_id)
        or GlobalRole.FINANCE_READER in actor.global_roles
        or GlobalRole.FINANCE_MANAGER in actor.global_roles
        or ActionRole.FINANCE_READER in actor.roles_for(action_id)
    )


class InvoiceService:
    def __init__(self, repository: InvoiceRepository) -> None:
        self._repository = repository

    @staticmethod
    def _require_read(actor: IdentityPrincipal, action_id: UUID) -> None:
        if may_read_invoices(actor, action_id):
            return
        raise PermissionDenied(
            "invoice_read_required",
            "Du darfst die Rechnungen dieser Charity-Aktion nicht einsehen.",
        )

    async def context(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> InvoiceContext:
        self._require_read(actor, action_id)
        context = await self._repository.context(action_id=action_id)
        return InvoiceContext(
            action_id=context.action_id,
            action_name=context.action_name,
            starts_on=context.starts_on,
            ends_on=context.ends_on,
            profile=context.profile,
            may_issue=may_manage_action(actor, action_id),
            may_manage_settlements=may_manage_invoice_settlements(actor, action_id),
        )

    async def list_for_action(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> InvoiceList:
        self._require_read(actor, action_id)
        records = await self._repository.list_for_action(action_id=action_id)
        gross_totals: dict[str, Money] = {}
        open_totals: dict[str, Money] = {}
        for record in records:
            total = record.invoice.gross
            gross_totals[total.currency] = gross_totals.get(
                total.currency,
                Money(0, total.currency),
            ).plus(total)
            open_totals[total.currency] = open_totals.get(
                total.currency,
                Money(0, total.currency),
            ).plus(record.open_amount)
        return InvoiceList(
            action_id=action_id,
            records=records,
            currency_totals=tuple(
                InvoiceCurrencyTotal(
                    currency=currency,
                    gross_total=gross_totals[currency],
                    open_total=open_totals[currency],
                )
                for currency in sorted(gross_totals)
            ),
        )

    async def issue(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        commitment_id: UUID,
        *,
        service_on: date,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> Invoice:
        require_action_manager(
            actor,
            action_id,
            code="invoice_issue_required",
            message=(
                "Nur ein verantwortlicher Charity-Admin darf eine Rechnung "
                "dieser Aktion freigeben."
            ),
        )
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "invoice_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "actionId": str(action_id),
                    "commitmentId": str(commitment_id),
                    "serviceOn": service_on.isoformat(),
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return await self._repository.issue(
            action_id=action_id,
            commitment_id=commitment_id,
            service_on=service_on,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
