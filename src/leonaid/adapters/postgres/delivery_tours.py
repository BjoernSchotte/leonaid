"""Delivery tours in PostgreSQL: one driver's stops of one delivery day.

A tour has no table: its stops are the board's drops of the day's windows
with ``commitment_delivery.driver_user_id`` set to the driver. Their order is
stored per stop (``base_position``, ``driver_position``). Lock order of a
write (retry.py): the day's windows ``FOR SHARE``, then the tour's orders
``FOR SHARE`` and their delivery rows ``FOR UPDATE``, each in id order. A
closure (window ``FOR UPDATE``) and an assignment (order ``FOR UPDATE``)
therefore wait for a running tour write, and the other way round.

Stops carry the coordinates of their current address (``delivery_geo``, a
stale row is left out); both reads carry the action's start point. A manual
pin locks the order ``FOR SHARE`` before its ``delivery_geo`` row, the same
order as the geocoding job.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime
from typing import Any, TypeVar
from uuid import UUID

import asyncpg

from leonaid.adapters.postgres.delivery import read_start
from leonaid.adapters.postgres.delivery_geo import (
    current_address_hash,
    current_points,
    write_manual_pin,
)
from leonaid.adapters.postgres.privacy import ERASED_RECIPIENT_NAME
from leonaid.adapters.postgres.delivery_board import (
    action_context,
    active_drivers,
    fetch_drops,
    insert_audit,
    record_read_audit,
)
from leonaid.adapters.postgres.retry import (
    RETRYABLE_ERRORS,
    SERIALIZABLE_ATTEMPTS,
    serialization_pause,
)
from leonaid.application.errors import ResourceNotFound
from leonaid.domain.calendar import local_day
from leonaid.domain.delivery_board import (
    DELIVERABLE_ORDER_STATUSES,
    DeliveryBoardError,
    DeliveryDrop,
    board_day,
)
from leonaid.domain.delivery_geo import GeoPoint
from leonaid.domain.delivery_tours import (
    DayTours,
    DriverTour,
    MyTour,
    TourStop,
    TourStopView,
    TourWindow,
    has_driver_order,
    planned_positions,
    require_revision,
    stop_views,
    tour_revision,
)

_DELIVERABLE = sorted(DELIVERABLE_ORDER_STATUSES)
_T = TypeVar("_T")


async def _day_windows(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    zone_key: str,
    day: date,
    lock: bool,
) -> dict[UUID, asyncpg.Record]:
    """The action's windows that start on ``day`` in the action's zone."""

    rows = await connection.fetch(
        f"""
        SELECT window_row.id, window_row.starts_at, window_row.ends_at,
            window_row.retired,
            EXISTS (
                SELECT 1 FROM delivery_window_closure
                WHERE window_id = window_row.id
            ) AS closed
        FROM action_delivery_window AS window_row
        WHERE window_row.action_id = $1
          AND (window_row.starts_at AT TIME ZONE $2::text)::date = $3
        ORDER BY window_row.id
        {"FOR SHARE OF window_row" if lock else ""}
        """,
        action_id,
        zone_key,
        day,
    )
    return {row["id"]: row for row in rows}


async def _positions(
    connection: asyncpg.Connection[Any],
    *,
    commitment_ids: Sequence[UUID],
    driver_user_id: UUID | None,
    lock: bool,
) -> dict[UUID, asyncpg.Record]:
    if lock:
        # The orders first (lock order), so their status, window and
        # driver cannot change under the write.
        await connection.execute(
            """
            SELECT id FROM commitment WHERE id = ANY($1::uuid[])
            ORDER BY id FOR SHARE
            """,
            list(commitment_ids),
        )
    rows = await connection.fetch(
        f"""
        SELECT commitment_id, driver_user_id, driver_assigned_at,
            base_position, driver_position, driver_ordered_at
        FROM commitment_delivery
        WHERE commitment_id = ANY($1::uuid[])
          AND ($2::uuid IS NULL OR driver_user_id = $2)
        ORDER BY commitment_id
        {"FOR UPDATE" if lock else ""}
        """,
        list(commitment_ids),
        driver_user_id,
    )
    return {row["commitment_id"]: row for row in rows}


def _tour_stop(
    drop: DeliveryDrop, window: asyncpg.Record, position: asyncpg.Record
) -> TourStop:
    return TourStop(
        commitment_id=drop.commitment_id,
        window_id=drop.window_id,
        window_starts_at=window["starts_at"],
        window_closed=bool(window["closed"]),
        base_position=position["base_position"],
        driver_position=position["driver_position"],
        assigned_at=position["driver_assigned_at"] or window["starts_at"],
    )


def _grouped(
    views: Sequence[TourStopView], windows: dict[UUID, asyncpg.Record]
) -> tuple[TourWindow, ...]:
    """Views (already sorted by window) grouped into their windows."""

    groups: dict[UUID, list[TourStopView]] = {}
    for view in views:
        groups.setdefault(view.drop.window_id, []).append(view)
    return tuple(
        TourWindow(
            window_id=window_id,
            starts_at=windows[window_id]["starts_at"],
            ends_at=windows[window_id]["ends_at"],
            closed=bool(windows[window_id]["closed"]),
            stops=tuple(stops),
        )
        for window_id, stops in sorted(
            groups.items(),
            key=lambda item: (windows[item[0]]["starts_at"], item[0]),
        )
    )


def _driver_tour(
    *,
    driver_user_id: UUID,
    driver_name: str,
    day: date,
    windows: dict[UUID, asyncpg.Record],
    drops: Sequence[DeliveryDrop],
    positions: dict[UUID, asyncpg.Record],
    points: dict[UUID, GeoPoint],
) -> tuple[DriverTour, tuple[TourStop, ...]]:
    stops = tuple(
        _tour_stop(drop, windows[drop.window_id], positions[drop.commitment_id])
        for drop in drops
    )
    ordered_at = [
        positions[stop.commitment_id]["driver_ordered_at"]
        for stop in stops
        if stop.driver_position is not None
        and positions[stop.commitment_id]["driver_ordered_at"] is not None
    ]
    views = stop_views(stops, {drop.commitment_id: drop for drop in drops}, points)
    tour = DriverTour(
        driver_user_id=driver_user_id,
        driver_name=driver_name,
        day=day,
        revision=tour_revision(stops),
        driver_ordered_at=max(ordered_at) if ordered_at else None,
        windows=_grouped(views, windows),
    )
    return tour, stops


def _unassigned(
    drops: Sequence[DeliveryDrop],
    windows: dict[UUID, asyncpg.Record],
    points: dict[UUID, GeoPoint],
) -> tuple[TourWindow, ...]:
    """Stops without a driver, by window, in the board's order."""

    counts: dict[UUID, int] = {}
    views: list[TourStopView] = []
    for drop in drops:
        counts[drop.window_id] = counts.get(drop.window_id, 0) + 1
        rank = counts[drop.window_id]
        views.append(
            TourStopView(
                drop=drop,
                base_rank=rank,
                driver_rank=None,
                effective_rank=rank,
                new_for_driver=False,
                point=points.get(drop.commitment_id),
            )
        )
    return _grouped(views, windows)


async def _driver_name(
    connection: asyncpg.Connection[Any], driver_user_id: UUID
) -> str:
    name = await connection.fetchval(
        "SELECT display_name FROM user_account WHERE id = $1", driver_user_id
    )
    if name is None:
        raise ResourceNotFound(
            "delivery_driver_not_found", "Diese Person wurde nicht gefunden."
        )
    return str(name)


class AsyncpgDeliveryTourRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    # ---------- reads ----------

    async def _tour(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        driver_user_id: UUID,
        driver_name: str,
        day: date,
        windows: dict[UUID, asyncpg.Record],
        manager: bool,
        lock: bool = False,
    ) -> tuple[DriverTour, tuple[TourStop, ...]]:
        """One tour; ``manager`` gives the manager's drop fields (P3)."""

        if lock:
            candidates = await connection.fetch(
                """
                SELECT commitment.id FROM commitment
                JOIN commitment_delivery AS delivery
                  ON delivery.commitment_id = commitment.id
                WHERE commitment.action_id = $1
                  AND commitment.delivery_window_id = ANY($2::uuid[])
                  AND commitment.status = ANY($3::text[])
                  AND delivery.driver_user_id = $4
                """,
                action_id,
                list(windows),
                _DELIVERABLE,
                driver_user_id,
            )
            positions = await _positions(
                connection,
                commitment_ids=sorted(row["id"] for row in candidates),
                driver_user_id=driver_user_id,
                lock=True,
            )
        drops = [
            drop
            for drop in await fetch_drops(
                connection,
                action_id=action_id,
                window_ids=list(windows),
                driver_user_id=driver_user_id,
                manager=manager,
            )
            # Cancelled-but-delivered drops stay on the manager's board,
            # not in a tour.
            if not manager or drop.order_status in DELIVERABLE_ORDER_STATUSES
        ]
        if lock:
            # Locked rows decide; an order assigned since then joins later.
            drops = [drop for drop in drops if drop.commitment_id in positions]
        else:
            positions = await _positions(
                connection,
                commitment_ids=[drop.commitment_id for drop in drops],
                driver_user_id=driver_user_id,
                lock=False,
            )
        return _driver_tour(
            driver_user_id=driver_user_id,
            driver_name=driver_name,
            day=day,
            windows=windows,
            drops=drops,
            positions=positions,
            points=await current_points(
                connection, [drop.commitment_id for drop in drops]
            ),
        )

    async def day_tours(
        self, *, action_id: UUID, day: date | None, viewed_at: datetime
    ) -> DayTours:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                action_name, zone = await action_context(connection, action_id)
                # As on the board: days of active windows or windows with drops.
                rows = await connection.fetch(
                    """
                    SELECT window_row.starts_at
                    FROM action_delivery_window AS window_row
                    WHERE window_row.action_id = $1
                      AND (NOT window_row.retired OR EXISTS (
                          SELECT 1 FROM commitment
                          WHERE commitment.delivery_window_id = window_row.id
                            AND commitment.status = ANY($2::text[])
                      ))
                    """,
                    action_id,
                    _DELIVERABLE,
                )
                days = tuple(
                    sorted({local_day(row["starts_at"], zone) for row in rows})
                )
                selected = board_day(days, day, local_day(viewed_at, zone))
                drivers = await active_drivers(connection, action_id)
                start = await read_start(connection, action_id)
                if selected is None:
                    return DayTours(
                        action_id=action_id,
                        action_name=action_name,
                        timezone=zone.key,
                        day=None,
                        days=days,
                        unassigned=(),
                        tours=(),
                        drivers=drivers,
                        start=start,
                    )
                windows = await _day_windows(
                    connection,
                    action_id=action_id,
                    zone_key=zone.key,
                    day=selected,
                    lock=False,
                )
                drops = [
                    drop
                    for drop in await fetch_drops(
                        connection,
                        action_id=action_id,
                        window_ids=list(windows),
                        driver_user_id=None,
                        manager=True,
                    )
                    if drop.order_status in DELIVERABLE_ORDER_STATUSES
                ]
                positions = await _positions(
                    connection,
                    commitment_ids=[
                        drop.commitment_id
                        for drop in drops
                        if drop.driver_user_id is not None
                    ],
                    driver_user_id=None,
                    lock=False,
                )
                points = await current_points(
                    connection, [drop.commitment_id for drop in drops]
                )
        names = {driver.user_id: driver.display_name for driver in drivers}
        by_driver: dict[UUID, list[DeliveryDrop]] = {driver: [] for driver in names}
        for drop in drops:
            if drop.driver_user_id is not None:
                by_driver.setdefault(drop.driver_user_id, []).append(drop)
                # A former driver still holding stops keeps their tour.
                names.setdefault(drop.driver_user_id, drop.driver_name or "")
        tours = sorted(
            (
                _driver_tour(
                    driver_user_id=driver_user_id,
                    driver_name=names[driver_user_id],
                    day=selected,
                    windows=windows,
                    drops=held,
                    positions=positions,
                    points=points,
                )[0]
                for driver_user_id, held in by_driver.items()
            ),
            key=lambda tour: (tour.driver_name, tour.driver_user_id),
        )
        return DayTours(
            action_id=action_id,
            action_name=action_name,
            timezone=zone.key,
            day=selected,
            days=days,
            unassigned=_unassigned(
                [drop for drop in drops if drop.driver_user_id is None],
                windows,
                points,
            ),
            tours=tuple(tours),
            drivers=drivers,
            start=start,
        )

    async def my_tour(
        self,
        *,
        action_id: UUID,
        driver_user_id: UUID,
        day: date | None,
        viewed_at: datetime,
    ) -> MyTour:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                action_name, zone = await action_context(connection, action_id)
                # Only days where the driver holds stops.
                rows = await connection.fetch(
                    """
                    SELECT DISTINCT window_row.starts_at
                    FROM action_delivery_window AS window_row
                    JOIN commitment
                      ON commitment.delivery_window_id = window_row.id
                    JOIN commitment_delivery AS delivery
                      ON delivery.commitment_id = commitment.id
                    WHERE window_row.action_id = $1
                      AND commitment.status = ANY($2::text[])
                      AND delivery.driver_user_id = $3
                    """,
                    action_id,
                    _DELIVERABLE,
                    driver_user_id,
                )
                days = tuple(
                    sorted({local_day(row["starts_at"], zone) for row in rows})
                )
                selected = board_day(days, day, local_day(viewed_at, zone))
                start = await read_start(connection, action_id)
                tour: DriverTour | None = None
                if selected is not None:
                    windows = await _day_windows(
                        connection,
                        action_id=action_id,
                        zone_key=zone.key,
                        day=selected,
                        lock=False,
                    )
                    tour, _ = await self._tour(
                        connection,
                        action_id=action_id,
                        driver_user_id=driver_user_id,
                        driver_name=await _driver_name(connection, driver_user_id),
                        day=selected,
                        windows=windows,
                        manager=False,
                    )
                    await record_read_audit(
                        connection,
                        driver_user_id=driver_user_id,
                        action_id=action_id,
                        window_ids=[item.window_id for item in tour.windows],
                        viewed_at=viewed_at,
                        zone=zone,
                    )
        return MyTour(
            action_id=action_id,
            action_name=action_name,
            timezone=zone.key,
            days=days,
            tour=tour,
            start=start,
        )

    # ---------- writes ----------

    async def _write(
        self, command: Callable[[asyncpg.Connection[Any]], Awaitable[_T]]
    ) -> _T:
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
                try:
                    async with connection.transaction():
                        return await command(connection)
                except RETRYABLE_ERRORS:
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise DeliveryBoardError(
                            "delivery_concurrent_retry",
                            "Die Tour wurde gleichzeitig geändert. Bitte erneut "
                            "speichern.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Tour wurde nicht gespeichert.")

    async def _locked(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        driver_user_id: UUID,
        day: date,
        manager: bool,
    ) -> tuple[DriverTour, tuple[TourStop, ...], dict[UUID, asyncpg.Record]]:
        _, zone = await action_context(connection, action_id)
        driver_name = await _driver_name(connection, driver_user_id)
        windows = await _day_windows(
            connection, action_id=action_id, zone_key=zone.key, day=day, lock=True
        )
        tour, stops = await self._tour(
            connection,
            action_id=action_id,
            driver_user_id=driver_user_id,
            driver_name=driver_name,
            day=day,
            windows=windows,
            manager=manager,
            lock=True,
        )
        return tour, stops, windows

    async def save_order(
        self,
        *,
        action_id: UUID,
        driver_user_id: UUID,
        day: date,
        ordered_ids: Sequence[UUID],
        expected_revision: str,
        driver: bool,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> DriverTour:
        column = "driver_position" if driver else "base_position"

        async def command(connection: asyncpg.Connection[Any]) -> DriverTour:
            tour, stops, windows = await self._locked(
                connection,
                action_id=action_id,
                driver_user_id=driver_user_id,
                day=day,
                manager=not driver,
            )
            planned = planned_positions(stops, ordered_ids, driver=driver)
            stored = {stop.commitment_id: getattr(stop, column) for stop in stops}
            # Idempotent by target state: a repeated write changes nothing,
            # whatever revision it carries.
            if planned == stored:
                return tour
            require_revision(stops, expected_revision)
            ids = list(planned)
            await connection.execute(
                f"""
                UPDATE commitment_delivery AS delivery
                SET {column} = item.position
                    {", driver_ordered_at = $3" if driver else ""}
                FROM unnest($1::uuid[], $2::int[]) AS item(id, position)
                WHERE delivery.commitment_id = item.id
                """,
                ids,
                [planned[commitment_id] for commitment_id in ids],
                *((occurred_at,) if driver else ()),
            )
            await insert_audit(
                connection,
                action_id=action_id,
                actor_user_id=actor_user_id,
                event_type="delivery.tour_order_saved",
                entity_type="charity_action",
                entity_id=action_id,
                request_id=request_id,
                payload={
                    "driverUserId": str(driver_user_id),
                    "day": day.isoformat(),
                    "stopCount": len(stops),
                    "kind": "driver" if driver else "base",
                },
                occurred_at=occurred_at,
            )
            updated, _ = await self._tour(
                connection,
                action_id=action_id,
                driver_user_id=driver_user_id,
                driver_name=tour.driver_name,
                day=day,
                windows=windows,
                manager=not driver,
            )
            return updated

        return await self._write(command)

    async def discard_driver_order(
        self,
        *,
        action_id: UUID,
        driver_user_id: UUID,
        day: date,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        driver: bool = False,
    ) -> DriverTour:
        """Back to the base order. ``driver``: the driver resets their own
        order ("Zurück zur Planung") and gets the driver's view."""

        async def command(connection: asyncpg.Connection[Any]) -> DriverTour:
            tour, stops, windows = await self._locked(
                connection,
                action_id=action_id,
                driver_user_id=driver_user_id,
                day=day,
                manager=not driver,
            )
            if not has_driver_order(stops):
                return tour
            await connection.execute(
                """
                UPDATE commitment_delivery
                SET driver_position = NULL, driver_ordered_at = NULL
                WHERE commitment_id = ANY($1::uuid[])
                """,
                [stop.commitment_id for stop in stops],
            )
            await insert_audit(
                connection,
                action_id=action_id,
                actor_user_id=actor_user_id,
                event_type="delivery.driver_order_discarded",
                entity_type="charity_action",
                entity_id=action_id,
                request_id=request_id,
                payload={
                    "driverUserId": str(driver_user_id),
                    "day": day.isoformat(),
                    "stopCount": len(stops),
                },
                occurred_at=occurred_at,
            )
            updated, _ = await self._tour(
                connection,
                action_id=action_id,
                driver_user_id=driver_user_id,
                driver_name=tour.driver_name,
                day=day,
                windows=windows,
                manager=not driver,
            )
            return updated

        return await self._write(command)

    async def set_pin(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        point: GeoPoint,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> TourStopView:
        """The manager's pin for a stop of this action (spec §6.4).

        Only an order on the board can be pinned: deliverable, in a window,
        with an address, not erased. The audit names ids only.
        """

        async def command(connection: asyncpg.Connection[Any]) -> TourStopView:
            _, zone = await action_context(connection, action_id)
            digest = await current_address_hash(connection, action_id, commitment_id)
            row = await connection.fetchrow(
                """
                SELECT commitment.status,
                    commitment.delivery_recipient_snapshot ->> 'recipientName'
                        AS recipient,
                    window_row.starts_at, delivery.driver_user_id
                FROM commitment
                JOIN action_delivery_window AS window_row
                  ON window_row.id = commitment.delivery_window_id
                LEFT JOIN commitment_delivery AS delivery
                  ON delivery.commitment_id = commitment.id
                WHERE commitment.id = $1 AND commitment.action_id = $2
                """,
                commitment_id,
                action_id,
            )
            if (
                digest is None
                or row is None
                or row["status"] not in DELIVERABLE_ORDER_STATUSES
                or row["recipient"] == ERASED_RECIPIENT_NAME
            ):
                raise ResourceNotFound(
                    "delivery_drop_not_found",
                    "Diese Lieferung wurde nicht gefunden.",
                )
            await write_manual_pin(
                connection,
                action_id=action_id,
                commitment_id=commitment_id,
                point=point,
                address_digest=digest,
                at=occurred_at,
            )
            # Coordinates are personal data: ids only (spec §10).
            await insert_audit(
                connection,
                action_id=action_id,
                actor_user_id=actor_user_id,
                event_type="delivery.pin_set",
                entity_type="commitment",
                entity_id=commitment_id,
                request_id=request_id,
                payload={"commitmentId": str(commitment_id)},
                occurred_at=occurred_at,
            )
            day = local_day(row["starts_at"], zone)
            windows = await _day_windows(
                connection, action_id=action_id, zone_key=zone.key, day=day, lock=False
            )
            driver_user_id = row["driver_user_id"]
            if driver_user_id is not None:
                tour, _ = await self._tour(
                    connection,
                    action_id=action_id,
                    driver_user_id=driver_user_id,
                    driver_name=await _driver_name(connection, driver_user_id),
                    day=day,
                    windows=windows,
                    manager=True,
                )
                groups = tour.windows
            else:
                drops = [
                    drop
                    for drop in await fetch_drops(
                        connection,
                        action_id=action_id,
                        window_ids=list(windows),
                        driver_user_id=None,
                        manager=True,
                    )
                    if drop.driver_user_id is None
                    and drop.order_status in DELIVERABLE_ORDER_STATUSES
                ]
                groups = _unassigned(
                    drops,
                    windows,
                    await current_points(
                        connection, [drop.commitment_id for drop in drops]
                    ),
                )
            for group in groups:
                for stop in group.stops:
                    if stop.drop.commitment_id == commitment_id:
                        return stop
            # Unreachable after the checks above; fail as "not a stop".
            raise ResourceNotFound(
                "delivery_drop_not_found", "Diese Lieferung wurde nicht gefunden."
            )

        return await self._write(command)
