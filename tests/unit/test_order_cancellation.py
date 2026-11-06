"""Order cancellation: reason, states, invoice cases, version and authorization."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from leonaid.adapters.postgres.order_cancellation import follow_up_closing_note
from leonaid.application.commitments import CommitmentRecord, CommitmentService
from leonaid.application.errors import PermissionDenied
from leonaid.application.order_cancellation import (
    OrderCancellationRequest,
    OrderCancellationResult,
    OrderCancellationService,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    Money,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.invoices import InvoiceStatus
from leonaid.domain.order_cancellation import (
    CANCELLABLE_ORDER_STATUSES,
    OrderCancellation,
    OrderInvoiceState,
    cancellation_block,
    normalize_note,
    normalize_reason,
)

ACTION_ID = uuid4()
VERSION = "a" * 64
NOW = datetime(2026, 11, 6, 23, 30, tzinfo=timezone.utc)


def line(quantity: int) -> CommitmentLine:
    return CommitmentLine(
        id=uuid4(),
        offering_id=uuid4(),
        description_snapshot="Krapfen",
        quantity=quantity,
        unit_snapshot=OfferingUnit.BOX,
        pieces_per_unit_snapshot=12,
        unit_price=Money(100, "EUR"),
        line_total=Money(100 * quantity, "EUR"),
    )


def order(status: CommitmentStatus, quantity: int = 2) -> Commitment:
    return Commitment(
        id=uuid4(),
        action_id=ACTION_ID,
        source=CommitmentSource.ADMIN,
        status=status,
        buyer=BuyerSnapshot(CommitmentPartyKind.PERSON, uuid4(), "Buyer"),
        invoice_recipient=None,
        lines=(line(quantity),),
        total=Money(100 * quantity, "EUR"),
    )


def invoice(
    status: InvoiceStatus, *, payment_recorded: bool = False
) -> OrderInvoiceState:
    return OrderInvoiceState(uuid4(), "KT26-0009", status, payment_recorded)


def principal(
    role: ActionRole | None,
    scope: UUID = ACTION_ID,
    global_roles: frozenset[GlobalRole] = frozenset(),
) -> IdentityPrincipal:
    user = UserAccount(uuid4(), "user@example.invalid", "User", AccountStatus.ACTIVE)
    memberships = (
        (ActionMembership(uuid4(), scope, "Action", user.id, role, NOW),)
        if role is not None
        else ()
    )
    return IdentityPrincipal(user, global_roles, memberships)


# ---------- reason and note ----------


def test_reason_is_collapsed_and_bounded() -> None:
    assert normalize_reason("  Sponsor   hat\n doppelt bestellt ") == (
        "Sponsor hat doppelt bestellt"
    )
    for value, code in (
        ("zu kurz", "commitment_cancellation_reason_too_short"),
        ("        ", "commitment_cancellation_reason_too_short"),
        ("x" * 501, "commitment_cancellation_reason_too_long"),
    ):
        with pytest.raises(DomainInvariantError) as error:
            normalize_reason(value)
        assert error.value.code == code
    assert normalize_reason("x" * 500) == "x" * 500


def test_note_keeps_lines_and_blank_means_none() -> None:
    assert normalize_note(None) is None
    assert normalize_note(" \n  ") is None
    assert normalize_note("  Erste Zeile  \n zweite  ") == "Erste Zeile\n zweite"
    with pytest.raises(DomainInvariantError) as error:
        normalize_note("x" * 1001)
    assert error.value.code == "commitment_cancellation_note_too_long"


# ---------- states and invoice cases ----------


@pytest.mark.parametrize("status", sorted(CANCELLABLE_ORDER_STATUSES))
def test_undelivered_orders_without_payment_may_be_cancelled(
    status: CommitmentStatus,
) -> None:
    for current in (
        None,
        invoice(InvoiceStatus.ISSUED),
        invoice(InvoiceStatus.SENT),
        invoice(InvoiceStatus.CANCELLED),
    ):
        assert (
            cancellation_block(status=status, delivered=False, invoice=current) is None
        )


def test_blocks_are_reported_most_final_first() -> None:
    paid = invoice(InvoiceStatus.PAID, payment_recorded=True)
    block = cancellation_block(
        status=CommitmentStatus.CANCELLED, delivered=True, invoice=paid
    )
    assert block is not None and block.code == "commitment_already_cancelled"
    block = cancellation_block(
        status=CommitmentStatus.INVOICED, delivered=True, invoice=paid
    )
    assert block is not None and block.code == "commitment_cancellation_delivered"
    assert "geliefert" in block.message
    block = cancellation_block(
        status=CommitmentStatus.INVOICED, delivered=False, invoice=paid
    )
    assert block is not None
    assert block.code == "commitment_cancellation_payment_recorded"
    assert "Zahlung zurückbuchen" in block.message
    assert "KT26-0009" in block.message


def test_any_booked_payment_blocks_even_before_the_invoice_is_paid() -> None:
    # A partial payment leaves the invoice open but is still money received.
    partly = invoice(InvoiceStatus.ISSUED, payment_recorded=True)
    block = cancellation_block(
        status=CommitmentStatus.INVOICED, delivered=False, invoice=partly
    )
    assert block is not None
    assert block.code == "commitment_cancellation_payment_recorded"
    # The paid status alone blocks, too (a payment row may be erased later).
    block = cancellation_block(
        status=CommitmentStatus.INVOICED,
        delivered=False,
        invoice=invoice(InvoiceStatus.PAID),
    )
    assert block is not None


def test_only_issued_and_sent_invoices_need_a_cancellation() -> None:
    assert invoice(InvoiceStatus.ISSUED).needs_cancellation
    assert invoice(InvoiceStatus.SENT).needs_cancellation
    assert not invoice(InvoiceStatus.PAID).needs_cancellation
    assert not invoice(InvoiceStatus.CANCELLED).needs_cancellation


def test_cancellation_record_validates_its_snapshot() -> None:
    record = OrderCancellation(
        id=uuid4(),
        action_id=ACTION_ID,
        commitment_id=uuid4(),
        previous_status=CommitmentStatus.REVIEW_READY,
        reason="  Sponsor   hat abgesagt ",
        note="  ",
        requested_by_user_id=uuid4(),
        requested_at=NOW,
    )
    assert record.reason == "Sponsor hat abgesagt" and record.note is None
    with pytest.raises(DomainInvariantError) as error:
        replace(record, previous_status=CommitmentStatus.CANCELLED)
    assert error.value.code == "commitment_cancellation_previous_status_invalid"
    with pytest.raises(DomainInvariantError):
        replace(record, requested_at=datetime(2026, 11, 6, 12))


# ---------- request ----------


def test_request_requires_a_version_and_normalizes() -> None:
    with pytest.raises(DomainInvariantError) as error:
        OrderCancellationRequest("stale", "Sponsor hat abgesagt")
    assert error.value.code == "commitment_cancellation_version_invalid"
    request = OrderCancellationRequest(VERSION, " Sponsor  hat abgesagt ", " ")
    assert request.reason == "Sponsor hat abgesagt" and request.note is None


def test_fingerprint_binds_actor_order_version_reason_and_note() -> None:
    request = OrderCancellationRequest(VERSION, "Sponsor hat abgesagt", "Notiz")
    actor, order_id = uuid4(), uuid4()

    def fingerprint(value: OrderCancellationRequest, **changes: UUID) -> str:
        arguments = {
            "action_id": ACTION_ID,
            "commitment_id": order_id,
            "actor_user_id": actor,
            **changes,
        }
        return value.fingerprint(**arguments)

    base = fingerprint(request)
    assert len(base) == 64 and fingerprint(request) == base
    # Whitespace the server normalizes away is the same command.
    assert (
        fingerprint(
            OrderCancellationRequest(VERSION, "Sponsor  hat abgesagt ", "Notiz ")
        )
        == base
    )
    for changed in (
        fingerprint(request, actor_user_id=uuid4()),
        fingerprint(request, commitment_id=uuid4()),
        fingerprint(request, action_id=uuid4()),
        fingerprint(replace(request, expected_version="b" * 64)),
        fingerprint(replace(request, reason="Anderer Grund hier")),
        fingerprint(replace(request, note=None)),
    ):
        assert changed != base


# ---------- service ----------


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def cancel(self, **arguments: Any) -> OrderCancellationResult:
        self.calls.append(arguments)
        cancelled = order(CommitmentStatus.CANCELLED)
        return OrderCancellationResult(
            commitment=cancelled,
            cancellation=OrderCancellation(
                id=uuid4(),
                action_id=ACTION_ID,
                commitment_id=cancelled.id,
                previous_status=CommitmentStatus.REVIEW_READY,
                reason=arguments["request"].reason,
                note=None,
                requested_by_user_id=arguments["actor_user_id"],
                requested_at=arguments["occurred_at"],
            ),
        )


def cancel(
    service: OrderCancellationService,
    actor: IdentityPrincipal,
    *,
    key: str = "order-cancellation:1",
    fresh_login: bool = False,
) -> OrderCancellationResult:
    return asyncio.run(
        service.cancel(
            actor,
            ACTION_ID,
            uuid4(),
            request=OrderCancellationRequest(VERSION, "Sponsor hat abgesagt"),
            fresh_login=fresh_login,
            idempotency_key=key,
            request_id="test",
        )
    )


@pytest.mark.parametrize(
    "actor",
    [
        principal(ActionRole.ACQUIRER),
        principal(ActionRole.DRIVER),
        principal(ActionRole.FINANCE_READER),
        principal(ActionRole.CHARITY_ADMIN, uuid4()),
        principal(None, global_roles=frozenset({GlobalRole.FINANCE_MANAGER})),
        principal(None, global_roles=frozenset({GlobalRole.FINANCE_READER})),
    ],
    ids=[
        "acquirer",
        "driver",
        "finance-reader",
        "admin-of-other-action",
        "finance-manager",
        "global-finance-reader",
    ],
)
def test_only_order_managers_may_cancel(actor: IdentityPrincipal) -> None:
    repository = RecordingRepository()
    with pytest.raises(PermissionDenied) as error:
        cancel(OrderCancellationService(repository), actor)
    assert error.value.code == "commitment_cancellation_manager_required"
    assert repository.calls == []


def test_disabled_account_may_not_cancel() -> None:
    actor = principal(ActionRole.CHARITY_ADMIN)
    disabled = replace(
        actor, account=replace(actor.account, status=AccountStatus.SUSPENDED)
    )
    with pytest.raises(PermissionDenied):
        cancel(OrderCancellationService(RecordingRepository()), disabled)


@pytest.mark.parametrize(
    "actor",
    [
        principal(ActionRole.CHARITY_ADMIN),
        principal(None, global_roles=frozenset({GlobalRole.SYSTEM_ADMIN})),
    ],
    ids=["charity-admin", "system-admin"],
)
def test_managers_cancel_with_key_hash_and_fresh_flag(actor: IdentityPrincipal) -> None:
    repository = RecordingRepository()
    service = OrderCancellationService(repository)
    with pytest.raises(DomainInvariantError) as error:
        cancel(service, actor, key="bad key")
    assert error.value.code == "commitment_idempotency_key_invalid"
    assert repository.calls == []
    result = cancel(service, actor, fresh_login=True)
    assert result.commitment.status is CommitmentStatus.CANCELLED
    (call,) = repository.calls
    assert call["fresh_login"] is True
    assert call["actor_user_id"] == actor.account.id
    assert call["request_hash"] == call["request"].fingerprint(
        action_id=ACTION_ID,
        commitment_id=call["commitment_id"],
        actor_user_id=actor.account.id,
    )
    assert call["occurred_at"].tzinfo is not None


# ---------- follow-up task and list totals ----------


def test_closing_note_holds_no_free_text_and_uses_the_local_day() -> None:
    # 23:30 UTC is already the next day in Berlin (CET, UTC+1).
    note = follow_up_closing_note(NOW)
    assert "06.11.2026" not in note and "07.11.2026" in note
    assert "storniert" in note and "Grund" in note


class ListingRepository:
    def __init__(self, records: tuple[CommitmentRecord, ...]) -> None:
        self.records = records

    async def list_for_action(self, **_arguments: Any) -> tuple[CommitmentRecord, ...]:
        return self.records


def test_cancelled_orders_stay_listed_but_count_for_nothing() -> None:
    active = CommitmentRecord(order(CommitmentStatus.REVIEW_READY, 2), NOW, None)
    cancelled = CommitmentRecord(order(CommitmentStatus.CANCELLED, 5), NOW, None)
    service = CommitmentService(ListingRepository((active, cancelled)))  # type: ignore[arg-type]
    listing = asyncio.run(
        service.list_for_action(principal(ActionRole.CHARITY_ADMIN), ACTION_ID)
    )
    assert listing.records == (active, cancelled)
    assert [item.total for item in listing.currency_totals] == [Money(200, "EUR")]
    assert listing.total_boxes == 2 and listing.total_pieces == 24
    assert [(item.unit, item.quantity) for item in listing.quantities] == [
        (OfferingUnit.BOX, 2)
    ]
