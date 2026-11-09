"""Delivery configuration; all writes lock action before configuration."""

from __future__ import annotations

from dataclasses import replace
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.application.delivery import window_full_conflict
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.delivery import (
    DeliveryConfiguration,
    DeliveryWindow,
    DeliveryContactSnapshot,
)
from leonaid.domain.errors import DomainInvariantError


async def read_configuration(
    connection: asyncpg.Connection[Any], action_id: UUID
) -> DeliveryConfiguration:
    row = await connection.fetchrow(
        """SELECT c.enabled, c.timezone, c.revision FROM charity_action a
        LEFT JOIN action_delivery_configuration c ON c.action_id = a.id WHERE a.id = $1""",
        action_id,
    )
    if row is None:
        raise ResourceNotFound("action_not_found", "Diese Aktion wurde nicht gefunden.")
    zone_name = str(row["timezone"] or INSTALLATION_TIME_ZONE.key)
    zone = ZoneInfo(zone_name)
    windows = await connection.fetch(
        "SELECT * FROM action_delivery_window WHERE action_id = $1 ORDER BY starts_at, id",
        action_id,
    )
    return DeliveryConfiguration(
        action_id=action_id,
        enabled=bool(row["enabled"]),
        timezone=zone_name,
        revision=int(row["revision"] or 1),
        windows=tuple(
            DeliveryWindow(
                id=item["id"],
                action_id=action_id,
                delivery_on=item["starts_at"].astimezone(zone).date(),
                starts_at=item["starts_at"].astimezone(zone).time(),
                ends_at=item["ends_at"].astimezone(zone).time(),
                retired=item["retired"],
                fully_booked=item["fully_booked"],
            )
            for item in windows
        ),
    )


async def has_delivery_capability(
    connection: asyncpg.Connection[Any], action_id: UUID
) -> bool:
    """Delivery is a capability of the action, never of a template name."""
    return bool(
        await connection.fetchval(
            """SELECT EXISTS (SELECT 1 FROM charity_action_capability
            WHERE action_id = $1 AND capability = 'delivery')""",
            action_id,
        )
    )


async def lock_configuration(
    connection: asyncpg.Connection[Any], action_id: UUID
) -> DeliveryConfiguration:
    # The caller holds the action row lock. A row lock also forces stale
    # SERIALIZABLE snapshots to abort after waiting for a schedule change.
    await connection.fetchval(
        "SELECT revision FROM action_delivery_configuration WHERE action_id = $1 FOR SHARE",
        action_id,
    )
    return await read_configuration(connection, action_id)


async def lock_order_windows(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    commitment_id: UUID,
    target_window_id: UUID | None,
) -> None:
    """Share-lock the order's booked window and the one it is about to book.

    Taken before the order row (lock order in ``retry.py``), so a completion
    and a cancellation or board command on the same window never deadlock.
    """
    booked = await connection.fetchval(
        "SELECT delivery_window_id FROM commitment WHERE id = $1 AND action_id = $2",
        commitment_id,
        action_id,
    )
    window_ids = sorted(
        {window for window in (booked, target_window_id) if window is not None},
        key=str,
    )
    if window_ids:
        await connection.execute(
            """
            SELECT id FROM action_delivery_window
            WHERE action_id = $1 AND id = ANY($2::uuid[])
            ORDER BY id FOR SHARE
            """,
            action_id,
            window_ids,
        )


async def guard_window_booking(
    connection: asyncpg.Connection[Any],
    *,
    window_id: UUID | None,
    allow_full_window: bool,
) -> bool:
    """Apply the "ausgebucht" switch to an order that books ``window_id``.

    The shared row lock lets parallel orders through but makes a concurrent
    switch wait for them, and an order wait for a pending switch. Returns True
    when a full window was booked on purpose; the caller records that in the
    order event.
    """
    if window_id is None:
        return False
    fully_booked = await connection.fetchval(
        "SELECT fully_booked FROM action_delivery_window WHERE id = $1 FOR SHARE",
        window_id,
    )
    if not fully_booked:
        return False
    if not allow_full_window:
        raise window_full_conflict()
    return True


async def _audit_fully_booked(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    window_id: UUID,
    previous: bool,
    current: bool,
    actor_user_id: UUID | None,
    request_id: str,
    occurred_at: datetime,
    reason: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "fullyBooked": current,
        "previousFullyBooked": previous,
    }
    if reason is not None:
        payload["reason"] = reason
    await connection.execute(
        """
        INSERT INTO audit_event (
            id, action_id, actor_user_id, event_type,
            entity_type, entity_id, request_id, payload, occurred_at
        )
        VALUES ($1, $2, $3, 'delivery_window_fully_booked_changed',
            'delivery_window', $4, $5, $6::jsonb, $7)
        """,
        uuid4(),
        action_id,
        actor_user_id,
        window_id,
        request_id,
        json.dumps(payload, separators=(",", ":")),
        occurred_at,
    )


class AsyncpgDeliveryRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def get(self, action_id: UUID) -> DeliveryConfiguration:
        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read", readonly=True
            ):
                return await read_configuration(connection, action_id)

    async def save(
        self,
        configuration: DeliveryConfiguration,
        *,
        actor_user_id: UUID | None = None,
        request_id: str = "internal",
    ) -> DeliveryConfiguration:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                action = await connection.fetchrow(
                    "SELECT starts_on, ends_on, status FROM charity_action WHERE id = $1 FOR UPDATE",
                    configuration.action_id,
                )
                if action is None:
                    raise ResourceNotFound(
                        "action_not_found", "Diese Aktion wurde nicht gefunden."
                    )
                if not await has_delivery_capability(
                    connection, configuration.action_id
                ):
                    raise DomainInvariantError(
                        "delivery_not_supported",
                        "Lieferplanung ist nur für Aktionen mit Auslieferung verfügbar.",
                    )
                if action["status"] == "archived":
                    raise Conflict(
                        "delivery_action_archived",
                        "Archivierte Aktionen können nicht geändert werden.",
                    )
                current = await read_configuration(connection, configuration.action_id)
                if current.revision != configuration.revision:
                    raise Conflict(
                        "delivery_configuration_conflict",
                        "Die Lieferplanung wurde inzwischen geändert.",
                    )
                if current.enabled and not configuration.enabled:
                    raise Conflict(
                        "delivery_disable_forbidden",
                        "Bitte die Fenster stilllegen, um neue Lieferbestellungen zu pausieren.",
                    )
                if current.windows and current.timezone != configuration.timezone:
                    raise Conflict(
                        "delivery_timezone_locked",
                        "Die Zeitzone bestehender Lieferfenster bleibt unverändert.",
                    )
                configuration.validate_period(action["starts_on"], action["ends_on"])
                incoming = {window.id: window for window in configuration.windows}
                for old in current.windows:
                    updated = incoming.get(old.id)
                    if (
                        updated is None
                        # The "ausgebucht" switch has its own command.
                        or replace(
                            old,
                            retired=updated.retired,
                            fully_booked=updated.fully_booked,
                        )
                        != updated
                        or (old.retired and not updated.retired)
                    ):
                        raise Conflict(
                            "delivery_window_immutable",
                            "Bestehende Fenster können nur stillgelegt werden. Für neue Termine ein neues Fenster hinzufügen.",
                        )
                existing_ids = {window.id for window in current.windows}
                now = datetime.now(timezone.utc)
                for window in configuration.windows:
                    if window.id not in existing_ids:
                        if (
                            window.retired
                            or window.bounds(configuration.timezone)[0] <= now
                        ):
                            raise DomainInvariantError(
                                "delivery_window_past",
                                "Neue Lieferfenster müssen in der Zukunft liegen.",
                            )
                        owner = await connection.fetchval(
                            "SELECT action_id FROM action_delivery_window WHERE id = $1",
                            window.id,
                        )
                        if owner is not None:
                            raise DomainInvariantError(
                                "delivery_window_action_mismatch",
                                "Das Lieferfenster gehört nicht zu dieser Aktion.",
                            )
                await connection.execute(
                    """INSERT INTO action_delivery_configuration(action_id, enabled, timezone, revision)
                    VALUES ($1, $2, $3, $4) ON CONFLICT(action_id) DO UPDATE SET
                    enabled = EXCLUDED.enabled, timezone = EXCLUDED.timezone, revision = EXCLUDED.revision""",
                    configuration.action_id,
                    configuration.enabled,
                    configuration.timezone,
                    current.revision + 1,
                )
                stored = {window.id: window for window in current.windows}
                for window in configuration.windows:
                    if window.id in existing_ids:
                        # Retiring clears the switch; otherwise it is kept as
                        # stored, so a stale form never resets it.
                        await connection.execute(
                            """UPDATE action_delivery_window
                            SET retired = $2, fully_booked = fully_booked AND NOT $2
                            WHERE id = $1""",
                            window.id,
                            window.retired,
                        )
                        if stored[window.id].fully_booked and window.retired:
                            await _audit_fully_booked(
                                connection,
                                action_id=configuration.action_id,
                                window_id=window.id,
                                previous=True,
                                current=False,
                                actor_user_id=actor_user_id,
                                request_id=request_id,
                                occurred_at=now,
                                reason="retired",
                            )
                    else:
                        start, end = window.bounds(configuration.timezone)
                        await connection.execute(
                            """INSERT INTO action_delivery_window(id, action_id, starts_at, ends_at)
                            VALUES ($1, $2, $3, $4)""",
                            window.id,
                            configuration.action_id,
                            start,
                            end,
                        )
                return await read_configuration(connection, configuration.action_id)

    async def set_fully_booked(
        self,
        *,
        action_id: UUID,
        window_id: UUID,
        fully_booked: bool,
        actor_user_id: UUID,
        request_id: str,
    ) -> DeliveryConfiguration:
        """Switch "ausgebucht" on or off; a repeated value changes nothing.

        The configuration revision stays: the switch is not part of the
        window form, so a parallel form edit must not conflict with it.
        """
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                # FOR SHARE conflicts with the configuration save's FOR UPDATE.
                action = await connection.fetchrow(
                    "SELECT status FROM charity_action WHERE id = $1 FOR SHARE",
                    action_id,
                )
                if action is None:
                    raise ResourceNotFound(
                        "action_not_found", "Diese Aktion wurde nicht gefunden."
                    )
                if not await has_delivery_capability(connection, action_id):
                    raise DomainInvariantError(
                        "delivery_not_supported",
                        "Lieferplanung ist nur für Aktionen mit Auslieferung verfügbar.",
                    )
                if action["status"] == "archived":
                    raise Conflict(
                        "delivery_action_archived",
                        "Archivierte Aktionen können nicht geändert werden.",
                    )
                window = await connection.fetchrow(
                    """SELECT starts_at, retired, fully_booked
                    FROM action_delivery_window
                    WHERE id = $1 AND action_id = $2
                    FOR UPDATE""",
                    window_id,
                    action_id,
                )
                if window is None:
                    raise ResourceNotFound(
                        "delivery_window_not_found",
                        "Dieses Lieferfenster wurde nicht gefunden.",
                    )
                previous = bool(window["fully_booked"])
                if previous != fully_booked:
                    now = datetime.now(timezone.utc)
                    if window["retired"]:
                        raise Conflict(
                            "delivery_window_retired",
                            "Ein stillgelegtes Lieferfenster kann nicht ausgebucht werden.",
                        )
                    if window["starts_at"] <= now:
                        raise Conflict(
                            "delivery_window_past",
                            "Dieses Lieferfenster hat bereits begonnen.",
                        )
                    await connection.execute(
                        "UPDATE action_delivery_window SET fully_booked = $2 WHERE id = $1",
                        window_id,
                        fully_booked,
                    )
                    await _audit_fully_booked(
                        connection,
                        action_id=action_id,
                        window_id=window_id,
                        previous=previous,
                        current=fully_booked,
                        actor_user_id=actor_user_id,
                        request_id=request_id,
                        occurred_at=now,
                    )
                return await read_configuration(connection, action_id)


def decode_window_snapshot(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise ValueError("Invalid delivery window snapshot")
    return {str(key): str(item) for key, item in payload.items()}


def decode_contact_snapshot(value: object) -> DeliveryContactSnapshot | None:
    if value is None:
        return None
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise ValueError("Invalid delivery contact snapshot")
    return DeliveryContactSnapshot.from_payload(payload)


async def write_order_delivery(
    connection: asyncpg.Connection[Any],
    *,
    commitment_id: UUID,
    window_id: UUID | None,
    window_snapshot: dict[str, str] | None,
    contact: DeliveryContactSnapshot | None,
) -> None:
    # Caller owns the order transaction. This update never commits independently.
    # A stop that changes window leaves both tour orders (tours spec D14f);
    # it runs before the window update, which it compares against.
    await connection.execute(
        """UPDATE commitment_delivery AS delivery
        SET base_position = NULL, driver_position = NULL, driver_ordered_at = NULL
        FROM commitment
        WHERE delivery.commitment_id = $1 AND commitment.id = delivery.commitment_id
          AND commitment.delivery_window_id IS DISTINCT FROM $2
          AND (delivery.base_position IS NOT NULL
               OR delivery.driver_position IS NOT NULL
               OR delivery.driver_ordered_at IS NOT NULL)""",
        commitment_id,
        window_id,
    )
    await connection.execute(
        """UPDATE commitment SET delivery_window_id=$2,
        delivery_window_snapshot=$3::jsonb, delivery_contact_snapshot=$4::jsonb
        WHERE id=$1""",
        commitment_id,
        window_id,
        json.dumps(window_snapshot) if window_snapshot is not None else None,
        json.dumps(contact.payload()) if contact is not None else None,
    )
