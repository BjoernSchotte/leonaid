"""Coordinates of delivery addresses in PostgreSQL (``delivery_geo``).

Pending stops are the deliverable orders of actions with delivery planning
whose window starts on ``today`` or later in the action's zone. The address
hash is computed here from the order's snapshot (the domain's casefold rule
has no exact SQL twin), so every run reads the upcoming orders once; that is
a few hundred rows for a club. A write first locks the order ``FOR SHARE``
and compares its current address with the hash the lookup was made for, so a
delivery completion or a privacy erasure in between wins and the stale
outcome is dropped.

The action's start point (D11) is looked up by the same job: its lookup
state lives in ``action_delivery_configuration`` and is written only while
the stored address is still the one that was asked for.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Collection, Sequence
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
    PendingStartGeocode,
    StoredGeo,
    address_hash,
    is_pending,
    retry_due,
    start_geocode_query,
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


async def current_points(
    connection: asyncpg.Connection[Any], commitment_ids: Collection[UUID]
) -> dict[UUID, GeoPoint]:
    """Found coordinates of the orders whose address is still the one pinned.

    A row for a former address (delivery completion) is stale and left out.
    """

    if not commitment_ids:
        return {}
    rows = await connection.fetch(
        """
        SELECT geo.commitment_id, geo.lat, geo.lon, geo.address_hash,
            commitment.delivery_recipient_snapshot
        FROM delivery_geo AS geo
        JOIN commitment ON commitment.id = geo.commitment_id
        WHERE geo.commitment_id = ANY($1::uuid[]) AND geo.outcome = 'found'
        """,
        list(commitment_ids),
    )
    points: dict[UUID, GeoPoint] = {}
    for row in rows:
        query = geocode_query(row["delivery_recipient_snapshot"])
        if query is not None and address_hash(query) == row["address_hash"]:
            points[row["commitment_id"]] = GeoPoint(row["lat"], row["lon"])
    return points


async def current_address_hash(
    connection: asyncpg.Connection[Any], action_id: UUID, commitment_id: UUID
) -> str | None:
    """Locks the order ``FOR SHARE``; None without a usable address."""

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


async def write_manual_pin(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    commitment_id: UUID,
    point: GeoPoint,
    address_digest: str,
    at: datetime,
) -> None:
    """The manager's pin for the order's current address (spec §6.4)."""

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
        address_digest,
        at,
        MANUAL_GEOCODER,
    )


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
                current = await current_address_hash(
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
                current = await current_address_hash(
                    connection, action_id, commitment_id
                )
                if current is None:
                    raise ResourceNotFound(
                        "delivery_address_missing",
                        "Diese Bestellung hat keine Lieferadresse.",
                    )
                await write_manual_pin(
                    connection,
                    action_id=action_id,
                    commitment_id=commitment_id,
                    point=point,
                    address_digest=current,
                    at=at,
                )

    async def pending_starts(
        self, *, now: datetime, limit: int
    ) -> Sequence[PendingStartGeocode]:
        """Start addresses without a point that were never asked or may retry."""

        rows = await self._pool.fetch(
            """
            SELECT configuration.action_id, configuration.start_address,
                configuration.start_geo_outcome,
                configuration.start_geo_attempts,
                configuration.start_geocoded_at
            FROM action_delivery_configuration AS configuration
            JOIN charity_action AS action ON action.id = configuration.action_id
            WHERE configuration.enabled
              AND action.status <> 'archived'
              AND configuration.start_address IS NOT NULL
              AND configuration.start_lat IS NULL
              AND configuration.start_geo_outcome IS DISTINCT FROM 'not_found'
              AND EXISTS (
                  SELECT 1 FROM charity_action_capability
                  WHERE action_id = configuration.action_id
                    AND capability = 'delivery'
              )
            ORDER BY configuration.action_id
            """
        )
        found: list[PendingStartGeocode] = []
        for row in rows:
            outcome = row["start_geo_outcome"]
            if outcome is not None and not retry_due(
                GeoOutcome(outcome),
                row["start_geo_attempts"],
                row["start_geocoded_at"],
                now,
            ):
                continue
            address = str(row["start_address"])
            found.append(
                PendingStartGeocode(
                    action_id=row["action_id"],
                    address=address,
                    query=start_geocode_query(address),
                )
            )
            if len(found) == limit:
                break
        return found

    async def record_start(
        self,
        action_id: UUID,
        address: str,
        outcome: GeocodeOutcome,
        *,
        geocoder: str,
        at: datetime,
    ) -> bool:
        """Store the outcome while ``address`` is still the start without a point."""

        point = outcome.point if isinstance(outcome, Found) else None
        status = await self._pool.execute(
            """
            UPDATE action_delivery_configuration SET
                start_lat = $3, start_lon = $4,
                start_geo_outcome = $5,
                start_geo_attempts = start_geo_attempts + 1,
                start_geocoded_at = $6, start_geocoder = $7
            WHERE action_id = $1 AND start_address = $2 AND start_lat IS NULL
            """,
            action_id,
            address,
            point.lat if point else None,
            point.lon if point else None,
            outcome.outcome.value,
            at,
            geocoder,
        )
        return str(status).endswith(" 1")
