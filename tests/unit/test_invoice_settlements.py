from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from leonaid.application.errors import PermissionDenied
from leonaid.application.invoice_settlements import InvoiceSettlementService
from leonaid.domain.commitments import Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.invoice_settlements import (
    InvoiceBalance,
    InvoiceCancellation,
    InvoiceSettlementState,
    PaymentRecord,
    PaymentReversal,
    SettlementStatus,
    settlement_version,
)
from leonaid.domain.invoices import InvoiceStatus

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
INVOICE_ID = UUID("90000000-0000-4000-8000-000000000001")
PAYMENT_ID = UUID("97000000-0000-4000-8000-000000000010")
CANCELLATION_ID = UUID("98000000-0000-4000-8000-000000000010")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
ISSUED_AT = datetime(2026, 6, 30, 14, tzinfo=timezone.utc)
RECORDED_AT = datetime(2026, 7, 12, 9, tzinfo=timezone.utc)
GROSS = Money(36_000, "EUR")


def invoice_state(
    status: InvoiceStatus = InvoiceStatus.SENT,
) -> InvoiceSettlementState:
    return InvoiceSettlementState(
        id=INVOICE_ID,
        action_id=ACTION_ID,
        number="KT26-0001",
        status=status,
        issued_at=ISSUED_AT,
        issued_on=ISSUED_AT.date(),
        gross=GROSS,
    )


def payment(
    amount_minor: int,
    *,
    status: InvoiceStatus = InvoiceStatus.SENT,
    note: str | None = None,
) -> PaymentRecord:
    return PaymentRecord.record(
        id=uuid4(),
        invoice=invoice_state(status),
        amount=Money(amount_minor, "EUR"),
        received_on=date(2026, 7, 10),
        reference="KT26-0001",
        recorded_by_user_id=ADMIN_ID,
        recorded_at=RECORDED_AT,
        note=note,
    )


def reversed_entry(entry: PaymentRecord) -> PaymentRecord:
    return replace(
        entry,
        reversal=entry.reverse(
            id=uuid4(),
            reason="Bank hat die Gutschrift zurückgeholt.",
            reversed_by_user_id=ADMIN_ID,
            reversed_at=RECORDED_AT,
        ),
    )


def test_payment_keeps_date_amount_reference_and_note() -> None:
    entry = PaymentRecord.record(
        id=PAYMENT_ID,
        invoice=invoice_state(),
        amount=Money(36_000, "EUR"),
        received_on=date(2026, 7, 10),
        reference="  KT26-0001   Bankumsatz  ",
        recorded_by_user_id=ADMIN_ID,
        recorded_at=RECORDED_AT,
        note="  Rest  folgt  ",
    )

    assert entry.amount == Money(36_000, "EUR")
    assert entry.received_on == date(2026, 7, 10)
    assert entry.reference == "KT26-0001 Bankumsatz"
    assert entry.note == "Rest folgt"
    assert entry.active


def test_blank_note_is_dropped_and_long_note_rejected() -> None:
    assert payment(100, note="   ").note is None
    with pytest.raises(DomainInvariantError) as captured:
        payment(100, note="x" * 501)
    assert captured.value.code == "invoice_payment_note_too_long"


@pytest.mark.parametrize("amount_minor", (1, 35_999, 36_000, 36_001, 72_000))
def test_any_positive_amount_is_an_entry(amount_minor: int) -> None:
    assert payment(amount_minor).amount.amount_minor == amount_minor


@pytest.mark.parametrize(
    ("amount_minor", "code"),
    ((0, "invoice_payment_amount_invalid"), (-1, "money_amount_invalid")),
)
def test_non_positive_amount_is_rejected(amount_minor: int, code: str) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        payment(amount_minor)
    assert captured.value.code == code


def test_wrong_currency_is_rejected() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        PaymentRecord.record(
            id=PAYMENT_ID,
            invoice=invoice_state(),
            amount=Money(36_000, "USD"),
            received_on=date(2026, 7, 10),
            reference="KT26-0001",
            recorded_by_user_id=ADMIN_ID,
            recorded_at=RECORDED_AT,
        )
    assert captured.value.code == "invoice_payment_currency_mismatch"


@pytest.mark.parametrize(
    ("received_on", "code"),
    (
        (date(2026, 6, 29), "invoice_payment_before_issue"),
        (date(2026, 7, 13), "invoice_payment_future_date"),
    ),
)
def test_payment_date_must_be_between_issue_and_recording(
    received_on: date,
    code: str,
) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        PaymentRecord.record(
            id=PAYMENT_ID,
            invoice=invoice_state(),
            amount=Money(36_000, "EUR"),
            received_on=received_on,
            reference="KT26-0001",
            recorded_by_user_id=ADMIN_ID,
            recorded_at=RECORDED_AT,
        )
    assert captured.value.code == code


def test_paid_invoice_accepts_a_further_entry_but_cancelled_does_not() -> None:
    assert payment(500, status=InvoiceStatus.PAID).amount.amount_minor == 500
    with pytest.raises(DomainInvariantError) as captured:
        payment(500, status=InvoiceStatus.CANCELLED)
    assert captured.value.code == "invoice_payment_cancelled"


@pytest.mark.parametrize(
    ("amounts", "status", "paid", "open_", "overpaid"),
    (
        ((), SettlementStatus.OPEN, 0, 36_000, 0),
        ((10_000,), SettlementStatus.PARTIALLY_PAID, 10_000, 26_000, 0),
        ((10_000, 26_000), SettlementStatus.PAID, 36_000, 0, 0),
        ((36_000,), SettlementStatus.PAID, 36_000, 0, 0),
        ((35_999,), SettlementStatus.PARTIALLY_PAID, 35_999, 1, 0),
        ((36_001,), SettlementStatus.OVERPAID, 36_001, 0, 1),
        ((36_000, 36_000), SettlementStatus.OVERPAID, 72_000, 0, 36_000),
    ),
)
def test_balance_derives_status_and_amounts_in_cents(
    amounts: tuple[int, ...],
    status: SettlementStatus,
    paid: int,
    open_: int,
    overpaid: int,
) -> None:
    balance = InvoiceBalance.of(GROSS, (payment(amount) for amount in amounts))

    assert balance.status is status
    assert balance.paid == Money(paid, "EUR")
    assert balance.open_amount == Money(open_, "EUR")
    assert balance.overpaid_amount == Money(overpaid, "EUR")


def test_cent_sums_have_no_rounding_drift() -> None:
    # Three thirds of 360 € in cents: 120,00 € each, then one cent short.
    exact = InvoiceBalance.of(GROSS, (payment(12_000) for _ in range(3)))
    short = InvoiceBalance.of(
        GROSS, (payment(amount) for amount in (12_000, 12_000, 11_999))
    )
    assert exact.status is SettlementStatus.PAID
    assert short.open_amount == Money(1, "EUR")


def test_reversed_entry_leaves_the_sum_and_reopens_the_remainder() -> None:
    first, second = payment(20_000), payment(16_000)
    balance = InvoiceBalance.of(GROSS, (first, reversed_entry(second)))

    assert balance.status is SettlementStatus.PARTIALLY_PAID
    assert balance.open_amount == Money(16_000, "EUR")
    assert balance.invoice_status(delivered=True) is InvoiceStatus.SENT
    assert balance.invoice_status(delivered=False) is InvoiceStatus.ISSUED


def test_full_and_over_payment_store_paid_status() -> None:
    assert (
        InvoiceBalance.of(GROSS, (payment(36_000),)).invoice_status(delivered=False)
        is InvoiceStatus.PAID
    )
    assert (
        InvoiceBalance.of(GROSS, (payment(40_000),)).invoice_status(delivered=True)
        is InvoiceStatus.PAID
    )


def test_cancelled_balance_has_no_open_or_overpaid_amount() -> None:
    balance = InvoiceBalance.of(GROSS, (payment(10_000),), cancelled=True)

    assert balance.status is SettlementStatus.CANCELLED
    assert balance.open_amount == Money(0, "EUR")
    assert balance.overpaid_amount == Money(0, "EUR")
    assert balance.invoice_status(delivered=True) is InvoiceStatus.CANCELLED


def test_entry_is_reversed_only_once_and_needs_a_reason() -> None:
    entry = reversed_entry(payment(10_000))
    assert not entry.active
    with pytest.raises(DomainInvariantError) as captured:
        entry.reverse(
            id=uuid4(),
            reason="Noch einmal zurückbuchen.",
            reversed_by_user_id=ADMIN_ID,
            reversed_at=RECORDED_AT,
        )
    assert captured.value.code == "invoice_payment_already_reversed"
    with pytest.raises(DomainInvariantError) as captured:
        payment(10_000).reverse(
            id=uuid4(),
            reason="kurz",
            reversed_by_user_id=ADMIN_ID,
            reversed_at=RECORDED_AT,
        )
    assert captured.value.code == "invoice_payment_reversal_reason_too_short"


def test_reversal_must_belong_to_its_entry() -> None:
    entry = payment(10_000)
    foreign = PaymentReversal(
        id=uuid4(),
        action_id=ACTION_ID,
        invoice_id=INVOICE_ID,
        payment_id=uuid4(),
        reason="Bank hat die Gutschrift zurückgeholt.",
        reversed_by_user_id=ADMIN_ID,
        reversed_at=RECORDED_AT,
    )
    with pytest.raises(DomainInvariantError) as captured:
        replace(entry, reversal=foreign)
    assert captured.value.code == "invoice_payment_reversal_mismatch"


def test_settlement_version_grows_with_every_entry_and_reversal() -> None:
    first, second = payment(10_000), payment(5_000)
    versions = [
        settlement_version(()),
        settlement_version((first,)),
        settlement_version((first, second)),
        settlement_version((first, reversed_entry(second))),
        settlement_version((reversed_entry(first), reversed_entry(second))),
    ]
    assert versions == sorted(set(versions))


@pytest.mark.parametrize(
    "status",
    (InvoiceStatus.ISSUED, InvoiceStatus.SENT, InvoiceStatus.PAID),
)
def test_storno_preserves_original_status_and_reason(
    status: InvoiceStatus,
) -> None:
    cancellation = InvoiceCancellation.cancel(
        id=CANCELLATION_ID,
        invoice=invoice_state(status),
        reason="Empfängeranschrift muss fachlich korrigiert werden.",
        requested_by_user_id=ADMIN_ID,
        requested_at=RECORDED_AT,
    )

    assert cancellation.original_status is status
    assert cancellation.reason == "Empfängeranschrift muss fachlich korrigiert werden."


def test_cancelled_invoice_cannot_be_cancelled_again() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        InvoiceCancellation.cancel(
            id=CANCELLATION_ID,
            invoice=invoice_state(InvoiceStatus.CANCELLED),
            reason="Noch einmal stornieren.",
            requested_by_user_id=ADMIN_ID,
            requested_at=RECORDED_AT,
        )

    assert captured.value.code == "invoice_status_transition_invalid"


# ---------- application service: permissions and idempotency hashes ----------


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def record_payment(self, **kwargs: Any) -> Any:
        self.calls.append(("record", kwargs))
        return None

    async def reverse_payment(self, **kwargs: Any) -> Any:
        self.calls.append(("reverse", kwargs))
        return None

    async def cancel(self, **kwargs: Any) -> Any:
        self.calls.append(("cancel", kwargs))
        return None


def principal(
    *,
    role: ActionRole | None = None,
    global_roles: frozenset[GlobalRole] = frozenset(),
    scope: UUID = ACTION_ID,
) -> IdentityPrincipal:
    user = UserAccount(uuid4(), "user@example.invalid", "User", AccountStatus.ACTIVE)
    memberships = (
        (
            ActionMembership(
                uuid4(), scope, "Action", user.id, role, datetime.now(timezone.utc)
            ),
        )
        if role is not None
        else ()
    )
    return IdentityPrincipal(user, global_roles, memberships)


def record(
    service: InvoiceSettlementService,
    actor: IdentityPrincipal,
    **changes: Any,
) -> None:
    arguments: dict[str, Any] = {
        "amount_minor": 10_000,
        "currency": "EUR",
        "received_on": date(2026, 7, 10),
        "reference": "KT26-0001",
        "idempotency_key": "test:payment:0001",
        "request_id": "test-request",
        "occurred_at": RECORDED_AT,
        **changes,
    }
    asyncio.run(service.record_payment(actor, ACTION_ID, INVOICE_ID, **arguments))


def reverse(
    service: InvoiceSettlementService,
    actor: IdentityPrincipal,
    **changes: Any,
) -> None:
    arguments: dict[str, Any] = {
        "reason": "Bank hat die Gutschrift zurückgeholt.",
        "idempotency_key": "test:reversal:0001",
        "request_id": "test-request",
        "occurred_at": RECORDED_AT,
        **changes,
    }
    asyncio.run(
        service.reverse_payment(actor, ACTION_ID, INVOICE_ID, PAYMENT_ID, **arguments)
    )


@pytest.mark.parametrize(
    "actor",
    (
        principal(role=ActionRole.FINANCE_READER),
        principal(role=ActionRole.ACQUIRER),
        principal(role=ActionRole.CHARITY_ADMIN, scope=uuid4()),
        principal(global_roles=frozenset({GlobalRole.FINANCE_READER})),
    ),
)
def test_only_managers_record_or_reverse(actor: IdentityPrincipal) -> None:
    repository = RecordingRepository()
    service = InvoiceSettlementService(repository)  # type: ignore[arg-type]
    for command in (record, reverse):
        with pytest.raises(PermissionDenied) as captured:
            command(service, actor)
        assert captured.value.code == "invoice_settlement_required"
    assert repository.calls == []


@pytest.mark.parametrize(
    "actor",
    (
        principal(role=ActionRole.CHARITY_ADMIN),
        principal(global_roles=frozenset({GlobalRole.FINANCE_MANAGER})),
    ),
)
def test_managers_record_and_reverse_with_version(actor: IdentityPrincipal) -> None:
    repository = RecordingRepository()
    service = InvoiceSettlementService(repository)  # type: ignore[arg-type]
    record(service, actor, expected_version=3, note=" Teil 1 ")
    reverse(service, actor, expected_version=4)
    (_, recorded), (_, reversed_) = repository.calls
    assert recorded["expected_version"] == 3
    assert recorded["note"] == "Teil 1"
    assert reversed_["expected_version"] == 4
    assert reversed_["payment_id"] == PAYMENT_ID


def test_request_hash_ignores_version_but_binds_content() -> None:
    repository = RecordingRepository()
    service = InvoiceSettlementService(repository)  # type: ignore[arg-type]
    actor = principal(role=ActionRole.CHARITY_ADMIN)
    record(service, actor)
    record(service, actor, expected_version=7)
    record(service, actor, note="Rest folgt")
    record(service, actor, amount_minor=10_001)
    reverse(service, actor)
    reverse(service, actor, expected_version=9)
    reverse(service, actor, reason="Ein anderer Grund für die Rückbuchung.")
    hashes = [call["request_hash"] for _, call in repository.calls]
    assert hashes[0] == hashes[1]
    assert len({hashes[0], hashes[2], hashes[3]}) == 3
    assert hashes[4] == hashes[5] != hashes[6]


def test_request_hash_without_note_matches_the_full_payment_contract() -> None:
    # Commands recorded before notes existed keep replaying after the upgrade.
    repository = RecordingRepository()
    service = InvoiceSettlementService(repository)  # type: ignore[arg-type]
    record(service, principal(role=ActionRole.CHARITY_ADMIN), note="   ")
    expected = hashlib.sha256(
        json.dumps(
            {
                "actionId": str(ACTION_ID),
                "invoiceId": str(INVOICE_ID),
                "amountMinor": 10_000,
                "currency": "EUR",
                "receivedOn": "2026-07-10",
                "reference": "KT26-0001",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert repository.calls[0][1]["request_hash"] == expected


def test_malformed_idempotency_key_is_rejected() -> None:
    service = InvoiceSettlementService(RecordingRepository())  # type: ignore[arg-type]
    with pytest.raises(DomainInvariantError) as captured:
        reverse(service, principal(role=ActionRole.CHARITY_ADMIN), idempotency_key="x")
    assert captured.value.code == "invoice_settlement_idempotency_key_invalid"
