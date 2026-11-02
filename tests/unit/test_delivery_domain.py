from dataclasses import replace
from datetime import date, datetime, time, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.domain.delivery import DeliveryConfiguration, DeliveryWindow, local_instant
from leonaid.domain.errors import DomainInvariantError


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
    assert selected.snapshot(config.timezone)["startsAt"] == "2027-02-04T07:00:00+00:00"
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


def test_manager_completion_records_past_windows_as_historical() -> None:
    action = uuid4()
    past = DeliveryWindow(uuid4(), action, date(2027, 2, 4), time(8), time(10))
    retired_past = DeliveryWindow(
        uuid4(), action, date(2027, 2, 4), time(10), time(12), retired=True
    )
    future = DeliveryWindow(uuid4(), action, date(2027, 2, 6), time(8), time(10))
    retired_future = DeliveryWindow(
        uuid4(), action, date(2027, 2, 6), time(10), time(12), retired=True
    )
    config = DeliveryConfiguration(
        action, True, windows=(past, retired_past, future, retired_future)
    )
    # 2027-02-05 12:00 UTC: both windows on the 4th are over, the 6th is ahead.
    now = datetime(2027, 2, 5, 12, tzinfo=timezone.utc)

    def complete(
        window_id: UUID | None, *, has_address: bool = True, at: datetime = now
    ) -> tuple[dict[str, str] | None, bool]:
        return config.validate_manager_completion(
            window_id=window_id, has_address=has_address, contact=None, now=at
        )

    snapshot, historical = complete(future.id)
    assert not historical and snapshot == future.snapshot(config.timezone)
    for window in (past, retired_past):
        snapshot, historical = complete(window.id)
        assert historical and snapshot == window.snapshot(config.timezone)
    # A window that has started but not ended is history, too.
    _, historical = complete(past.id, at=datetime(2027, 2, 4, 7, 30, tzinfo=timezone.utc))
    assert historical
    for selection in (retired_future.id, uuid4()):
        with pytest.raises(DomainInvariantError) as error:
            complete(selection)
        assert error.value.code == "delivery_window_unavailable"
    with pytest.raises(DomainInvariantError) as error:
        complete(past.id, has_address=False)
    assert error.value.code == "delivery_required"
    with pytest.raises(DomainInvariantError) as error:
        complete(None)
    assert error.value.code == "delivery_required"
    # Capture paths (acquisition, public order) still reject the past.
    for window in (past, retired_past):
        with pytest.raises(DomainInvariantError, match="nicht mehr verfügbar"):
            config.validate_order(
                window_id=window.id,
                has_address=True,
                contact=None,
                complete=True,
                now=now,
            )
    disabled = replace(config, enabled=False)
    with pytest.raises(DomainInvariantError) as error:
        disabled.validate_manager_completion(
            window_id=past.id, has_address=True, contact=None, now=now
        )
    assert error.value.code == "delivery_not_supported"
    assert disabled.validate_manager_completion(
        window_id=None, has_address=False, contact=None, now=now
    ) == (None, False)
