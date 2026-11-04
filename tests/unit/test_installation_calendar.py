"""Server-side "which day is it" follows the club's local day, not UTC.

23:30 UTC is 00:30 the next day in Berlin in winter (CET, UTC+1) and 01:30
in summer (CEST, UTC+2). Before the fix the payment check compared against
the UTC day, so in that hour no date passed both UI and server.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.calendar import INSTALLATION_TIME_ZONE, local_day
from leonaid.domain.commitments import Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoice_settlements import (
    InvoiceSettlementState,
    PaymentRecord,
)
from leonaid.domain.invoices import Invoice, InvoiceStatus
from tests.unit.test_invoice_domain import commitment, profile

WINTER_NIGHT = datetime(2026, 1, 14, 23, 30, tzinfo=timezone.utc)  # 00:30 CET
SUMMER_NIGHT = datetime(2026, 7, 14, 23, 30, tzinfo=timezone.utc)  # 01:30 CEST
NIGHTS = (
    pytest.param(WINTER_NIGHT, date(2026, 1, 15), id="winter"),
    pytest.param(SUMMER_NIGHT, date(2026, 7, 15), id="summer"),
)


@pytest.mark.parametrize(("moment", "berlin_day"), NIGHTS)
def test_local_day_is_the_berlin_day_after_utc_midnight_in_berlin(
    moment: datetime, berlin_day: date
) -> None:
    assert moment.date() == berlin_day - timedelta(days=1)
    assert local_day(moment) == berlin_day
    assert INSTALLATION_TIME_ZONE.key == "Europe/Berlin"


def test_local_day_refuses_naive_datetimes() -> None:
    with pytest.raises(ValueError):
        local_day(datetime(2026, 1, 14, 23, 30))


def _record(
    *, issued_at: datetime, recorded_at: datetime, received_on: date
) -> PaymentRecord:
    return PaymentRecord.record_full(
        id=UUID("97000000-0000-4000-8000-000000000020"),
        invoice=InvoiceSettlementState(
            id=UUID("90000000-0000-4000-8000-000000000020"),
            action_id=UUID("20000000-0000-4000-8000-000000000001"),
            number="KT26-0020",
            status=InvoiceStatus.SENT,
            issued_at=issued_at,
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
    issued_at = moment - timedelta(minutes=10)
    payment = _record(issued_at=issued_at, recorded_at=moment, received_on=berlin_day)
    assert payment.received_on == berlin_day


@pytest.mark.parametrize(("moment", "berlin_day"), NIGHTS)
def test_payment_dates_outside_the_berlin_days_are_rejected(
    moment: datetime, berlin_day: date
) -> None:
    issued_at = moment - timedelta(minutes=10)
    with pytest.raises(DomainInvariantError) as future:
        _record(
            issued_at=issued_at,
            recorded_at=moment,
            received_on=berlin_day + timedelta(days=1),
        )
    assert future.value.code == "invoice_payment_future_date"
    # The UTC day is yesterday in Berlin, before the invoice existed there.
    with pytest.raises(DomainInvariantError) as early:
        _record(issued_at=issued_at, recorded_at=moment, received_on=moment.date())
    assert early.value.code == "invoice_payment_before_issue"


@pytest.mark.parametrize(("moment", "berlin_day"), NIGHTS)
def test_invoice_date_and_due_date_use_the_berlin_day(
    moment: datetime, berlin_day: date
) -> None:
    invoice = Invoice.issue(
        id=UUID("90000000-0000-4000-8000-000000000021"),
        number="KT26-0021",
        commitment=commitment(),
        profile=replace(profile(), payment_terms_days=14),
        approved_by_user_id=UUID("10000000-0000-4000-8000-000000000002"),
        issued_at=moment,
        service_on=date(2026, 11, 15),
    )
    assert invoice.due_on == berlin_day + timedelta(days=14)


def test_rendered_invoice_date_is_the_berlin_day() -> None:
    from leonaid.adapters.typst import render_payload
    from tests.unit.test_invoice_documents import snapshot

    night = replace(snapshot(), issued_at=WINTER_NIGHT)
    assert render_payload(night)["issuedOn"] == "15.01.2026"
