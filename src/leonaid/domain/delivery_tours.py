"""Delivery tours: the order of one driver's stops on one delivery day.

A tour is driver × delivery day, with no own table. Its stops are grouped by
window and ordered inside each window only, so reordering never breaks a
customer's promised slot. The manager owns the base order; the driver may
keep their own order beside it. Positions are stored per stop and may have
gaps (a stop left the tour); ranks are always dense ``1..n`` per window.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from leonaid.domain.delivery_board import BoardDriver, DeliveryBoardError, DeliveryDrop

TOUR_CHANGED_MESSAGE = "Die Tour wurde inzwischen geändert."
WINDOW_CLOSED_MESSAGE = "Dieses Lieferfenster ist abgeschlossen."


@dataclass(frozen=True, slots=True)
class TourStop:
    """What ordering needs to know of one stop."""

    commitment_id: UUID
    window_id: UUID
    window_starts_at: datetime
    window_closed: bool
    base_position: int | None
    driver_position: int | None
    # When the stop joined this tour; orders stops that have no position yet.
    assigned_at: datetime


@dataclass(frozen=True, slots=True)
class TourStopView:
    drop: DeliveryDrop
    base_rank: int
    # None while the driver has no own order.
    driver_rank: int | None
    effective_rank: int
    # Joined after the driver made their own order ("neu").
    new_for_driver: bool


@dataclass(frozen=True, slots=True)
class TourWindow:
    window_id: UUID
    starts_at: datetime
    ends_at: datetime
    closed: bool
    stops: tuple[TourStopView, ...]


@dataclass(frozen=True, slots=True)
class DriverTour:
    driver_user_id: UUID
    driver_name: str
    day: date
    revision: str
    driver_ordered_at: datetime | None
    windows: tuple[TourWindow, ...]


@dataclass(frozen=True, slots=True)
class DayTours:
    """Manager view of one delivery day: unassigned stops and every tour."""

    action_id: UUID
    action_name: str
    timezone: str
    day: date | None
    days: tuple[date, ...]
    unassigned: tuple[TourWindow, ...]
    tours: tuple[DriverTour, ...]
    drivers: tuple[BoardDriver, ...]


@dataclass(frozen=True, slots=True)
class MyTour:
    """Driver view: their own tour of one day, if they have stops."""

    action_id: UUID
    action_name: str
    timezone: str
    days: tuple[date, ...]
    tour: DriverTour | None


def tour_order_stale() -> DeliveryBoardError:
    """The submitted ids are not exactly the tour's stops."""

    return DeliveryBoardError("tour_order_stale", TOUR_CHANGED_MESSAGE)


def tour_revision_conflict() -> DeliveryBoardError:
    return DeliveryBoardError("tour_revision_conflict", TOUR_CHANGED_MESSAGE)


def _window_key(stop: TourStop) -> tuple[datetime, UUID]:
    return (stop.window_starts_at, stop.window_id)


def _ordered(stops: Sequence[TourStop], position: str) -> tuple[TourStop, ...]:
    def key(stop: TourStop) -> tuple[datetime, UUID, bool, int, datetime, UUID]:
        value: int | None = getattr(stop, position)
        return (
            *_window_key(stop),
            value is None,
            0 if value is None else value,
            stop.assigned_at,
            stop.commitment_id,
        )

    return tuple(sorted(stops, key=key))


def base_order(stops: Sequence[TourStop]) -> tuple[TourStop, ...]:
    """Windows by start, then the manager's positions; unranked stops last."""

    return _ordered(stops, "base_position")


def driver_order(stops: Sequence[TourStop]) -> tuple[TourStop, ...]:
    """Windows by start, then the driver's positions; new stops last."""

    return _ordered(stops, "driver_position")


def has_driver_order(stops: Sequence[TourStop]) -> bool:
    return any(stop.driver_position is not None for stop in stops)


def effective_order(stops: Sequence[TourStop]) -> tuple[TourStop, ...]:
    return driver_order(stops) if has_driver_order(stops) else base_order(stops)


def new_for_driver(stop: TourStop, stops: Sequence[TourStop]) -> bool:
    return has_driver_order(stops) and stop.driver_position is None


def _ranks(ordered: Sequence[TourStop]) -> dict[UUID, int]:
    """Dense ranks 1..n per window of an already ordered tour."""

    ranks: dict[UUID, int] = {}
    counts: Counter[UUID] = Counter()
    for stop in ordered:
        counts[stop.window_id] += 1
        ranks[stop.commitment_id] = counts[stop.window_id]
    return ranks


def tour_revision(stops: Sequence[TourStop]) -> str:
    """Changes exactly when membership or a stored position changes."""

    def part(value: int | None) -> str:
        return "-" if value is None else str(value)

    lines = sorted(
        f"{stop.commitment_id}:{part(stop.base_position)}:{part(stop.driver_position)}"
        for stop in stops
    )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def require_revision(stops: Sequence[TourStop], expected_revision: str) -> None:
    if tour_revision(stops) != expected_revision:
        raise tour_revision_conflict()


def planned_positions(
    stops: Sequence[TourStop], ordered_ids: Sequence[UUID], *, driver: bool
) -> dict[UUID, int]:
    """The new dense positions per window for a whole-tour order write.

    ``ordered_ids`` must name every stop of the tour exactly once; ids may
    interleave windows, only their relative order inside a window counts.
    A driver may not change the order they see (the effective order) of a
    closed window; a manager may. Resetting a driver order (an empty driver
    write) is the caller's job, not a plan.
    """

    by_id = {stop.commitment_id: stop for stop in stops}
    if len(ordered_ids) != len(by_id) or set(ordered_ids) != by_id.keys():
        raise tour_order_stale()
    index = {commitment_id: i for i, commitment_id in enumerate(ordered_ids)}
    planned = _ranks(
        sorted(
            stops,
            key=lambda stop: (*_window_key(stop), index[stop.commitment_id]),
        )
    )
    if driver:
        seen = _ranks(effective_order(stops))
        if any(
            stop.window_closed
            and planned[stop.commitment_id] != seen[stop.commitment_id]
            for stop in stops
        ):
            raise DeliveryBoardError("delivery_window_closed", WINDOW_CLOSED_MESSAGE)
    return planned


def stop_views(
    stops: Sequence[TourStop], drops: Mapping[UUID, DeliveryDrop]
) -> tuple[TourStopView, ...]:
    """Read models of a tour's stops in effective order, with dense ranks."""

    driver_set = has_driver_order(stops)
    base = _ranks(base_order(stops))
    own = _ranks(driver_order(stops)) if driver_set else {}
    ordered = effective_order(stops)
    effective = _ranks(ordered)
    return tuple(
        TourStopView(
            drop=drops[stop.commitment_id],
            base_rank=base[stop.commitment_id],
            driver_rank=own.get(stop.commitment_id),
            effective_rank=effective[stop.commitment_id],
            new_for_driver=driver_set and stop.driver_position is None,
        )
        for stop in ordered
    )
