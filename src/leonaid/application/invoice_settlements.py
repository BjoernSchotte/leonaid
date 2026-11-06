"""Authorized payment, payment-reversal and invoice-cancellation use cases."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import PermissionDenied
from leonaid.domain.commitments import Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import GlobalRole, IdentityPrincipal
from leonaid.domain.invoice_settlements import (
    InvoiceCancellation,
    PaymentRecord,
    PaymentReversal,
)
from leonaid.domain.policies import may_manage_action

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class InvoiceSettlementRepository(Protocol):
    async def record_payment(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        amount: Money,
        received_on: date,
        reference: str,
        note: str | None,
        expected_version: int | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentRecord: ...

    async def reverse_payment(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        payment_id: UUID,
        reason: str,
        expected_version: int | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PaymentReversal: ...

    async def cancel(
        self,
        *,
        action_id: UUID,
        invoice_id: UUID,
        reason: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceCancellation: ...


def may_manage_invoice_settlements(
    actor: IdentityPrincipal,
    action_id: UUID,
) -> bool:
    return actor.account.can_authenticate and (
        may_manage_action(actor, action_id)
        or GlobalRole.FINANCE_MANAGER in actor.global_roles
    )


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None


def _request_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class InvoiceSettlementService:
    def __init__(self, repository: InvoiceSettlementRepository) -> None:
        self._repository = repository

    @staticmethod
    def _require_manage(actor: IdentityPrincipal, action_id: UUID) -> None:
        if may_manage_invoice_settlements(actor, action_id):
            return
        raise PermissionDenied(
            "invoice_settlement_required",
            "Nur ein verantwortlicher Charity-Admin oder eine Person mit "
            "Finanz-Buchungsrecht darf Zahlungen und Stornos erfassen.",
        )

    @staticmethod
    def _validate_idempotency_key(value: str) -> None:
        if not IDEMPOTENCY_KEY.fullmatch(value):
            raise DomainInvariantError(
                "invoice_settlement_idempotency_key_invalid",
                "Die Vorgangs-ID besitzt ein ungültiges Format.",
            )

    async def record_payment(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        invoice_id: UUID,
        *,
        amount_minor: int,
        currency: str,
        received_on: date,
        reference: str,
        idempotency_key: str,
        request_id: str,
        note: str | None = None,
        expected_version: int | None = None,
        occurred_at: datetime | None = None,
    ) -> PaymentRecord:
        self._require_manage(actor, action_id)
        self._validate_idempotency_key(idempotency_key)
        amount = Money(amount_minor, currency)
        normalized_note = _normalized(note)
        payload: dict[str, object] = {
            "actionId": str(action_id),
            "invoiceId": str(invoice_id),
            "amountMinor": amount.amount_minor,
            "currency": amount.currency,
            "receivedOn": received_on.isoformat(),
            "reference": " ".join(reference.split()),
        }
        # Only present when given, so commands without a note keep the hash
        # they had before notes existed. The expected version is a
        # precondition, not command content: a replay ignores it.
        if normalized_note is not None:
            payload["note"] = normalized_note
        return await self._repository.record_payment(
            action_id=action_id,
            invoice_id=invoice_id,
            amount=amount,
            received_on=received_on,
            reference=reference,
            note=normalized_note,
            expected_version=expected_version,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(payload),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def reverse_payment(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        invoice_id: UUID,
        payment_id: UUID,
        *,
        reason: str,
        idempotency_key: str,
        request_id: str,
        expected_version: int | None = None,
        occurred_at: datetime | None = None,
    ) -> PaymentReversal:
        self._require_manage(actor, action_id)
        self._validate_idempotency_key(idempotency_key)
        normalized_reason = " ".join(reason.split())
        return await self._repository.reverse_payment(
            action_id=action_id,
            invoice_id=invoice_id,
            payment_id=payment_id,
            reason=reason,
            expected_version=expected_version,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(
                {
                    "actionId": str(action_id),
                    "invoiceId": str(invoice_id),
                    "paymentId": str(payment_id),
                    "reason": normalized_reason,
                }
            ),
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

    async def cancel(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        invoice_id: UUID,
        *,
        reason: str,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> InvoiceCancellation:
        self._require_manage(actor, action_id)
        self._validate_idempotency_key(idempotency_key)
        normalized_reason = " ".join(reason.split())
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "actionId": str(action_id),
                    "invoiceId": str(invoice_id),
                    "reason": normalized_reason,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return await self._repository.cancel(
            action_id=action_id,
            invoice_id=invoice_id,
            reason=reason,
            actor_user_id=actor.account.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
