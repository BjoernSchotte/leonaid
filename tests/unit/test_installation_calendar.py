"""Server-side "which day is it" follows the club's local day, not UTC.

23:30 UTC is 00:30 the next day in Berlin in winter (CET, UTC+1) and 01:30
in summer (CEST, UTC+2). Before the fix the payment check compared against
the UTC day, so in that hour no date passed both UI and server. The invoice
date is now stored at issue (``issued_on``) and read back, never re-derived.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.adapters.typst import render_payload
from leonaid.application.invoice_documents import (
    INVOICE_DOCUMENT_SCHEMA_VERSION,
    InvoiceDocumentSnapshot,
)
from leonaid.domain.calendar import local_day, local_day_bounds
from leonaid.domain.commitments import Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoice_settlements import (
    InvoiceSettlementState,
    PaymentRecord,
)
from leonaid.domain.invoices import Invoice, InvoiceStatus
from leonaid.modules.tasks.planning import planning_day
from tests.unit.invoice_builders import (
    commitment,
    document_snapshot,
    golden_document_payload,
    profile,
)

WINTER_NIGHT = datetime(2026, 1, 14, 23, 30, tzinfo=timezone.utc)  # 00:30 CET
SUMMER_NIGHT = datetime(2026, 7, 14, 23, 30, tzinfo=timezone.utc)  # 01:30 CEST
NIGHTS = (
    pytest.param(WINTER_NIGHT, date(2026, 1, 15), id="winter"),
    pytest.param(SUMMER_NIGHT, date(2026, 7, 15), id="summer"),
)


@pytest.mark.parametrize(
    ("moment", "berlin_day"),
    (
        *NIGHTS,
        # Spring forward: 29 March 2026, 02:00 CET -> 03:00 CEST.
        pytest.param(
            datetime(2026, 3, 28, 22, 59, tzinfo=timezone.utc),
            date(2026, 3, 28),
            id="spring-eve-last-minute",
        ),
        pytest.param(
            datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc),
            date(2026, 3, 29),
            id="spring-midnight",
        ),
        pytest.param(
            datetime(2026, 3, 29, 21, 59, tzinfo=timezone.utc),
            date(2026, 3, 29),
            id="spring-day-last-minute",
        ),
        pytest.param(
            datetime(2026, 3, 29, 22, 0, tzinfo=timezone.utc),
            date(2026, 3, 30),
            id="spring-next-midnight",
        ),
        # Fall back: 25 October 2026, 03:00 CEST -> 02:00 CET.
        pytest.param(
            datetime(2026, 10, 24, 21, 59, tzinfo=timezone.utc),
            date(2026, 10, 24),
            id="autumn-eve-last-minute",
        ),
        pytest.param(
            datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc),
            date(2026, 10, 25),
            id="autumn-midnight",
        ),
        pytest.param(
            datetime(2026, 10, 25, 22, 59, tzinfo=timezone.utc),
            date(2026, 10, 25),
            id="autumn-day-last-minute",
        ),
        pytest.param(
            datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc),
            date(2026, 10, 26),
            id="autumn-next-midnight",
        ),
    ),
)
def test_local_day_is_the_berlin_day(moment: datetime, berlin_day: date) -> None:
    assert local_day(moment) == berlin_day


def test_local_day_refuses_naive_datetimes() -> None:
    with pytest.raises(DomainInvariantError):
        local_day(datetime(2026, 1, 14, 23, 30))


@pytest.mark.parametrize(
    ("day", "start", "hours"),
    (
        (date(2026, 1, 15), datetime(2026, 1, 14, 23, tzinfo=timezone.utc), 24),
        (date(2026, 7, 15), datetime(2026, 7, 14, 22, tzinfo=timezone.utc), 24),
        (date(2026, 3, 29), datetime(2026, 3, 28, 23, tzinfo=timezone.utc), 23),
        (date(2026, 10, 25), datetime(2026, 10, 24, 22, tzinfo=timezone.utc), 25),
    ),
)
def test_local_day_bounds_cover_the_berlin_day(
    day: date, start: datetime, hours: int
) -> None:
    begins, ends = local_day_bounds(day)
    assert begins == start
    assert ends - begins == timedelta(hours=hours)
    assert local_day(begins) == day
    assert local_day(ends - timedelta(microseconds=1)) == day
    assert local_day(ends) == day + timedelta(days=1)


def test_task_planning_keeps_the_viewers_zone_and_refuses_naive_clocks() -> None:
    today, start, end = planning_day("America/New_York", now=WINTER_NIGHT)
    assert today == date(2026, 1, 14)
    assert start == datetime(2026, 1, 14, 5, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 15, 5, tzinfo=timezone.utc)
    with pytest.raises(DomainInvariantError):
        planning_day("Europe/Berlin", now=datetime(2026, 1, 14, 23, 30))


def _issue(moment: datetime) -> Invoice:
    return Invoice.issue(
        id=UUID("90000000-0000-4000-8000-000000000021"),
        number="KT26-0021",
        commitment=commitment(),
        profile=replace(profile(), payment_terms_days=14),
        approved_by_user_id=UUID("10000000-0000-4000-8000-000000000002"),
        issued_at=moment,
        service_on=date(2026, 11, 15),
    )


@pytest.mark.parametrize(("moment", "berlin_day"), NIGHTS)
def test_a_night_hour_issue_stores_the_berlin_day(
    moment: datetime, berlin_day: date
) -> None:
    invoice = _issue(moment)
    assert invoice.issued_on == berlin_day
    assert invoice.due_on == berlin_day + timedelta(days=14)
    snapshot = InvoiceDocumentSnapshot.from_invoice(invoice)
    assert snapshot.issued_on == berlin_day
    assert render_payload(snapshot)["issuedOn"] == berlin_day.strftime("%d.%m.%Y")


def test_an_old_night_hour_invoice_keeps_its_stored_utc_day() -> None:
    # Issued before the fix: the migration stored its UTC day, which its
    # due date was computed from. Loading and rendering keep that day.
    stored = replace(
        _issue(WINTER_NIGHT),
        issued_on=WINTER_NIGHT.date(),
        due_on=WINTER_NIGHT.date() + timedelta(days=14),
    )
    snapshot = InvoiceDocumentSnapshot.from_invoice(stored)
    assert render_payload(snapshot)["issuedOn"] == "14.01.2026"
    assert render_payload(snapshot)["dueOn"] == "28.01.2026"


def test_document_payload_carries_the_invoice_date() -> None:
    snapshot = replace(
        document_snapshot(), issued_at=WINTER_NIGHT, issued_on=date(2026, 1, 15)
    )
    payload = snapshot.payload()
    assert payload["schemaVersion"] == INVOICE_DOCUMENT_SCHEMA_VERSION == 2
    assert payload["issuedOn"] == "2026-01-15"
    assert InvoiceDocumentSnapshot.from_payload(payload) == snapshot


def test_a_version_1_document_keeps_the_utc_day_it_was_printed_with() -> None:
    payload = {
        **golden_document_payload(),
        "schemaVersion": 1,
        "issuedAt": WINTER_NIGHT.isoformat(),
    }
    payload.pop("issuedOn", None)
    snapshot = InvoiceDocumentSnapshot.from_payload(payload)
    assert snapshot.issued_on == date(2026, 1, 14)


def test_the_due_date_may_not_precede_the_stored_invoice_date() -> None:
    invoice = _issue(WINTER_NIGHT)
    with pytest.raises(DomainInvariantError) as captured:
        replace(invoice, due_on=invoice.issued_on - timedelta(days=1))
    assert captured.value.code == "invoice_due_date_invalid"


def _record(
    *,
    issued_at: datetime,
    issued_on: date,
    recorded_at: datetime,
    received_on: date,
) -> PaymentRecord:
    return PaymentRecord.record_full(
        id=UUID("97000000-0000-4000-8000-000000000020"),
        invoice=InvoiceSettlementState(
            id=UUID("90000000-0000-4000-8000-000000000020"),
            action_id=UUID("20000000-0000-4000-8000-000000000001"),
            number="KT26-0020",
            status=InvoiceStatus.SENT,
            issued_at=issued_at,
            issued_on=issued_on,
            gross=Money(36_000, "EUR"),
        ),
        amount=Money(36_000, "EUR"),
        received_on=received_on,
        reference="KT26-0020",
        recorded_by_user_id=UUID("10000000-0000-4000-8000-000000000002"),
        recorded_at=recorded_at,
    )


@pytest.mark.parametrize(("moment", "berlin_day"), NIGHTS)
def test_payment_on_the_berlin_day_is_accepted_right_after_midnight(
    moment: datetime, berlin_day: date
) -> None:
    # Issued and recorded in the same Berlin night: the only valid date is
    # today in Berlin, which the UI also offers.
    payment = _record(
        issued_at=moment - timedelta(minutes=10),
        issued_on=berlin_day,
        recorded_at=moment,
        received_on=berlin_day,
    )
    assert payment.received_on == berlin_day


@pytest.mark.parametrize(("moment", "berlin_day"), NIGHTS)
def test_payment_dates_outside_the_berlin_days_are_rejected(
    moment: datetime, berlin_day: date
) -> None:
    issued_at = moment - timedelta(minutes=10)
    with pytest.raises(DomainInvariantError) as future:
        _record(
            issued_at=issued_at,
            issued_on=berlin_day,
            recorded_at=moment,
            received_on=berlin_day + timedelta(days=1),
        )
    assert future.value.code == "invoice_payment_future_date"
    # The UTC day is yesterday in Berlin, before the printed invoice date.
    with pytest.raises(DomainInvariantError) as early:
        _record(
            issued_at=issued_at,
            issued_on=berlin_day,
            recorded_at=moment,
            received_on=moment.date(),
        )
    assert early.value.code == "invoice_payment_before_issue"


def test_payment_check_reads_the_stored_invoice_date() -> None:
    # An old night-hour invoice printed with the UTC day accepts a payment
    # on that printed day.
    payment = _record(
        issued_at=WINTER_NIGHT,
        issued_on=WINTER_NIGHT.date(),
        recorded_at=WINTER_NIGHT + timedelta(days=1),
        received_on=WINTER_NIGHT.date(),
    )
    assert payment.received_on == date(2026, 1, 14)
