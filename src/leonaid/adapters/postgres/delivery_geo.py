"""Coordinates of delivery addresses in PostgreSQL (``delivery_geo``).

Pending stops are the deliverable orders of actions with delivery planning
whose window starts on ``today`` or later in the action's zone. The address
hash is computed here from the order's snapshot (the domain's casefold rule
has no exact SQL twin), so every run reads the upcoming orders once; that is
a few hundred rows for a club. A write first locks the order ``FOR SHARE``
and compares its current address with the hash the lookup was made for, so a
delivery completion or a privacy erasure in between wins and the stale
outcome is dropped.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.adapters.postgres.privacy import ERASED_RECIPIENT_NAME
from leonaid.application.errors import ResourceNotFound
from leonaid.domain.delivery_board import DELIVERABLE_ORDER_STATUSES
from leonaid.domain.delivery_geo import (
    MANUAL_GEOCODER,
    Found,
    GeocodeOutcome,
    GeocodeQuery,
    GeoOutcome,
    GeoPoint,
    PendingGeocode,
    StoredGeo,
    address_hash,
    is_pending,
)

# One geocoding run per installation at a time (all workers share it).
_LOCK_KEY = "leonaid.geocoding"
_DELIVERABLE = sorted(DELIVERABLE_ORDER_STATUSES)


def _snapshot(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    document = json.loads(value) if isinstance(value, str) else value
    return document if isinstance(document, dict) else None


def geocode_query(snapshot: object) -> GeocodeQuery | None:
    """The four address fields of a delivery snapshot; None without a street."""

    document = _snapshot(snapshot)
    if document is None:
        return None
    fields = (
        document.get("streetLine1"),
        document.get("postalCode"),
        document.get("city"),
        document.get("countryCode") or "DE",
    )
    if not all(isinstance(value, str) and value.strip() for value in fields):
        return None
    street, postal_code, city, country = (str(value) for value in fields)
    return GeocodeQuery(street, postal_code, city, country)


class AsyncpgDeliveryGeoRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[bool]:
        # A session lock on a connection of its own: no transaction stays
        # open while the geocoder is asked.
        async with self._pool.acquire() as connection:
            acquired = bool(
                await connection.fetchval(
                    "SELECT pg_try_advisory_lock(hashtext($1))", _LOCK_KEY
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.execute(
                        "SELECT pg_advisory_unlock(hashtext($1))", _LOCK_KEY
                    )

    async def pending(
        self, *, today: date, now: datetime, limit: int
    ) -> Sequence[PendingGeocode]:
        rows = await self._pool.fetch(
            """
            SELECT commitment.id, commitment.action_id,
                commitment.delivery_recipient_snapshot,
                (window_row.starts_at AT TIME ZONE configuration.timezone)::date
                    AS delivery_on,
                geo.outcome, geo.address_hash, geo.attempts, geo.geocoded_at,
                geo.source
            FROM commitment
            JOIN action_delivery_configuration AS configuration
              ON configuration.action_id = commitment.action_id
             AND configuration.enabled
            JOIN action_delivery_window AS window_row
              ON window_row.id = commitment.delivery_window_id
            LEFT JOIN delivery_geo AS geo ON geo.commitment_id = commitment.id
            WHERE commitment.status = ANY($1::text[])
              AND commitment.delivery_recipient_snapshot IS NOT NULL
              -- An erased order keeps a placeholder address: nothing to find.
              AND commitment.delivery_recipient_snapshot ->> 'recipientName'
                  IS DISTINCT FROM $3
              AND (window_row.starts_at AT TIME ZONE configuration.timezone)::date
                  >= $2
              AND EXISTS (
                  SELECT 1 FROM charity_action_capability
                  WHERE action_id = commitment.action_id
                    AND capability = 'delivery'
              )
            ORDER BY window_row.starts_at, commitment.id
            """,
            _DELIVERABLE,
            today,
            ERASED_RECIPIENT_NAME,
        )
        found: list[PendingGeocode] = []
        for row in rows:
            query = geocode_query(row["delivery_recipient_snapshot"])
            if query is None:
                continue
            digest = address_hash(query)
            stored = (
                None
                if row["outcome"] is None
                else StoredGeo(
                    outcome=GeoOutcome(row["outcome"]),
                    address_hash=row["address_hash"],
                    attempts=row["attempts"],
                    geocoded_at=row["geocoded_at"],
                    manual=row["source"] == "manual",
                )
            )
            if not is_pending(stored, digest, now):
                continue
            found.append(
                PendingGeocode(
                    action_id=row["action_id"],
                    commitment_id=row["id"],
                    delivery_on=row["delivery_on"],
                    query=query,
                    address_hash=digest,
                )
            )
            if len(found) == limit:
                break
        return found

    async def _current_hash(
        self, connection: asyncpg.Connection[Any], action_id: UUID, commitment_id: UUID
    ) -> str | None:
        snapshot = await connection.fetchval(
            """
            SELECT delivery_recipient_snapshot FROM commitment
            WHERE id = $1 AND action_id = $2
            FOR SHARE
            """,
            commitment_id,
            action_id,
        )
        query = geocode_query(snapshot)
        return None if query is None else address_hash(query)

    async def record(
        self,
        pending: PendingGeocode,
        outcome: GeocodeOutcome,
        *,
        geocoder: str,
        at: datetime,
    ) -> bool:
        point = outcome.point if isinstance(outcome, Found) else None
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                current = await self._current_hash(
                    connection, pending.action_id, pending.commitment_id
                )
                if current != pending.address_hash:
                    return False
                status = await connection.execute(
                    """
                    INSERT INTO delivery_geo (
                        commitment_id, action_id, lat, lon, source, outcome,
                        address_hash, geocoded_at, geocoder, attempts
                    )
                    VALUES ($1, $2, $3, $4, 'geocoder', $5, $6, $7, $8, 1)
                    ON CONFLICT (commitment_id) DO UPDATE SET
                        lat = EXCLUDED.lat,
                        lon = EXCLUDED.lon,
                        source = 'geocoder',
                        outcome = EXCLUDED.outcome,
                        geocoded_at = EXCLUDED.geocoded_at,
                        geocoder = EXCLUDED.geocoder,
                        attempts = CASE
                            WHEN delivery_geo.address_hash = EXCLUDED.address_hash
                            THEN delivery_geo.attempts + 1
                            ELSE 1
                        END,
                        address_hash = EXCLUDED.address_hash
                    -- A pin the manager set for this address stays.
                    WHERE NOT (
                        delivery_geo.source = 'manual'
                        AND delivery_geo.address_hash = EXCLUDED.address_hash
                    )
                    """,
                    pending.commitment_id,
                    pending.action_id,
                    point.lat if point else None,
                    point.lon if point else None,
                    outcome.outcome.value,
                    pending.address_hash,
                    at,
                    geocoder,
                )
                return str(status).endswith(" 1")

    async def set_pin(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        point: GeoPoint,
        at: datetime,
    ) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                current = await self._current_hash(connection, action_id, commitment_id)
                if current is None:
                    raise ResourceNotFound(
                        "delivery_address_missing",
                        "Diese Bestellung hat keine Lieferadresse.",
                    )
                await connection.execute(
                    """
                    INSERT INTO delivery_geo (
                        commitment_id, action_id, lat, lon, source, outcome,
                        address_hash, geocoded_at, geocoder, attempts
                    )
                    VALUES ($1, $2, $3, $4, 'manual', 'found', $5, $6, $7, 1)
                    ON CONFLICT (commitment_id) DO UPDATE SET
                        lat = EXCLUDED.lat,
                        lon = EXCLUDED.lon,
                        source = 'manual',
                        outcome = 'found',
                        address_hash = EXCLUDED.address_hash,
                        geocoded_at = EXCLUDED.geocoded_at,
                        geocoder = EXCLUDED.geocoder,
                        attempts = 1
                    """,
                    commitment_id,
                    action_id,
                    point.lat,
                    point.lon,
                    current,
                    at,
                    MANUAL_GEOCODER,
                )
