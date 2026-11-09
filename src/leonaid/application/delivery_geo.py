"""The geocoding job: coordinates for upcoming deliveries (spec §8.2).

One loop covers both "on a new address" and the catch-up: every run asks the
repository for the stops that need a lookup (no row, a row for an older
address, or a failure that is due again) and records each outcome. The job
runs only while ``delivery.tours`` is on and only for delivery days from
today on. One advisory lock keeps two workers from asking the geocoder twice.
The job never logs or stores an address outside ``delivery_geo``.
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
    PendingGeocode,
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
        """Look up at most ``limit`` stops; returns the number of lookups."""

        require_aware(now, "now")
        if limit < 1:
            raise ValueError("limit must be positive")
        if not await self._flags.installation_enabled(FeatureFlagKey.DELIVERY_TOURS):
            return 0
        async with self._repository.exclusive() as acquired:
            if not acquired:
                return 0
            pending = await self._repository.pending(
                today=local_day(now), now=now, limit=limit
            )
            for item in pending:
                outcome = await self._geocoder.lookup(item.query)
                await self._repository.record(
                    item, outcome, geocoder=self._geocoder.provider_id, at=now
                )
            return len(pending)
