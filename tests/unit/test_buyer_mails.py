"""Buyer mail settings and the derived mail status of an order."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.application import buyer_mails as subject
from leonaid.application.buyer_mails import (
    BuyerMailJob,
    BuyerMailLedger,
    BuyerMailReason,
    BuyerMailState,
    BuyerMailStatus,
    last_sequence,
)
from leonaid.application.errors import Conflict
from leonaid.application.order_mails import OrderMailKind, order_mail_key
from leonaid.domain.buyer_mails import BuyerMailConfiguration
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
)
from leonaid.domain.errors import DomainInvariantError
from tests.unit.test_order_mails import (
    BERLIN,
    DELIVERY_MORNING,
    ORDER_ID,
    WINDOW_ID,
    order,
)

SENT_AT = datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc)
# Two days before the order's delivery window (14.02.2026, 09:00–11:00 Berlin).
NOW = datetime(2026, 2, 12, 9, 0, tzinfo=timezone.utc)


def buyer_mail_status(
    kind: OrderMailKind, value: BuyerMailLedger, *, now: datetime = NOW
) -> BuyerMailStatus:
    return subject.buyer_mail_status(kind, value, now=now)


def buyer_mail_statuses(
    value: BuyerMailLedger, *, now: datetime = NOW
) -> tuple[BuyerMailStatus, ...]:
    return subject.buyer_mail_statuses(value, now=now)


def resend_refusal(
    kind: OrderMailKind, value: BuyerMailLedger, *, now: datetime = NOW
) -> Conflict | None:
    return subject.resend_refusal(kind, value, now=now)


CONFIRMATION = OrderMailKind.CONFIRMATION
CANCELLATION = OrderMailKind.CANCELLATION


def key(kind: OrderMailKind = CONFIRMATION, resend: int | None = None) -> str:
    return order_mail_key(kind, ORDER_ID, resend=resend)


def ledger(
    *,
    jobs: tuple[BuyerMailJob, ...] = (),
    sent: tuple[tuple[str, datetime], ...] = (),
    internal_order_mails: bool = False,
    previous_status: CommitmentStatus | None = None,
    delivery_day_mail: bool = False,
    drop_state: str | None = None,
    **changes: object,
) -> BuyerMailLedger:
    return BuyerMailLedger(
        commitment=order(**changes),
        internal_order_mails=internal_order_mails,
        previous_status=previous_status,
        jobs=jobs,
        sent=sent,
        delivery_day_mail=delivery_day_mail,
        delivery_day_send_time=time(7, 0),
        delivery_zone=BERLIN,
        drop_state=drop_state,
    )


@pytest.mark.parametrize("moment", [time(5, 0), time(7, 0), time(9, 30), time(12, 0)])
def test_the_delivery_day_send_time_lies_between_five_and_noon(moment: time) -> None:
    configuration = BuyerMailConfiguration(
        action_id=uuid4(), delivery_day_send_time=moment
    )

    assert configuration.delivery_day_send_time == moment
    # Everything is off until the club switches it on.
    assert not configuration.internal_order_mails
    assert not configuration.delivery_day_mail


@pytest.mark.parametrize(
    "moment",
    [
        time(4, 59),
        time(12, 1),
        time(23, 0),
        time(7, 0, 30),
        time(7, 0, tzinfo=timezone.utc),
    ],
)
def test_a_send_time_outside_the_morning_is_refused(moment: time) -> None:
    with pytest.raises(DomainInvariantError) as captured:
        BuyerMailConfiguration(action_id=uuid4(), delivery_day_send_time=moment)

    assert captured.value.code == "buyer_mail_send_time_invalid"


def test_a_sent_mail_can_be_sent_again() -> None:
    status = buyer_mail_status(
        CONFIRMATION,
        ledger(
            jobs=(BuyerMailJob(key(), "completed"),),
            sent=((key(), SENT_AT),),
        ),
    )

    assert status == BuyerMailStatus(
        CONFIRMATION, BuyerMailState.SENT, sent_at=SENT_AT, can_resend=True
    )


def test_a_sent_mail_stays_sent_after_retention_deleted_its_job() -> None:
    status = buyer_mail_status(CONFIRMATION, ledger(sent=((key(), SENT_AT),)))

    assert status.state is BuyerMailState.SENT
    assert status.sent_at == SENT_AT


@pytest.mark.parametrize("job_status", ["pending", "processing"])
def test_a_waiting_job_is_queued_and_cannot_be_sent_again(job_status: str) -> None:
    value = ledger(jobs=(BuyerMailJob(key(), job_status, "smtp_unavailable"),))
    status = buyer_mail_status(CONFIRMATION, value)

    assert status.state is BuyerMailState.QUEUED
    assert status.reason is None
    assert not status.can_resend
    refusal = resend_refusal(CONFIRMATION, value)
    assert refusal is not None and refusal.code == "buyer_mail_already_queued"


@pytest.mark.parametrize(
    ("error_code", "reason"),
    [
        ("order_mail_recipient_limit", BuyerMailReason.RECIPIENT_LIMIT),
        ("smtp_unavailable", BuyerMailReason.DELIVERY_FAILED),
        (None, BuyerMailReason.DELIVERY_FAILED),
    ],
)
def test_a_dead_job_is_failed_with_its_reason_and_can_be_sent_again(
    error_code: str | None, reason: BuyerMailReason
) -> None:
    value = ledger(jobs=(BuyerMailJob(key(), "dead_letter", error_code),))
    status = buyer_mail_status(CONFIRMATION, value)

    assert status == BuyerMailStatus(
        CONFIRMATION, BuyerMailState.FAILED, reason=reason, can_resend=True
    )
    assert resend_refusal(CONFIRMATION, value) is None


def test_the_newest_job_decides_and_the_last_send_time_stays_visible() -> None:
    later = SENT_AT + timedelta(hours=2)
    value = ledger(
        jobs=(
            BuyerMailJob(key(), "completed"),
            BuyerMailJob(key(resend=1), "completed"),
            BuyerMailJob(key(resend=2), "pending"),
        ),
        sent=((key(), SENT_AT), (key(resend=1), later)),
    )

    assert last_sequence(CONFIRMATION, value) == 2
    status = buyer_mail_status(CONFIRMATION, value)
    assert status.state is BuyerMailState.QUEUED
    assert status.sent_at == later


def test_resend_numbers_are_compared_as_numbers() -> None:
    value = ledger(
        sent=tuple(
            (key(resend=number), SENT_AT + timedelta(minutes=number))
            for number in (2, 10)
        )
    )

    assert last_sequence(CONFIRMATION, value) == 10
    assert buyer_mail_status(CONFIRMATION, value).sent_at == SENT_AT + timedelta(
        minutes=10
    )


def test_jobs_of_another_kind_or_order_do_not_count() -> None:
    other_order = order_mail_key(CONFIRMATION, uuid4())
    value = ledger(
        jobs=(
            BuyerMailJob(key(CANCELLATION), "pending"),
            BuyerMailJob(other_order, "pending"),
            BuyerMailJob(f"{key()}:resend:x", "pending"),
            BuyerMailJob(f"{key()}:other:1", "pending"),
        )
    )

    assert last_sequence(CONFIRMATION, value) is None
    assert buyer_mail_status(CONFIRMATION, value).state is BuyerMailState.NOT_DUE


def test_an_order_without_any_job_says_why_no_mail_is_due() -> None:
    no_email = BuyerSnapshot(
        party_kind=CommitmentPartyKind.COMPANY,
        twenty_id=uuid4(),
        display_name="Firma",
        email=None,
    )
    cases = [
        (ledger(buyer=no_email), BuyerMailReason.NO_EMAIL),
        (ledger(source=CommitmentSource.ADMIN), BuyerMailReason.SWITCHED_OFF),
        (
            ledger(
                source=CommitmentSource.ACQUISITION,
                status=CommitmentStatus.DRAFT,
                internal_order_mails=True,
            ),
            BuyerMailReason.ORDER_DRAFT,
        ),
        # Recorded while the switch was off, switched on later.
        (
            ledger(source=CommitmentSource.ADMIN, internal_order_mails=True),
            BuyerMailReason.NOT_REQUESTED,
        ),
    ]
    for value, reason in cases:
        status = buyer_mail_status(CONFIRMATION, value)
        assert status == BuyerMailStatus(
            CONFIRMATION, BuyerMailState.NOT_DUE, reason=reason
        ), reason
        refusal = resend_refusal(CONFIRMATION, value)
        assert refusal is not None
        assert refusal.code == "buyer_mail_resend_not_allowed"


def test_a_job_that_ended_without_a_mail_is_skipped_with_the_reason() -> None:
    switched_off = ledger(
        source=CommitmentSource.ADMIN, jobs=(BuyerMailJob(key(), "completed"),)
    )
    unknown = ledger(jobs=(BuyerMailJob(key(), "completed"),))

    assert buyer_mail_status(CONFIRMATION, switched_off) == BuyerMailStatus(
        CONFIRMATION, BuyerMailState.SKIPPED, reason=BuyerMailReason.SWITCHED_OFF
    )
    assert buyer_mail_status(CONFIRMATION, unknown).reason is BuyerMailReason.NOT_SENT
    assert not buyer_mail_status(CONFIRMATION, unknown).can_resend


def test_a_cancelled_order_lists_both_kinds_and_resends_only_the_notice() -> None:
    value = ledger(
        status=CommitmentStatus.CANCELLED,
        previous_status=CommitmentStatus.REVIEW_READY,
        jobs=(
            BuyerMailJob(key(), "completed"),
            BuyerMailJob(key(CANCELLATION), "completed"),
        ),
        sent=((key(), SENT_AT), (key(CANCELLATION), SENT_AT + timedelta(days=1))),
    )

    confirmation, cancellation = buyer_mail_statuses(value)
    assert confirmation == BuyerMailStatus(
        CONFIRMATION, BuyerMailState.SENT, sent_at=SENT_AT, can_resend=False
    )
    assert cancellation == BuyerMailStatus(
        CANCELLATION,
        BuyerMailState.SENT,
        sent_at=SENT_AT + timedelta(days=1),
        can_resend=True,
    )
    refusal = resend_refusal(CONFIRMATION, value)
    assert refusal is not None and refusal.code == "buyer_mail_not_due"
    assert resend_refusal(CANCELLATION, value) is None


def test_an_open_order_has_no_cancellation_notice() -> None:
    value = ledger(sent=((key(), SENT_AT),))

    assert [status.kind for status in buyer_mail_statuses(value)] == [CONFIRMATION]
    refusal = resend_refusal(CANCELLATION, value)
    assert refusal is not None and refusal.code == "buyer_mail_not_applicable"


def test_an_erased_buyer_gets_no_resend_of_a_sent_mail() -> None:
    erased = BuyerSnapshot(
        party_kind=CommitmentPartyKind.COMPANY,
        twenty_id=uuid4(),
        display_name="Anonymisiert",
        email=None,
    )
    value = ledger(buyer=erased, sent=((key(), SENT_AT),))

    status = buyer_mail_status(CONFIRMATION, value)
    assert status.state is BuyerMailState.SENT
    assert not status.can_resend
    refusal = resend_refusal(CONFIRMATION, value)
    assert refusal is not None and refusal.code == "buyer_mail_not_due"


def test_a_cancelled_internal_draft_has_no_notice_to_send() -> None:
    value = ledger(
        source=CommitmentSource.ADMIN,
        status=CommitmentStatus.CANCELLED,
        internal_order_mails=True,
        previous_status=CommitmentStatus.DRAFT,
    )

    assert [status.reason for status in buyer_mail_statuses(value)] == [
        BuyerMailReason.ORDER_DRAFT,
        BuyerMailReason.ORDER_DRAFT,
    ]


# ---- the mail on the delivery day -------------------------------------

DELIVERY_DAY = OrderMailKind.DELIVERY_DAY


def day_key(resend: int | None = None, window_id: UUID = WINDOW_ID) -> str:
    return order_mail_key(DELIVERY_DAY, ORDER_ID, window_id=window_id, resend=resend)


def test_the_delivery_day_mail_is_listed_for_an_order_with_a_window_and_the_switch() -> (
    None
):
    with_window = ledger(delivery_day_mail=True)
    kinds = [status.kind for status in buyer_mail_statuses(with_window)]
    assert kinds == [CONFIRMATION, DELIVERY_DAY]

    # Not while the action does not send it, and never without a window.
    assert DELIVERY_DAY not in [s.kind for s in buyer_mail_statuses(ledger())]
    no_window = ledger(
        delivery_day_mail=True, delivery_window_id=None, delivery_window_snapshot=None
    )
    assert [s.kind for s in buyer_mail_statuses(no_window)] == [CONFIRMATION]
    refusal = resend_refusal(DELIVERY_DAY, no_window)
    assert refusal is not None and refusal.code == "buyer_mail_not_applicable"
    # A mail that went out stays visible after the action switched it off.
    switched_off = ledger(sent=((day_key(), SENT_AT),))
    assert DELIVERY_DAY in [s.kind for s in buyer_mail_statuses(switched_off)]
    # Cancelled: confirmation, delivery day, cancellation notice.
    cancelled = ledger(
        delivery_day_mail=True,
        status=CommitmentStatus.CANCELLED,
        previous_status=CommitmentStatus.REVIEW_READY,
    )
    assert [s.kind for s in buyer_mail_statuses(cancelled)] == [
        CONFIRMATION,
        DELIVERY_DAY,
        CANCELLATION,
    ]


def test_before_the_delivery_day_the_mail_is_scheduled() -> None:
    value = ledger(delivery_day_mail=True)

    for now in (
        NOW,
        datetime(2026, 2, 14, 6, 59, tzinfo=BERLIN),
        # Due, and the next sweep queues it.
        DELIVERY_MORNING,
    ):
        assert buyer_mail_status(DELIVERY_DAY, value, now=now) == BuyerMailStatus(
            DELIVERY_DAY, BuyerMailState.NOT_DUE, reason=BuyerMailReason.SCHEDULED
        ), now
        refusal = resend_refusal(DELIVERY_DAY, value, now=now)
        assert refusal is not None
        assert refusal.code == "buyer_mail_resend_not_allowed"


def test_without_a_job_the_delivery_day_mail_says_why_it_will_not_come() -> None:
    erased = BuyerSnapshot(
        party_kind=CommitmentPartyKind.COMPANY,
        twenty_id=uuid4(),
        display_name="Firma",
        email=None,
    )
    after = datetime(2026, 2, 14, 11, 0, tzinfo=BERLIN)
    cases = [
        (ledger(delivery_day_mail=True, buyer=erased), DELIVERY_MORNING, "no_email"),
        (
            ledger(delivery_day_mail=True, status=CommitmentStatus.DRAFT),
            DELIVERY_MORNING,
            "order_draft",
        ),
        (
            ledger(delivery_day_mail=True, drop_state="delivered"),
            DELIVERY_MORNING,
            "delivery_recorded",
        ),
        (ledger(delivery_day_mail=True), after, "window_over"),
    ]
    for value, now, reason in cases:
        status = buyer_mail_status(DELIVERY_DAY, value, now=now)
        assert status.state is BuyerMailState.NOT_DUE
        assert status.reason is not None and status.reason.value == reason
        assert not status.can_resend


def test_a_sent_delivery_day_mail_can_be_sent_again_until_the_window_ends() -> None:
    value = ledger(
        delivery_day_mail=True,
        jobs=(BuyerMailJob(day_key(), "completed"),),
        sent=((day_key(), DELIVERY_MORNING),),
    )
    during = datetime(2026, 2, 14, 10, 30, tzinfo=BERLIN)
    after = datetime(2026, 2, 14, 11, 0, tzinfo=BERLIN)

    assert buyer_mail_status(DELIVERY_DAY, value, now=during) == BuyerMailStatus(
        DELIVERY_DAY, BuyerMailState.SENT, sent_at=DELIVERY_MORNING, can_resend=True
    )
    assert resend_refusal(DELIVERY_DAY, value, now=during) is None
    # Afterwards it stays "sent", but "today" is over.
    late = buyer_mail_status(DELIVERY_DAY, value, now=after)
    assert late.state is BuyerMailState.SENT and not late.can_resend
    refusal = resend_refusal(DELIVERY_DAY, value, now=after)
    assert refusal is not None and refusal.code == "buyer_mail_not_due"


def test_a_delivered_or_cancelled_order_gets_no_resend_of_the_delivery_day_mail() -> (
    None
):
    sent = ((day_key(), DELIVERY_MORNING),)
    during = datetime(2026, 2, 14, 9, 30, tzinfo=BERLIN)
    for value in (
        ledger(delivery_day_mail=True, sent=sent, drop_state="delivered"),
        ledger(delivery_day_mail=True, sent=sent, drop_state="missed"),
        ledger(
            delivery_day_mail=True,
            sent=sent,
            status=CommitmentStatus.CANCELLED,
            previous_status=CommitmentStatus.REVIEW_READY,
        ),
        ledger(delivery_day_mail=False, sent=sent),
    ):
        status = buyer_mail_status(DELIVERY_DAY, value, now=during)
        assert status.state is BuyerMailState.SENT and not status.can_resend
        refusal = resend_refusal(DELIVERY_DAY, value, now=during)
        assert refusal is not None and refusal.code == "buyer_mail_not_due"


def test_jobs_of_a_window_the_order_left_do_not_count_for_its_window_now() -> None:
    old_window = uuid4()
    value = ledger(
        delivery_day_mail=True,
        jobs=(BuyerMailJob(day_key(window_id=old_window), "completed"),),
        sent=((day_key(window_id=old_window), SENT_AT),),
    )

    assert last_sequence(DELIVERY_DAY, value) is None
    status = buyer_mail_status(DELIVERY_DAY, value, now=DELIVERY_MORNING)
    assert status == BuyerMailStatus(
        DELIVERY_DAY, BuyerMailState.NOT_DUE, reason=BuyerMailReason.SCHEDULED
    )


def test_a_failed_delivery_day_mail_and_its_resend_number() -> None:
    value = ledger(
        delivery_day_mail=True,
        jobs=(
            BuyerMailJob(day_key(), "completed"),
            BuyerMailJob(
                day_key(resend=1), "dead_letter", "order_mail_recipient_limit"
            ),
        ),
        sent=((day_key(), DELIVERY_MORNING),),
    )
    during = datetime(2026, 2, 14, 9, 30, tzinfo=BERLIN)

    assert last_sequence(DELIVERY_DAY, value) == 1
    assert buyer_mail_status(DELIVERY_DAY, value, now=during) == BuyerMailStatus(
        DELIVERY_DAY,
        BuyerMailState.FAILED,
        sent_at=DELIVERY_MORNING,
        reason=BuyerMailReason.RECIPIENT_LIMIT,
        can_resend=True,
    )
    # The confirmation's jobs are not touched by the delivery-day keys.
    assert last_sequence(CONFIRMATION, value) is None
