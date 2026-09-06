from dataclasses import replace
from datetime import date, datetime, time, timezone
from uuid import uuid4

import pytest

from leonaid.domain.commitments import DeliveryRecipientSnapshot
from leonaid.domain.delivery import DeliveryConfiguration, DeliveryWindow, local_instant
from leonaid.domain.errors import DomainInvariantError
from leonaid.entrypoints.fastapi.schemas import PublicOrderInvoiceRecipientRequest
from pydantic import ValidationError


def test_variable_days_and_adjacent_windows_are_sorted_and_selectable() -> None:
    action = uuid4()
    windows = tuple(
        DeliveryWindow(uuid4(), action, date(2027, 2, day), time(hour), time(hour + 2))
        for day, hours in ((4, (8, 10, 12)), (5, (8, 10, 12)), (6, (9,)))
        for hour in hours
    )
    config = DeliveryConfiguration(action, enabled=True, windows=windows[::-1])
    assert config.windows == windows
    config.validate_period(date(2027, 2, 1), date(2027, 2, 7))
    selected = config.select(
        windows[0].id, now=datetime(2027, 1, 1, tzinfo=timezone.utc)
    )
    assert selected.snapshot(config.timezone)["startsAt"] == "08:00"
    assert config.form_definition()["requireWindow"] is True
    with pytest.raises(DomainInvariantError, match="Aktionslaufzeit"):
        config.validate_period(date(2027, 2, 5), date(2027, 2, 7))


@pytest.mark.parametrize("day", [date(2027, 3, 28), date(2027, 10, 31)])
def test_dst_gap_and_fold_are_rejected(day: date) -> None:
    with pytest.raises(DomainInvariantError) as error:
        local_instant(day, time(2, 30), "Europe/Berlin")
    assert error.value.code == "delivery_time_dst_invalid"


def test_invalid_schedules_and_unavailable_selection() -> None:
    action = uuid4()
    window = DeliveryWindow(uuid4(), action, date(2027, 2, 4), time(8), time(10))
    with pytest.raises(DomainInvariantError, match="überlappen"):
        DeliveryConfiguration(
            action, windows=(window, replace(window, id=uuid4(), starts_at=time(9)))
        )
    with pytest.raises(DomainInvariantError, match="doppelt"):
        DeliveryConfiguration(action, windows=(window, window))
    with pytest.raises(DomainInvariantError, match="nicht zu dieser Aktion"):
        DeliveryConfiguration(uuid4(), windows=(window,))
    with pytest.raises(DomainInvariantError, match="Ende"):
        replace(window, ends_at=time(7))
    with pytest.raises(DomainInvariantError, match="Minuten"):
        replace(window, starts_at=time(8, 0, 1)).bounds("Europe/Berlin")
    with pytest.raises(DomainInvariantError, match="Lieferzeitzone"):
        DeliveryConfiguration(action, timezone="Invalid/Zone")
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    for config, selection, when in (
        (DeliveryConfiguration(action, windows=(window,)), window.id, now),
        (DeliveryConfiguration(action, True, windows=(window,)), uuid4(), now),
        (
            DeliveryConfiguration(
                action, True, windows=(replace(window, retired=True),)
            ),
            window.id,
            now,
        ),
        (
            DeliveryConfiguration(action, True, windows=(window,)),
            window.id,
            datetime(2027, 2, 4, 7, tzinfo=timezone.utc),
        ),
    ):
        with pytest.raises(DomainInvariantError, match="nicht mehr verfügbar"):
            config.select(selection, now=when)


def test_delivery_notes_roundtrip_and_old_snapshots() -> None:
    old = {
        "recipientName": "Testempfang",
        "streetLine1": "Testweg 1",
        "postalCode": "00000",
        "city": "Teststadt",
        "countryCode": "DE",
    }
    original = DeliveryRecipientSnapshot.from_payload(old)
    assert original.contact_name is None
    assert original.instructions is None
    assert original.payload() == old
    updated = replace(
        original,
        contact_name=" Testkontakt ",
        contact_phone=" 000 123 ",
        instructions="  Abteilung A\n4. Stock\n<script>text</script>  ",
    )
    assert DeliveryRecipientSnapshot.from_payload(updated.payload()) == updated
    assert updated.instructions == "Abteilung A\n4. Stock\n<script>text</script>"
    assert replace(updated, contact_name=" \n ").contact_name is None
    for field, limit in (
        ("contact_name", 200),
        ("contact_phone", 50),
        ("instructions", 1000),
    ):
        with pytest.raises(DomainInvariantError):
            replace(original, **{field: "x" * (limit + 1)})


def test_invoice_contract_rejects_delivery_only_contact_and_notes() -> None:
    address = dict(
        recipientName="Test",
        streetLine1="Testweg 1",
        postalCode="00000",
        city="Teststadt",
        email="invoice@example.invalid",
    )
    for field in ("contactName", "contactPhone", "instructions"):
        with pytest.raises(ValidationError):
            PublicOrderInvoiceRecipientRequest.model_validate(
                {**address, field: "Test"}
            )
