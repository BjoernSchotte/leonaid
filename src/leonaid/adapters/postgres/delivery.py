"""Delivery reads and serialized action schedule writes."""

from __future__ import annotations

from dataclasses import replace
import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.delivery import DeliveryConfiguration, DeliveryWindow
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.commitments import DeliveryRecipientSnapshot


def decode_window_snapshot(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise ValueError("Invalid delivery window snapshot")
    return {str(key): str(item) for key, item in payload.items()}


async def select_order_window(
    connection: asyncpg.Connection[Any],
    action_id: UUID,
    *,
    window_id: UUID | None,
    recipient: DeliveryRecipientSnapshot | None,
    complete: bool,
    now: datetime,
) -> dict[str, str] | None:
    """Caller holds the action row lock until the order is committed."""
    configuration = await read_configuration(connection, action_id)
    if configuration.enabled and complete and (recipient is None or window_id is None):
        raise DomainInvariantError(
            "delivery_details_required",
            "Bitte Lieferadresse und Lieferfenster ergänzen.",
        )
    if window_id is None:
        return None
    return configuration.select(window_id, now=now).snapshot(configuration.timezone)


async def read_configuration(
    connection: asyncpg.Connection[Any], action_id: UUID
) -> DeliveryConfiguration:
    row = await connection.fetchrow(
        """SELECT c.enabled, c.timezone, c.revision
        FROM charity_action a LEFT JOIN action_delivery_configuration c
        ON c.action_id = a.id WHERE a.id = $1""",
        action_id,
    )
    if row is None:
        raise ResourceNotFound("action_not_found", "Diese Aktion wurde nicht gefunden.")
    windows = await connection.fetch(
        "SELECT * FROM delivery_window WHERE action_id = $1 ORDER BY delivery_on, starts_at",
        action_id,
    )
    return DeliveryConfiguration(
        action_id=action_id,
        enabled=bool(row["enabled"]),
        timezone=str(row["timezone"] or "Europe/Berlin"),
        revision=int(row["revision"] or 1),
        windows=tuple(
            DeliveryWindow(
                id=item["id"],
                action_id=action_id,
                delivery_on=item["delivery_on"],
                starts_at=item["starts_at"],
                ends_at=item["ends_at"],
                retired=item["retired"],
            )
            for item in windows
        ),
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

    async def save(self, configuration: DeliveryConfiguration) -> DeliveryConfiguration:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                # Order creation and action-period edits must use this same action lock.
                action = await connection.fetchrow(
                    "SELECT starts_on, ends_on FROM charity_action WHERE id = $1 FOR UPDATE",
                    configuration.action_id,
                )
                if action is None:
                    raise ResourceNotFound(
                        "action_not_found", "Diese Aktion wurde nicht gefunden."
                    )
                current = await read_configuration(connection, configuration.action_id)
                if current.revision != configuration.revision:
                    raise Conflict(
                        "delivery_revision_conflict",
                        "Die Lieferplanung wurde inzwischen geändert.",
                    )
                configuration.validate_period(action["starts_on"], action["ends_on"])
                if configuration.enabled and not any(
                    not w.retired for w in configuration.windows
                ):
                    raise DomainInvariantError(
                        "delivery_windows_required",
                        "Bitte mindestens ein Lieferfenster anlegen.",
                    )
                booked = {
                    row["delivery_window_id"]
                    for row in await connection.fetch(
                        "SELECT DISTINCT delivery_window_id FROM commitment WHERE action_id = $1 AND delivery_window_id IS NOT NULL",
                        configuration.action_id,
                    )
                }
                if booked and current.timezone != configuration.timezone:
                    raise Conflict(
                        "delivery_timezone_booked",
                        "Die Zeitzone bereits gebuchter Lieferungen bleibt unverändert.",
                    )
                incoming = {window.id: window for window in configuration.windows}
                for old in current.windows:
                    updated = incoming.get(old.id)
                    if old.id in booked and (
                        updated is None
                        or replace(old, retired=updated.retired) != updated
                    ):
                        raise Conflict(
                            "delivery_window_booked",
                            "Gebuchte Fenster können nur deaktiviert werden.",
                        )
                await connection.execute(
                    """INSERT INTO action_delivery_configuration(action_id, enabled, timezone, revision)
                    VALUES ($1, $2, $3, $4) ON CONFLICT (action_id) DO UPDATE SET
                    enabled = EXCLUDED.enabled, timezone = EXCLUDED.timezone, revision = EXCLUDED.revision""",
                    configuration.action_id,
                    configuration.enabled,
                    configuration.timezone,
                    current.revision + 1,
                )
                for old in current.windows:
                    if old.id not in incoming:
                        await connection.execute(
                            "DELETE FROM delivery_window WHERE id = $1", old.id
                        )
                # Validate IDs before upserts; a client cannot take over another action's ID.
                for window in configuration.windows:
                    owner = await connection.fetchval(
                        "SELECT action_id FROM delivery_window WHERE id = $1", window.id
                    )
                    if owner is not None and owner != configuration.action_id:
                        raise DomainInvariantError(
                            "delivery_window_action_mismatch",
                            "Das Lieferfenster gehört nicht zu dieser Aktion.",
                        )
                # Retire first to allow replacement of an existing interval in one save.
                await connection.execute(
                    "UPDATE delivery_window SET retired = true WHERE action_id = $1",
                    configuration.action_id,
                )
                for window in configuration.windows:
                    saved_id = await connection.fetchval(
                        """INSERT INTO delivery_window(id, action_id, delivery_on, starts_at, ends_at, retired)
                        VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO UPDATE SET
                        delivery_on = EXCLUDED.delivery_on, starts_at = EXCLUDED.starts_at,
                        ends_at = EXCLUDED.ends_at, retired = EXCLUDED.retired
                        WHERE delivery_window.action_id = EXCLUDED.action_id
                        RETURNING id""",
                        window.id,
                        configuration.action_id,
                        window.delivery_on,
                        window.starts_at,
                        window.ends_at,
                        window.retired,
                    )
                    if saved_id is None:
                        raise DomainInvariantError(
                            "delivery_window_action_mismatch",
                            "Das Lieferfenster gehört nicht zu dieser Aktion.",
                        )
                return replace(configuration, revision=current.revision + 1)
