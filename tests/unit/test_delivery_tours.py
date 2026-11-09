"""Tour ordering rules: windows first, dense ranks, driver order, revision."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from leonaid.domain.delivery_board import DeliveryBoardError, DeliveryDrop, DropState
from leonaid.domain.delivery_tours import (
    TourStop,
    base_order,
    driver_order,
    effective_order,
    has_driver_order,
    new_for_driver,
    planned_positions,
    require_revision,
    stop_views,
    tour_revision,
)

DAY = datetime(2026, 12, 5, tzinfo=UTC)
EARLY = UUID(int=1)  # 08–10
LATE = UUID(int=2)  # 10–12


def stop(
    number: int,
    *,
    window: UUID = EARLY,
    base: int | None = None,
    driver: int | None = None,
    assigned_minute: int = 0,
    closed: bool = False,
) -> TourStop:
    return TourStop(
        commitment_id=UUID(int=100 + number),
        window_id=window,
        window_starts_at=DAY + timedelta(hours=8 if window == EARLY else 10),
        window_closed=closed,
        base_position=base,
        driver_position=driver,
        assigned_at=DAY + timedelta(minutes=assigned_minute),
    )


def ids(stops: tuple[TourStop, ...]) -> list[UUID]:
    return [item.commitment_id for item in stops]


def drop_for(item: TourStop) -> DeliveryDrop:
    return DeliveryDrop(
        commitment_id=item.commitment_id,
        window_id=item.window_id,
        buyer_name="Kundin",
        quantities=(),
        total_boxes=1,
        address=None,
        contact=None,
        state=DropState.OPEN,
        state_changed_at=None,
        state_changed_by_name=None,
        driver_user_id=None,
        driver_name=None,
        revision=0,
        order_status=None,
    )


def views(stops: list[TourStop]) -> dict[UUID, tuple[int, int | None, int, bool]]:
    drops = {item.commitment_id: drop_for(item) for item in stops}
    return {
        view.drop.commitment_id: (
            view.base_rank,
            view.driver_rank,
            view.effective_rank,
            view.new_for_driver,
        )
        for view in stop_views(stops, drops)
    }


def test_unranked_stops_follow_ranked_ones_by_assignment_time() -> None:
    late_unranked = stop(1, assigned_minute=30)
    ranked = stop(2, base=1, assigned_minute=50)
    early_unranked = stop(3, assigned_minute=10)
    order = base_order([late_unranked, ranked, early_unranked])
    assert ids(order) == ids((ranked, early_unranked, late_unranked))


def test_unranked_stops_with_the_same_assignment_time_follow_the_id() -> None:
    second, first = stop(2), stop(1)
    assert ids(base_order([second, first])) == ids((first, second))


def test_ranks_close_up_when_a_stop_leaves() -> None:
    stops = [stop(1, base=1), stop(3, base=3), stop(4, base=4)]
    ranks = views(stops)
    assert [ranks[item.commitment_id][0] for item in stops] == [1, 2, 3]


def test_windows_come_first_whatever_the_positions() -> None:
    early = stop(1, window=EARLY, base=9, driver=9)
    late = stop(2, window=LATE, base=1, driver=1)
    assert ids(base_order([late, early])) == ids((early, late))
    assert ids(driver_order([late, early])) == ids((early, late))
    ranks = views([late, early])
    assert ranks[early.commitment_id][0] == 1
    assert ranks[late.commitment_id][0] == 1


def test_windows_with_the_same_start_follow_the_window_id() -> None:
    first = stop(1, window=EARLY)
    other = TourStop(
        commitment_id=UUID(int=99),
        window_id=UUID(int=0),
        window_starts_at=first.window_starts_at,
        window_closed=False,
        base_position=1,
        driver_position=None,
        assigned_at=first.assigned_at,
    )
    assert ids(base_order([first, other])) == [UUID(int=99), first.commitment_id]


def test_effective_order_uses_driver_order_only_when_set() -> None:
    first = stop(1, base=1)
    second = stop(2, base=2)
    assert not has_driver_order([first, second])
    assert ids(effective_order([first, second])) == ids((first, second))
    ranks = views([first, second])
    assert ranks[first.commitment_id] == (1, None, 1, False)

    first = stop(1, base=1, driver=2)
    second = stop(2, base=2, driver=1)
    assert has_driver_order([first, second])
    assert ids(effective_order([first, second])) == ids((second, first))
    ranks = views([first, second])
    assert ranks[first.commitment_id] == (1, 2, 2, False)
    assert ranks[second.commitment_id] == (2, 1, 1, False)


def test_new_stop_is_last_and_new_for_driver() -> None:
    first = stop(1, base=1, driver=2, assigned_minute=0)
    second = stop(2, base=2, driver=1, assigned_minute=0)
    added = stop(3, assigned_minute=90)
    stops = [added, first, second]
    assert ids(base_order(stops))[-1] == added.commitment_id
    assert ids(effective_order(stops)) == ids((second, first, added))
    assert new_for_driver(added, stops)
    assert not new_for_driver(first, stops)
    assert views(stops)[added.commitment_id] == (3, 3, 3, True)
    # Without a driver order nothing is "neu".
    plain = [stop(1, base=1), stop(3)]
    assert not new_for_driver(plain[1], plain)


def test_stop_views_come_in_effective_order() -> None:
    early = stop(1, window=EARLY, base=1, driver=2)
    early_two = stop(2, window=EARLY, base=2, driver=1)
    late = stop(3, window=LATE, base=1, driver=1)
    stops = [late, early, early_two]
    drops = {item.commitment_id: drop_for(item) for item in stops}
    ordered = [view.drop.commitment_id for view in stop_views(stops, drops)]
    assert ordered == ids((early_two, early, late))


def test_planned_positions_rank_within_each_window() -> None:
    early_a, early_b = stop(1, window=EARLY), stop(2, window=EARLY)
    late_a, late_b = stop(3, window=LATE), stop(4, window=LATE)
    stops = [early_a, early_b, late_a, late_b]
    ordered = [
        late_b.commitment_id,
        early_b.commitment_id,
        late_a.commitment_id,
        early_a.commitment_id,
    ]
    for driver in (False, True):
        assert planned_positions(stops, ordered, driver=driver) == {
            early_b.commitment_id: 1,
            early_a.commitment_id: 2,
            late_b.commitment_id: 1,
            late_a.commitment_id: 2,
        }


@pytest.mark.parametrize(
    "ordered",
    [
        pytest.param([UUID(int=101)], id="missing"),
        pytest.param([UUID(int=101), UUID(int=102), uuid4()], id="extra"),
        pytest.param([UUID(int=101), UUID(int=101)], id="duplicate"),
        pytest.param(
            [UUID(int=101), UUID(int=101), UUID(int=102)], id="duplicate-complete"
        ),
        pytest.param([], id="empty"),
    ],
)
def test_planned_positions_reject_missing_extra_or_duplicate_ids(
    ordered: list[UUID],
) -> None:
    stops = [stop(1), stop(2)]
    for driver in (False, True):
        with pytest.raises(DeliveryBoardError) as refused:
            planned_positions(stops, ordered, driver=driver)
        assert refused.value.code == "tour_order_stale"
        assert refused.value.status == 409
        assert refused.value.message == "Die Tour wurde inzwischen geändert."


def test_driver_may_not_reorder_a_closed_window() -> None:
    first = stop(1, base=1, closed=True)
    second = stop(2, base=2, closed=True)
    open_a = stop(3, window=LATE, base=1)
    open_b = stop(4, window=LATE, base=2)
    stops = [first, second, open_a, open_b]
    swapped_closed = [
        second.commitment_id,
        first.commitment_id,
        open_a.commitment_id,
        open_b.commitment_id,
    ]
    with pytest.raises(DeliveryBoardError) as refused:
        planned_positions(stops, swapped_closed, driver=True)
    assert refused.value.code == "delivery_window_closed"
    assert refused.value.status == 409
    assert refused.value.message == "Dieses Lieferfenster ist abgeschlossen."

    # The manager may.
    assert planned_positions(stops, swapped_closed, driver=False) == {
        second.commitment_id: 1,
        first.commitment_id: 2,
        open_a.commitment_id: 1,
        open_b.commitment_id: 2,
    }

    # The driver may reorder the open window and keep the closed one as seen.
    swapped_open = [
        first.commitment_id,
        second.commitment_id,
        open_b.commitment_id,
        open_a.commitment_id,
    ]
    assert planned_positions(stops, swapped_open, driver=True) == {
        first.commitment_id: 1,
        second.commitment_id: 2,
        open_b.commitment_id: 1,
        open_a.commitment_id: 2,
    }


def test_driver_closed_window_check_compares_with_the_effective_order() -> None:
    # The driver's own order of the closed window differs from the base order.
    first = stop(1, base=1, driver=2, closed=True)
    second = stop(2, base=2, driver=1, closed=True)
    stops = [first, second]
    kept = [second.commitment_id, first.commitment_id]
    assert planned_positions(stops, kept, driver=True) == {
        second.commitment_id: 1,
        first.commitment_id: 2,
    }
    with pytest.raises(DeliveryBoardError) as refused:
        planned_positions(
            stops, [first.commitment_id, second.commitment_id], driver=True
        )
    assert refused.value.code == "delivery_window_closed"


def test_revision_changes_with_membership_or_positions_only() -> None:
    first = stop(1, base=1)
    second = stop(2, base=2)
    revision = tour_revision([first, second])
    assert len(revision) == 16
    assert int(revision, 16) >= 0
    # Order of the input and fields outside the revision do not matter.
    moved = TourStop(
        commitment_id=first.commitment_id,
        window_id=LATE,
        window_starts_at=first.window_starts_at + timedelta(hours=2),
        window_closed=True,
        base_position=1,
        driver_position=None,
        assigned_at=first.assigned_at + timedelta(hours=1),
    )
    assert tour_revision([second, first]) == revision
    assert tour_revision([moved, second]) == revision
    # Membership and positions do.
    assert tour_revision([first]) != revision
    assert tour_revision([first, second, stop(3)]) != revision
    assert tour_revision([first, stop(2, base=3)]) != revision
    assert tour_revision([first, stop(2, base=2, driver=1)]) != revision
    assert tour_revision([first, stop(2)]) != revision
    # No ambiguity between a missing base and a missing driver position.
    assert tour_revision([stop(1, base=1)]) != tour_revision([stop(1, driver=1)])


def test_require_revision_refuses_a_stale_revision() -> None:
    stops = [stop(1, base=1)]
    require_revision(stops, tour_revision(stops))
    with pytest.raises(DeliveryBoardError) as refused:
        require_revision(stops, tour_revision([stop(1, base=2)]))
    assert refused.value.code == "tour_revision_conflict"
    assert refused.value.status == 409
    assert refused.value.message == "Die Tour wurde inzwischen geändert."
