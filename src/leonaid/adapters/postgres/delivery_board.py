"""Delivery day board in PostgreSQL.

Every command runs in one transaction and locks the order's delivery window
(``FOR UPDATE`` on the window row) before reading drops, so a closure and a
tick on the same window serialize. Follow-up tasks run in the same
transaction through the tasks module, when it is enabled.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.adapters.postgres.retry import (
    RETRYABLE_ERRORS,
    SERIALIZABLE_ATTEMPTS,
    serialization_pause,
)
from leonaid.application.delivery_board import DeliveryFollowUp
from leonaid.application.errors import ResourceNotFound
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE, local_day
from leonaid.domain.delivery_board import (
    DELIVERABLE_ORDER_STATUSES,
    READ_AUDIT_RETENTION_DAYS,
    BoardDriver,
    BoardWindow,
    DeliveryBoard,
    DeliveryBoardError,
    DeliveryDrop,
    DropAddress,
    DropContact,
    DropQuantity,
    DropState,
    WindowClosure,
    board_day,
    decide_state_change,
)

_DELIVERABLE = sorted(DELIVERABLE_ORDER_STATUSES)

_ACTIVE_DRIVER = """
    SELECT 1 FROM action_membership AS membership
    JOIN user_account AS account ON account.id = membership.user_id
    WHERE membership.action_id = $1
      AND membership.user_id = $2
      AND membership.role = 'driver'
      AND membership.active_from <= now()
      AND (membership.active_until IS NULL OR membership.active_until > now())
      AND account.status = 'active'
"""

_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def window_label(starts_at: datetime, ends_at: datetime, zone: ZoneInfo) -> str:
    """ "Mi 11.11. · 07:00–09:00 Uhr" in the window's zone."""

    start = starts_at.astimezone(zone)
    end = ends_at.astimezone(zone)
    return (
        f"{_WEEKDAYS[start.weekday()]} {start:%d.%m.} · {start:%H:%M}–{end:%H:%M} Uhr"
    )


def order_reference(commitment_id: UUID, public_reference: str | None) -> str:
    """A reference without personal data: the public one or the id's tail."""

    return public_reference or f"…{str(commitment_id)[-8:]}"


def order_link(action_id: UUID, commitment_id: UUID) -> str:
    """The order in the orders list pane (Task 5.1 URL contract)."""

    return f"/admin/orders?action={action_id}&view=all&open={commitment_id}"


def _json(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = json.loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, dict) else None


def _state(value: Any) -> DropState:
    return DropState(str(value)) if value is not None else DropState.OPEN


class AsyncpgDeliveryBoardRepository:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        follow_up: Callable[[asyncpg.Connection[Any]], DeliveryFollowUp] | None = None,
    ) -> None:
        self._pool = pool
        self._follow_up = follow_up

    # ---------- reads ----------

    async def _context(
        self, connection: asyncpg.Connection[Any], action_id: UUID
    ) -> tuple[str, ZoneInfo]:
        row = await connection.fetchrow(
            """
            SELECT action.name, configuration.enabled, configuration.timezone,
                EXISTS (
                    SELECT 1 FROM charity_action_capability
                    WHERE action_id = action.id AND capability = 'delivery'
                ) AS capable
            FROM charity_action AS action
            LEFT JOIN action_delivery_configuration AS configuration
              ON configuration.action_id = action.id
            WHERE action.id = $1
            """,
            action_id,
        )
        if row is None or not row["capable"] or not row["enabled"]:
            raise ResourceNotFound(
                "delivery_not_enabled",
                "Für diese Aktion ist keine Lieferplanung aktiv.",
            )
        return str(row["name"]), ZoneInfo(
            str(row["timezone"] or INSTALLATION_TIME_ZONE.key)
        )

    async def board(
        self,
        *,
        action_id: UUID,
        day: date | None,
        driver_user_id: UUID | None,
        viewed_at: datetime,
    ) -> DeliveryBoard:
        manager = driver_user_id is None
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                action_name, zone = await self._context(connection, action_id)
                windows = await connection.fetch(
                    """
                    SELECT window_row.id, window_row.starts_at, window_row.ends_at,
                        window_row.retired, window_row.fully_booked,
                        closure.closed_at, closure.missed_count,
                        closer.display_name AS closed_by_name
                    FROM action_delivery_window AS window_row
                    LEFT JOIN delivery_window_closure AS closure
                      ON closure.window_id = window_row.id
                    LEFT JOIN user_account AS closer
                      ON closer.id = closure.closed_by_user_id
                    WHERE window_row.action_id = $1
                    ORDER BY window_row.starts_at, window_row.id
                    """,
                    action_id,
                )
                drops = await self._drops(
                    connection,
                    action_id=action_id,
                    window_ids=[row["id"] for row in windows],
                    driver_user_id=driver_user_id,
                    manager=manager,
                )
                by_window: dict[UUID, list[DeliveryDrop]] = {}
                for drop in drops:
                    by_window.setdefault(drop.window_id, []).append(drop)
                # Managers see every window that is active or has drops;
                # drivers only windows with drops assigned to them.
                visible = [
                    row
                    for row in windows
                    if by_window.get(row["id"]) or (manager and not row["retired"])
                ]
                days = tuple(
                    sorted({local_day(row["starts_at"], zone) for row in visible})
                )
                selected = board_day(days, day, local_day(viewed_at, zone))
                selected_windows = [
                    row
                    for row in visible
                    if selected is not None
                    and local_day(row["starts_at"], zone) == selected
                ]
                if not manager and driver_user_id is not None and selected is not None:
                    await connection.executemany(
                        """
                        INSERT INTO delivery_read_audit (
                            driver_user_id, window_id, viewed_on, action_id,
                            first_viewed_at
                        )
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT DO NOTHING
                        """,
                        [
                            (
                                driver_user_id,
                                row["id"],
                                local_day(viewed_at, zone),
                                action_id,
                                viewed_at,
                            )
                            for row in selected_windows
                        ],
                    )
                drivers: tuple[BoardDriver, ...] = ()
                if manager:
                    drivers = tuple(
                        BoardDriver(
                            user_id=row["id"], display_name=str(row["display_name"])
                        )
                        for row in await connection.fetch(
                            """
                            SELECT DISTINCT account.id, account.display_name
                            FROM action_membership AS membership
                            JOIN user_account AS account
                              ON account.id = membership.user_id
                            WHERE membership.action_id = $1
                              AND membership.role = 'driver'
                              AND membership.active_from <= now()
                              AND (membership.active_until IS NULL
                                   OR membership.active_until > now())
                              AND account.status = 'active'
                            ORDER BY account.display_name, account.id
                            """,
                            action_id,
                        )
                    )
        return DeliveryBoard(
            action_id=action_id,
            action_name=action_name,
            timezone=zone.key,
            day=selected,
            days=days,
            manager=manager,
            windows=tuple(
                BoardWindow(
                    id=row["id"],
                    starts_at=row["starts_at"],
                    ends_at=row["ends_at"],
                    retired=bool(row["retired"]),
                    fully_booked=bool(row["fully_booked"]),
                    closure=(
                        WindowClosure(
                            closed_at=row["closed_at"],
                            closed_by_name=(
                                str(row["closed_by_name"]) if manager else ""
                            ),
                            missed_count=int(row["missed_count"]),
                        )
                        if row["closed_at"] is not None
                        else None
                    ),
                    drops=tuple(by_window.get(row["id"], ())),
                )
                for row in selected_windows
            ),
            drivers=drivers,
            follow_up_tasks=self._follow_up is not None,
        )

    async def _drops(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        window_ids: list[UUID],
        driver_user_id: UUID | None,
        manager: bool,
        commitment_id: UUID | None = None,
    ) -> list[DeliveryDrop]:
        rows = await connection.fetch(
            """
            SELECT
                commitment.id, commitment.delivery_window_id, commitment.status,
                commitment.customer_snapshot, commitment.delivery_recipient_snapshot,
                commitment.delivery_contact_snapshot,
                delivery.driver_user_id, driver.display_name AS driver_name,
                delivery.state, delivery.state_changed_at,
                changer.display_name AS changed_by_name,
                COALESCE(delivery.revision, 0) AS revision,
                COALESCE(delivery.missed_at_closure, false) AS missed_at_closure,
                COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object('unit', unit, 'quantity', quantity)
                        ORDER BY unit
                    )
                    FROM (
                        SELECT line.unit_snapshot AS unit,
                            sum(line.quantity)::int AS quantity
                        FROM commitment_line AS line
                        WHERE line.commitment_id = commitment.id
                        GROUP BY line.unit_snapshot
                    ) AS grouped
                ), '[]'::jsonb) AS quantities
            FROM commitment
            LEFT JOIN commitment_delivery AS delivery
              ON delivery.commitment_id = commitment.id
            LEFT JOIN user_account AS driver ON driver.id = delivery.driver_user_id
            LEFT JOIN user_account AS changer
              ON changer.id = delivery.state_changed_by_user_id
            WHERE commitment.action_id = $1
              AND commitment.delivery_window_id = ANY($2::uuid[])
              AND (
                  commitment.status = ANY($3::text[])
                  -- Cancelled after delivery: the fact stays, managers only.
                  OR ($5 AND delivery.state = 'delivered')
              )
              AND ($4::uuid IS NULL OR delivery.driver_user_id = $4)
              AND ($6::uuid IS NULL OR commitment.id = $6)
            ORDER BY commitment.customer_snapshot ->> 'displayName', commitment.id
            """,
            action_id,
            window_ids,
            _DELIVERABLE,
            driver_user_id,
            manager,
            commitment_id,
        )
        drops: list[DeliveryDrop] = []
        for row in rows:
            customer = _json(row["customer_snapshot"]) or {}
            recipient = _json(row["delivery_recipient_snapshot"])
            contact = _json(row["delivery_contact_snapshot"])
            quantities = tuple(
                DropQuantity(unit=str(item["unit"]), quantity=int(item["quantity"]))
                for item in (
                    json.loads(row["quantities"])
                    if isinstance(row["quantities"], str)
                    else row["quantities"]
                )
            )
            drops.append(
                DeliveryDrop(
                    commitment_id=row["id"],
                    window_id=row["delivery_window_id"],
                    buyer_name=str(customer.get("displayName") or "Besteller"),
                    quantities=quantities,
                    total_boxes=sum(
                        item.quantity for item in quantities if item.unit == "box"
                    ),
                    address=(
                        DropAddress(
                            recipient_name=str(recipient.get("recipientName") or ""),
                            street_line_1=str(recipient.get("streetLine1") or ""),
                            postal_code=str(recipient.get("postalCode") or ""),
                            city=str(recipient.get("city") or ""),
                        )
                        if recipient
                        else None
                    ),
                    contact=(
                        DropContact(
                            name=(
                                str(contact["name"]) if contact.get("name") else None
                            ),
                            phone=(
                                str(contact["phone"]) if contact.get("phone") else None
                            ),
                        )
                        if contact
                        else None
                    ),
                    state=_state(row["state"]),
                    # Drivers get the state only, not who changed it when
                    # (Björn P3); their own name they know.
                    state_changed_at=row["state_changed_at"] if manager else None,
                    state_changed_by_name=(
                        str(row["changed_by_name"])
                        if manager and row["changed_by_name"] is not None
                        else None
                    ),
                    driver_user_id=row["driver_user_id"],
                    driver_name=(
                        str(row["driver_name"])
                        if manager and row["driver_name"] is not None
                        else None
                    ),
                    revision=int(row["revision"]),
                    order_status=str(row["status"]) if manager else None,
                    missed_at_closure=bool(row["missed_at_closure"]),
                )
            )
        return drops

    # ---------- commands ----------

    async def _lock_window(
        self, connection: asyncpg.Connection[Any], action_id: UUID, window_id: UUID
    ) -> asyncpg.Record:
        row = await connection.fetchrow(
            """
            SELECT window_row.id, window_row.starts_at, window_row.ends_at,
                EXISTS (
                    SELECT 1 FROM delivery_window_closure
                    WHERE window_id = window_row.id
                ) AS closed
            FROM action_delivery_window AS window_row
            WHERE window_row.action_id = $1 AND window_row.id = $2
            FOR UPDATE OF window_row
            """,
            action_id,
            window_id,
        )
        if row is None:
            raise ResourceNotFound(
                "delivery_window_not_found", "Das Lieferfenster wurde nicht gefunden."
            )
        return row

    async def _audit(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        request_id: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type,
                entity_id, request_id, payload, occurred_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
            """,
            uuid4(),
            action_id,
            actor_user_id,
            event_type,
            entity_type,
            entity_id,
            request_id,
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )

    async def _sync_follow_up(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        drop: DeliveryDrop,
        label: str,
        needed: bool,
        assignee_user_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> None:
        if self._follow_up is None:
            return
        # The order cancellation (adapters/postgres/order_cancellation.py)
        # closes the task through the same port. No personal data in the task (it would outlive the order's
        # erasure): the order reference, the window and a link to the order,
        # whose pane shows the address to those allowed to see it.
        reference = await connection.fetchval(
            "SELECT public_reference FROM commitment WHERE id = $1",
            drop.commitment_id,
        )
        await self._follow_up(connection).sync(
            connection,
            action_id=action_id,
            commitment_id=drop.commitment_id,
            title=f"Nachliefern: Bestellung {order_reference(drop.commitment_id, reference)}",
            description=(
                f"Nicht geliefert im Fenster {label}.\n"
                f"Bestellung öffnen: {order_link(action_id, drop.commitment_id)}"
            ),
            needed=needed,
            assignee_user_id=assignee_user_id,
            actor_user_id=actor_user_id,
            request_id=request_id,
            occurred_at=occurred_at,
        )

    async def set_state(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        delivered: bool,
        expected_revision: int,
        actor_user_id: UUID,
        manager: bool,
        request_id: str,
        occurred_at: datetime,
    ) -> DeliveryDrop:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                _, zone = await self._context(connection, action_id)
                if not manager and not await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM commitment_delivery
                        WHERE commitment_id = $1 AND action_id = $2
                          AND driver_user_id = $3
                    )
                    """,
                    commitment_id,
                    action_id,
                    actor_user_id,
                ):
                    # Before anything else: a driver learns nothing about
                    # orders that are not theirs (existence, status).
                    raise DeliveryBoardError(
                        "delivery_not_assigned",
                        "Diese Lieferung ist Ihnen nicht zugewiesen.",
                        status=403,
                    )
                window_id = await connection.fetchval(
                    """
                    SELECT delivery_window_id FROM commitment
                    WHERE id = $1 AND action_id = $2
                    """,
                    commitment_id,
                    action_id,
                )
                if window_id is None:
                    raise ResourceNotFound(
                        "delivery_drop_not_found",
                        "Diese Lieferung wurde nicht gefunden.",
                    )
                window = await self._lock_window(connection, action_id, window_id)
                current = await self._drops(
                    connection,
                    action_id=action_id,
                    window_ids=[window_id],
                    driver_user_id=None,
                    manager=True,
                    commitment_id=commitment_id,
                )
                if not current:
                    raise DeliveryBoardError(
                        "delivery_order_not_deliverable",
                        "Diese Bestellung wird nicht ausgeliefert.",
                    )
                drop = current[0]
                if drop.order_status == "cancelled":
                    raise DeliveryBoardError(
                        "delivery_order_not_deliverable",
                        "Diese Bestellung ist storniert.",
                    )
                change = decide_state_change(
                    current=drop.state,
                    delivered=delivered,
                    window_closed=bool(window["closed"]),
                    manager=manager,
                    assigned_driver=drop.driver_user_id == actor_user_id,
                    missed_at_closure=drop.missed_at_closure,
                )
                if change is None:
                    return self._for_viewer(drop, manager)
                if drop.revision != expected_revision:
                    raise DeliveryBoardError(
                        "delivery_state_conflict",
                        "Diese Lieferung wurde inzwischen geändert.",
                    )
                stored_state = (
                    None
                    if change.new_state is DropState.OPEN
                    else change.new_state.value
                )
                await connection.execute(
                    """
                    INSERT INTO commitment_delivery (
                        commitment_id, action_id, state, state_changed_at,
                        state_changed_by_user_id
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (commitment_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        state_changed_at = EXCLUDED.state_changed_at,
                        state_changed_by_user_id = EXCLUDED.state_changed_by_user_id,
                        revision = commitment_delivery.revision + 1
                    """,
                    commitment_id,
                    action_id,
                    stored_state,
                    occurred_at if stored_state else None,
                    actor_user_id if stored_state else None,
                )
                # missed_at_closure stays as the closure set it: a later
                # delivery of a missed drop may still be undone to missed.
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type=(
                        "delivery.marked_delivered"
                        if change.new_state is DropState.DELIVERED
                        else "delivery.marked_open"
                        if change.new_state is DropState.OPEN
                        else "delivery.marked_missed"
                    ),
                    entity_type="commitment",
                    entity_id=commitment_id,
                    request_id=request_id,
                    payload={
                        "previousState": drop.state.value,
                        "state": change.new_state.value,
                        "windowId": str(window_id),
                    },
                    occurred_at=occurred_at,
                )
                if change.follow_up_needed is not None:
                    closer = await connection.fetchval(
                        "SELECT closed_by_user_id FROM delivery_window_closure"
                        " WHERE window_id = $1",
                        window_id,
                    )
                    await self._sync_follow_up(
                        connection,
                        action_id=action_id,
                        drop=drop,
                        label=window_label(
                            window["starts_at"], window["ends_at"], zone
                        ),
                        needed=change.follow_up_needed,
                        assignee_user_id=closer or actor_user_id,
                        actor_user_id=actor_user_id,
                        request_id=request_id,
                        occurred_at=occurred_at,
                    )
                updated = await self._drops(
                    connection,
                    action_id=action_id,
                    window_ids=[window_id],
                    driver_user_id=None,
                    manager=True,
                    commitment_id=commitment_id,
                )
                return self._for_viewer(updated[0], manager)

    @staticmethod
    def _for_viewer(drop: DeliveryDrop, manager: bool) -> DeliveryDrop:
        # Drivers get the P3 fields only: no order status, no who or when
        # of changes, no driver name.
        return (
            drop
            if manager
            else replace(
                drop,
                order_status=None,
                state_changed_at=None,
                state_changed_by_name=None,
                driver_name=None,
            )
        )

    async def assign_driver(
        self,
        *,
        action_id: UUID,
        commitment_ids: tuple[UUID, ...],
        driver_user_id: UUID | None,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int:
        if not commitment_ids:
            return 0
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
                try:
                    async with connection.transaction():
                        return await self._assign_driver_once(
                            connection,
                            action_id=action_id,
                            commitment_ids=commitment_ids,
                            driver_user_id=driver_user_id,
                            actor_user_id=actor_user_id,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except RETRYABLE_ERRORS:
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise DeliveryBoardError(
                            "delivery_concurrent_retry",
                            "Die Lieferungen wurden gleichzeitig geändert. "
                            "Bitte erneut zuweisen.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Fahrerzuweisung wurde nicht ausgeführt.")

    async def _assign_driver_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        commitment_ids: tuple[UUID, ...],
        driver_user_id: UUID | None,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int:
        await self._context(connection, action_id)
        if driver_user_id is not None and not await connection.fetchval(
            f"SELECT EXISTS ({_ACTIVE_DRIVER})", action_id, driver_user_id
        ):
            raise DeliveryBoardError(
                "delivery_driver_invalid",
                "Diese Person ist für die Aktion nicht als Ausfahrer eingetragen.",
            )
        # Lock order (retry.py): the orders' windows, then the order
        # rows, each in id order, so overlapping bulk assignments and
        # cancellations never wait on each other in a cycle.
        await connection.execute(
            """
            SELECT id FROM action_delivery_window
            WHERE id IN (
                SELECT delivery_window_id FROM commitment
                WHERE action_id = $1 AND id = ANY($2::uuid[])
            )
            ORDER BY id FOR SHARE
            """,
            action_id,
            list(commitment_ids),
        )
        rows = await connection.fetch(
            """
            SELECT id FROM commitment
            WHERE action_id = $1 AND id = ANY($2::uuid[])
              AND delivery_window_id IS NOT NULL
              AND status = ANY($3::text[])
            ORDER BY id
            FOR UPDATE
            """,
            action_id,
            list(commitment_ids),
            _DELIVERABLE,
        )
        if len(rows) != len(set(commitment_ids)):
            raise DeliveryBoardError(
                "delivery_order_not_deliverable",
                "Mindestens eine Bestellung wird nicht ausgeliefert.",
            )
        status = await connection.execute(
            """
            INSERT INTO commitment_delivery (
                commitment_id, action_id, driver_user_id,
                driver_assigned_by_user_id, driver_assigned_at
            )
            SELECT id, $2, $3, $4, $5 FROM unnest($1::uuid[]) AS id
            ON CONFLICT (commitment_id) DO UPDATE SET
                driver_user_id = EXCLUDED.driver_user_id,
                driver_assigned_by_user_id = EXCLUDED.driver_assigned_by_user_id,
                driver_assigned_at = EXCLUDED.driver_assigned_at,
                revision = commitment_delivery.revision + 1
            WHERE commitment_delivery.driver_user_id
                IS DISTINCT FROM EXCLUDED.driver_user_id
            """,
            [row["id"] for row in rows],
            action_id,
            driver_user_id,
            actor_user_id if driver_user_id else None,
            occurred_at if driver_user_id else None,
        )
        changed = int(status.rsplit(" ", 1)[-1])
        if changed:
            await self._audit(
                connection,
                action_id=action_id,
                actor_user_id=actor_user_id,
                event_type="delivery.drivers_assigned",
                entity_type="charity_action",
                entity_id=action_id,
                request_id=request_id,
                payload={
                    "driverUserId": (str(driver_user_id) if driver_user_id else None),
                    "commitmentIds": sorted(str(row["id"]) for row in rows),
                },
                occurred_at=occurred_at,
            )
        return changed

    async def close_window(
        self,
        *,
        action_id: UUID,
        window_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                _, zone = await self._context(connection, action_id)
                window = await self._lock_window(connection, action_id, window_id)
                if window["closed"]:
                    return int(
                        await connection.fetchval(
                            "SELECT missed_count FROM delivery_window_closure"
                            " WHERE window_id = $1",
                            window_id,
                        )
                    )
                drops = await self._drops(
                    connection,
                    action_id=action_id,
                    window_ids=[window_id],
                    driver_user_id=None,
                    manager=True,
                )
                missed = [
                    drop
                    for drop in drops
                    if drop.state is DropState.OPEN
                    and drop.order_status in DELIVERABLE_ORDER_STATUSES
                ]
                if missed:
                    await connection.execute(
                        """
                        INSERT INTO commitment_delivery (
                            commitment_id, action_id, state, state_changed_at,
                            state_changed_by_user_id, missed_at_closure
                        )
                        SELECT id, $2, 'missed', $3, $4, true
                        FROM unnest($1::uuid[]) AS id
                        ON CONFLICT (commitment_id) DO UPDATE SET
                            state = 'missed',
                            missed_at_closure = true,
                            state_changed_at = EXCLUDED.state_changed_at,
                            state_changed_by_user_id = EXCLUDED.state_changed_by_user_id,
                            revision = commitment_delivery.revision + 1
                        """,
                        [drop.commitment_id for drop in missed],
                        action_id,
                        occurred_at,
                        actor_user_id,
                    )
                await connection.execute(
                    """
                    INSERT INTO delivery_window_closure (
                        window_id, action_id, closed_at, closed_by_user_id,
                        missed_count
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    window_id,
                    action_id,
                    occurred_at,
                    actor_user_id,
                    len(missed),
                )
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="delivery.window_closed",
                    entity_type="action_delivery_window",
                    entity_id=window_id,
                    request_id=request_id,
                    payload={
                        "missedCommitmentIds": [
                            str(drop.commitment_id) for drop in missed
                        ],
                        "followUpTasks": self._follow_up is not None,
                    },
                    occurred_at=occurred_at,
                )
                label = window_label(window["starts_at"], window["ends_at"], zone)
                for drop in missed:
                    await self._sync_follow_up(
                        connection,
                        action_id=action_id,
                        drop=drop,
                        label=label,
                        needed=True,
                        assignee_user_id=actor_user_id,
                        actor_user_id=actor_user_id,
                        request_id=request_id,
                        occurred_at=occurred_at,
                    )
                return len(missed)

    async def reopen_window(
        self,
        *,
        action_id: UUID,
        window_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                _, zone = await self._context(connection, action_id)
                window = await self._lock_window(connection, action_id, window_id)
                if not window["closed"]:
                    return 0
                drops = await self._drops(
                    connection,
                    action_id=action_id,
                    window_ids=[window_id],
                    driver_user_id=None,
                    manager=True,
                )
                missed = [drop for drop in drops if drop.state is DropState.MISSED]
                # Later deliveries stay delivered; reopening makes their
                # window an ordinary open window again.
                await connection.execute(
                    """
                    UPDATE commitment_delivery SET missed_at_closure = false
                    WHERE missed_at_closure AND commitment_id = ANY($1::uuid[])
                    """,
                    [drop.commitment_id for drop in drops],
                )
                if missed:
                    await connection.execute(
                        """
                        UPDATE commitment_delivery
                        SET state = NULL, state_changed_at = NULL,
                            state_changed_by_user_id = NULL,
                            missed_at_closure = false,
                            revision = revision + 1
                        WHERE commitment_id = ANY($1::uuid[])
                        """,
                        [drop.commitment_id for drop in missed],
                    )
                await connection.execute(
                    "DELETE FROM delivery_window_closure WHERE window_id = $1",
                    window_id,
                )
                await self._audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="delivery.window_reopened",
                    entity_type="action_delivery_window",
                    entity_id=window_id,
                    request_id=request_id,
                    payload={
                        "reopenedCommitmentIds": [
                            str(drop.commitment_id) for drop in missed
                        ]
                    },
                    occurred_at=occurred_at,
                )
                label = window_label(window["starts_at"], window["ends_at"], zone)
                for drop in missed:
                    await self._sync_follow_up(
                        connection,
                        action_id=action_id,
                        drop=drop,
                        label=label,
                        needed=False,
                        assignee_user_id=actor_user_id,
                        actor_user_id=actor_user_id,
                        request_id=request_id,
                        occurred_at=occurred_at,
                    )
                return len(missed)


async def purge_read_audits(
    pool: asyncpg.Pool[Any], *, now: datetime, limit: int
) -> int:
    """Deletes driver read audits older than the retention, one batch."""

    status = await pool.execute(
        """
        DELETE FROM delivery_read_audit
        WHERE ctid = ANY (
            ARRAY(
                SELECT ctid FROM delivery_read_audit
                WHERE first_viewed_at < $1
                LIMIT $2
            )
        )
        """,
        now - timedelta(days=READ_AUDIT_RETENTION_DAYS),
        limit,
    )
    return int(status.rsplit(" ", 1)[-1])
