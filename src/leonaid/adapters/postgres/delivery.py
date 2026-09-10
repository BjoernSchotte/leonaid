"""Delivery configuration; all writes lock action before configuration."""

from __future__ import annotations

from dataclasses import replace
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
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
    zone_name = str(row["timezone"] or "Europe/Berlin")
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
            )
            for item in windows
        ),
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
                action = await connection.fetchrow(
                    "SELECT starts_on, ends_on, status FROM charity_action WHERE id = $1 FOR UPDATE",
                    configuration.action_id,
                )
                if action is None:
                    raise ResourceNotFound(
                        "action_not_found", "Diese Aktion wurde nicht gefunden."
                    )
                supported = await connection.fetchval(
                    """SELECT EXISTS (SELECT 1 FROM action_template_snapshot s
                    JOIN charity_action_capability c ON c.action_id = s.action_id
                    WHERE s.action_id = $1 AND s.template_key = 'krapfentaxi'
                    AND c.capability = 'ordering')""",
                    configuration.action_id,
                )
                if not supported:
                    raise DomainInvariantError(
                        "delivery_not_supported",
                        "Lieferplanung ist nur für Krapfentaxi mit Bestellungen verfügbar.",
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
                        or replace(old, retired=updated.retired) != updated
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
                for window in configuration.windows:
                    if window.id in existing_ids:
                        await connection.execute(
                            "UPDATE action_delivery_window SET retired = $2 WHERE id = $1",
                            window.id,
                            window.retired,
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
                return replace(configuration, revision=current.revision + 1)


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
    await connection.execute(
        """UPDATE commitment SET delivery_window_id=$2,
        delivery_window_snapshot=$3::jsonb, delivery_contact_snapshot=$4::jsonb
        WHERE id=$1""",
        commitment_id,
        window_id,
        json.dumps(window_snapshot) if window_snapshot is not None else None,
        json.dumps(contact.payload()) if contact is not None else None,
    )
