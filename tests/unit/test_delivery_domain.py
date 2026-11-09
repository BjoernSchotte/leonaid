from dataclasses import replace
from datetime import date, datetime, time, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.domain.delivery import (
    DeliveryConfiguration,
    DeliveryStartPoint,
    DeliveryWindow,
    local_instant,
    merged_start,
)
from leonaid.domain.delivery_geo import GeoPoint
from leonaid.domain.errors import DomainInvariantError
from leonaid.entrypoints.fastapi.routes import requested_start_point
from leonaid.entrypoints.fastapi.schemas import DeliveryConfigurationRequest


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
    _, historical = complete(
        past.id, at=datetime(2027, 2, 4, 7, 30, tzinfo=timezone.utc)
    )
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


BAKERY = DeliveryStartPoint(
    "Bäckerei", "Marktstraße 50, 83646 Bad Tölz", GeoPoint.parse("47.76", "11.56")
)


def _request(**extra: object) -> DeliveryConfigurationRequest:
    return DeliveryConfigurationRequest.model_validate(
        {
            "expectedRevision": 1,
            "enabled": True,
            "timezone": "Europe/Berlin",
            "windows": [],
            **extra,
        }
    )


def test_absent_start_point_keeps_stored_one() -> None:
    action = uuid4()
    stored = DeliveryConfiguration(action, start=BAKERY)
    # Absent: the stored start point stays, point included.
    assert requested_start_point(_request(), stored) == BAKERY
    # Explicit null clears it.
    assert requested_start_point(_request(startPoint=None), stored) is None
    # Same address without a point: the stored point (geocoded or pinned) stays.
    renamed = requested_start_point(
        _request(startPoint={"label": "Backstube", "address": BAKERY.address}),
        stored,
    )
    assert renamed == DeliveryStartPoint("Backstube", BAKERY.address, None)
    assert merged_start(BAKERY, renamed) == replace(renamed, point=BAKERY.point)
    # A new address without a point drops the old point; the worker looks it up.
    moved = DeliveryStartPoint("Bäckerei", "Marktstraße 27, 83646 Bad Tölz", None)
    assert merged_start(BAKERY, moved) == moved
    # A point given by hand wins.
    pinned = replace(moved, point=GeoPoint.parse("47.7601", "11.5602"))
    assert merged_start(BAKERY, pinned) == pinned
    assert merged_start(None, moved) == moved and merged_start(BAKERY, None) is None
    given = requested_start_point(
        _request(
            startPoint={"label": "B", "address": "A 1", "lat": 47.5, "lon": 11.25}
        ),
        stored,
    )
    assert given is not None and given.point == GeoPoint.parse("47.5", "11.25")


@pytest.mark.parametrize(
    ("label", "address"),
    [
        ("", "Marktstraße 50"),
        ("   ", "Marktstraße 50"),
        ("Bäckerei", ""),
        ("Bäcker\nei", "Marktstraße 50"),
        ("Bäckerei", "Marktstraße 50\r\n83646 Bad Tölz"),
        ("Bäckerei", "Marktstraße\u2028 50"),
        ("Bäckerei", "Markt\tstraße 50"),
        ("B" * 81, "Marktstraße 50"),
        ("Bäckerei", "M" * 201),
    ],
)
def test_start_point_rejects_multiline_and_long_values(
    label: str, address: str
) -> None:
    with pytest.raises(DomainInvariantError) as error:
        DeliveryStartPoint(label, address, None)
    assert error.value.code == "delivery_start_invalid"


def test_start_point_trims_and_accepts_limits() -> None:
    start = DeliveryStartPoint(" " + "B" * 80 + " ", "  " + "M" * 200, None)
    assert start.label == "B" * 80 and start.address == "M" * 200


def test_start_point_request_needs_both_coordinates() -> None:
    with pytest.raises(ValueError):
        _request(startPoint={"label": "B", "address": "A", "lat": 47.5})
    with pytest.raises(ValueError):
        _request(startPoint={"label": "B", "address": "A", "lat": 91, "lon": 1})
