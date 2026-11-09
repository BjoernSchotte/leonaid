"""Delivery day board rules: who may tick which drop and what follows."""

from __future__ import annotations

from datetime import date

import pytest

from leonaid.domain.delivery_board import (
    DeliveryBoardError,
    DropState,
    StateChange,
    board_day,
    decide_state_change,
)

OPEN, DELIVERED, MISSED = DropState.OPEN, DropState.DELIVERED, DropState.MISSED


def change(**overrides: object) -> StateChange | None:
    arguments: dict[str, object] = {
        "current": OPEN,
        "delivered": True,
        "window_closed": False,
        "manager": False,
        "assigned_driver": True,
    }
    arguments.update(overrides)
    return decide_state_change(**arguments)  # type: ignore[arg-type]


def test_assigned_driver_ticks_and_undoes_in_an_open_window() -> None:
    assert change() == StateChange(new_state=DELIVERED, follow_up_needed=None)
    assert change(current=DELIVERED, delivered=False) == StateChange(
        new_state=OPEN, follow_up_needed=None
    )


def test_the_same_target_twice_is_a_no_op() -> None:
    assert change(current=DELIVERED, delivered=True) is None
    assert change(current=OPEN, delivered=False) is None
    assert (
        change(
            current=MISSED,
            delivered=False,
            window_closed=True,
            manager=True,
            assigned_driver=False,
        )
        is None
    )


def test_others_may_not_tick_a_drop_that_is_not_theirs() -> None:
    with pytest.raises(DeliveryBoardError) as refused:
        change(assigned_driver=False)
    assert refused.value.code == "delivery_not_assigned"
    assert refused.value.status == 403


def test_managers_tick_any_drop() -> None:
    assert change(manager=True, assigned_driver=False) == StateChange(
        new_state=DELIVERED, follow_up_needed=None
    )


def test_drivers_cannot_change_a_closed_window() -> None:
    with pytest.raises(DeliveryBoardError) as refused:
        change(current=MISSED, window_closed=True)
    assert refused.value.code == "delivery_window_closed"
    assert refused.value.status == 409


def test_a_later_delivery_closes_the_follow_up_and_its_undo_reopens_it() -> None:
    later = change(
        current=MISSED, window_closed=True, manager=True, assigned_driver=False
    )
    assert later == StateChange(new_state=DELIVERED, follow_up_needed=False)
    undone = change(
        current=DELIVERED,
        delivered=False,
        window_closed=True,
        manager=True,
        assigned_driver=False,
        missed_at_closure=True,
    )
    assert undone == StateChange(new_state=MISSED, follow_up_needed=True)


def test_a_regular_delivery_in_a_closed_window_needs_a_reopen_to_undo() -> None:
    with pytest.raises(DeliveryBoardError) as refused:
        change(
            current=DELIVERED,
            delivered=False,
            window_closed=True,
            manager=True,
            assigned_driver=False,
            missed_at_closure=False,
        )
    assert refused.value.code == "delivery_window_closed"
    assert refused.value.status == 409


def test_managers_tick_an_open_drop_in_a_closed_window_without_follow_up() -> None:
    # Booked into the window after it was closed (historical completion).
    assert change(
        current=OPEN, window_closed=True, manager=True, assigned_driver=False
    ) == StateChange(new_state=DELIVERED, follow_up_needed=None)
    # Drivers still cannot.
    with pytest.raises(DeliveryBoardError) as refused:
        change(current=OPEN, window_closed=True)
    assert refused.value.code == "delivery_window_closed"
    # Taking an open drop "back" is a no-op.
    assert (
        change(
            current=OPEN,
            delivered=False,
            window_closed=True,
            manager=True,
            assigned_driver=False,
        )
        is None
    )


def test_driver_marks_missed_in_an_open_window_and_withdraws_it() -> None:
    # Spec D13: "Nicht angetroffen" during the day, same rule as delivered.
    assert change(delivered=False, missed=True) == StateChange(
        new_state=MISSED, follow_up_needed=None
    )
    assert change(current=MISSED, delivered=False) == StateChange(
        new_state=OPEN, follow_up_needed=None
    )
    assert change(current=MISSED, delivered=False, missed=True) is None
    # Found on a second try: missed becomes delivered, and back.
    assert change(current=MISSED) == StateChange(
        new_state=DELIVERED, follow_up_needed=None
    )
    assert change(current=DELIVERED, delivered=False, missed=True) == StateChange(
        new_state=MISSED, follow_up_needed=None
    )
    assert change(
        delivered=False, missed=True, manager=True, assigned_driver=False
    ) == StateChange(new_state=MISSED, follow_up_needed=None)


def test_others_may_not_mark_a_drop_missed() -> None:
    with pytest.raises(DeliveryBoardError) as refused:
        change(delivered=False, missed=True, assigned_driver=False)
    assert refused.value.code == "delivery_not_assigned"


def test_only_the_closure_marks_missed_in_a_closed_window() -> None:
    for manager in (False, True):
        with pytest.raises(DeliveryBoardError) as refused:
            change(
                delivered=False,
                missed=True,
                window_closed=True,
                manager=manager,
                assigned_driver=not manager,
            )
        assert refused.value.code == "delivery_window_closed"
    assert (
        change(
            current=MISSED,
            delivered=False,
            missed=True,
            window_closed=True,
            manager=True,
            assigned_driver=False,
        )
        is None
    )


def test_a_drop_cannot_be_delivered_and_missed_at_once() -> None:
    with pytest.raises(ValueError):
        change(delivered=True, missed=True)


@pytest.mark.parametrize(
    ("days", "requested", "today", "expected"),
    [
        ((), None, date(2026, 11, 4), None),
        (
            (date(2026, 11, 4), date(2026, 11, 5)),
            None,
            date(2026, 11, 4),
            date(2026, 11, 4),
        ),
        (
            (date(2026, 11, 6), date(2026, 11, 9)),
            None,
            date(2026, 11, 4),
            date(2026, 11, 6),
        ),
        (
            (date(2026, 11, 1), date(2026, 11, 2)),
            None,
            date(2026, 11, 4),
            date(2026, 11, 2),
        ),
        (
            (date(2026, 11, 1), date(2026, 11, 2)),
            date(2026, 11, 1),
            date(2026, 11, 4),
            date(2026, 11, 1),
        ),
        (
            (date(2026, 11, 1),),
            date(2026, 12, 24),
            date(2026, 11, 4),
            date(2026, 11, 1),
        ),
    ],
)
def test_board_day_prefers_the_requested_then_today_then_the_next_day(
    days: tuple[date, ...], requested: date | None, today: date, expected: date | None
) -> None:
    assert board_day(days, requested, today) == expected
