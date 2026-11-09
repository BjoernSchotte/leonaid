"""The geocoding job: coordinates for upcoming deliveries (spec §8.2).

One loop covers both "on a new address" and the catch-up: every run asks the
repository for the stops that need a lookup (no row, a row for an older
address, or a failure that is due again) and records each outcome. The job
runs only while ``delivery.tours`` is on and only for delivery days from
today on. One advisory lock keeps two workers from asking the geocoder twice.
The job never logs or stores an address outside ``delivery_geo``.

The same run first looks up the actions' start points (D11). Only the worker
has an egress network, so a saved start address waits for it; an address the
geocoder cannot take apart is stored as not found without a request.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from leonaid.domain.calendar import local_day
from leonaid.domain.identity import require_aware
from leonaid.domain.delivery_geo import (
    GeocodeOutcome,
    GeocodeQuery,
    GeoPoint,
    UNPARSED_GEOCODER,
    NotFound,
    PendingGeocode,
    PendingStartGeocode,
)
from leonaid.domain.feature_flags import FeatureFlagKey


class Geocoder(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def lookup(self, query: GeocodeQuery) -> GeocodeOutcome: ...


class DeliveryGeoRepository(Protocol):
    def exclusive(self) -> AbstractAsyncContextManager[bool]:
        """Hold the installation-wide geocoding lock; yields whether it was free."""
        ...

    async def pending(
        self, *, today: date, now: datetime, limit: int
    ) -> Sequence[PendingGeocode]: ...

    async def record(
        self,
        pending: PendingGeocode,
        outcome: GeocodeOutcome,
        *,
        geocoder: str,
        at: datetime,
    ) -> bool:
        """Store the outcome while the order still has ``pending.address_hash``."""
        ...

    async def set_pin(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        point: GeoPoint,
        at: datetime,
    ) -> None: ...

    async def pending_starts(
        self, *, now: datetime, limit: int
    ) -> Sequence[PendingStartGeocode]: ...

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
        ...


class FlagSwitch(Protocol):
    async def installation_enabled(self, key: FeatureFlagKey) -> bool: ...


class GeocodingJob:
    def __init__(
        self,
        repository: DeliveryGeoRepository,
        geocoder: Geocoder,
        flags: FlagSwitch,
    ) -> None:
        self._repository = repository
        self._geocoder = geocoder
        self._flags = flags

    async def run_once(self, *, now: datetime, limit: int = 30) -> int:
        """Look up at most ``limit`` start points and stops; returns the
        number of geocoder requests."""

        require_aware(now, "now")
        if limit < 1:
            raise ValueError("limit must be positive")
        if not await self._flags.installation_enabled(FeatureFlagKey.DELIVERY_TOURS):
            return 0
        async with self._repository.exclusive() as acquired:
            if not acquired:
                return 0
            geocoder = self._geocoder.provider_id
            starts = await self._repository.pending_starts(now=now, limit=limit)
            requests = 0
            for start in starts:
                source = geocoder
                if start.query is None:
                    outcome: GeocodeOutcome = NotFound()
                    source = UNPARSED_GEOCODER
                else:
                    outcome = await self._geocoder.lookup(start.query)
                    requests += 1
                await self._repository.record_start(
                    start.action_id,
                    start.address,
                    outcome,
                    geocoder=source,
                    at=now,
                )
            if len(starts) >= limit:
                return requests
            pending = await self._repository.pending(
                today=local_day(now), now=now, limit=limit - len(starts)
            )
            for item in pending:
                outcome = await self._geocoder.lookup(item.query)
                await self._repository.record(item, outcome, geocoder=geocoder, at=now)
            return requests + len(pending)
