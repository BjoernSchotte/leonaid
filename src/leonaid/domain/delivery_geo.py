"""Coordinates of delivery addresses (specs/krapfentaxi-touren §5, §8.2).

The server geocodes the address snapshot of an order and caches one row per
order in ``delivery_geo``. A row remembers the hash of the address it was
made for, so a changed address makes it stale. Failures are stored too, so
the geocoder is not asked again and again (D14 e): ``not_found`` is final for
that address, ``failed`` (timeout, provider error) is retried a few times.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError

# Nominatim's importance of a structured street hit is about 0.05-0.3; below
# that the hit is a guess. To be calibrated on the dev instance (D14 e).
MIN_IMPORTANCE = 0.05
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(hours=1)
# Geocoder id of a pin the manager set by hand.
MANUAL_GEOCODER = "manual"

_PLACES = Decimal("0.000001")
_FAILURE_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")
_SEPARATOR = "\x1f"
# "Street 1, 83646 Town" with an optional ", AT" country code (D11 start point).
_START_ADDRESS = re.compile(
    r"\s*(?P<street>[^,]*\S)\s*,\s*(?P<postal>\d{4,5})\s+(?P<city>[^,]*\S)"
    r"\s*(?:,\s*(?P<country>[A-Za-z]{2}))?\s*\Z"
)


class GeoOutcome(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    FAILED = "failed"


def _invalid_point() -> DomainInvariantError:
    return DomainInvariantError(
        "geo_point_invalid", "Die Koordinaten liegen außerhalb des gültigen Bereichs."
    )


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """WGS84 latitude and longitude, quantised to six places (about 0.1 m)."""

    lat: Decimal
    lon: Decimal

    def __post_init__(self) -> None:
        try:
            lat = Decimal(self.lat).quantize(_PLACES)
            lon = Decimal(self.lon).quantize(_PLACES)
        except (InvalidOperation, TypeError, ValueError):
            raise _invalid_point() from None
        if not (lat.is_finite() and lon.is_finite()):
            raise _invalid_point()
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise _invalid_point()
        object.__setattr__(self, "lat", lat)
        object.__setattr__(self, "lon", lon)

    @classmethod
    def parse(cls, lat: str | float | Decimal, lon: str | float | Decimal) -> GeoPoint:
        """A point from text or numbers, as a provider or a client sends them."""

        try:
            return cls(Decimal(str(lat)), Decimal(str(lon)))
        except (InvalidOperation, ValueError):
            raise _invalid_point() from None


@dataclass(frozen=True, slots=True)
class GeocodeQuery:
    """The only address fields that leave the server (spec §8.2): no names."""

    street: str
    postal_code: str
    city: str
    country_code: str


def start_geocode_query(address: str) -> GeocodeQuery | None:
    """The structured query of a one-line start address; None if it is vague.

    The geocoder takes street, postal code and city apart, so the start
    address must read "Marktstraße 50, 83646 Bad Tölz". Anything else is
    not looked up; the manager sets the pin by hand.
    """

    match = _START_ADDRESS.match(address)
    if match is None:
        return None
    return GeocodeQuery(
        " ".join(match["street"].split()),
        match["postal"],
        " ".join(match["city"].split()),
        (match["country"] or "DE").upper(),
    )


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def address_hash(query: GeocodeQuery) -> str:
    """Changes when the address changes, not when only case or spacing do."""

    joined = _SEPARATOR.join(
        _normalized(value)
        for value in (query.street, query.postal_code, query.city, query.country_code)
    )
    return hashlib.sha256(joined.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Found:
    point: GeoPoint
    importance: float

    @property
    def outcome(self) -> GeoOutcome:
        return GeoOutcome.FOUND


@dataclass(frozen=True, slots=True)
class NotFound:
    @property
    def outcome(self) -> GeoOutcome:
        return GeoOutcome.NOT_FOUND


@dataclass(frozen=True, slots=True)
class Failed:
    """A lookup that may work later; ``code`` is a fixed word, never input."""

    code: str

    def __post_init__(self) -> None:
        if not _FAILURE_CODE.fullmatch(self.code):
            raise DomainInvariantError(
                "geocode_failure_code_invalid", "Ungültiger Fehlercode."
            )

    @property
    def outcome(self) -> GeoOutcome:
        return GeoOutcome.FAILED


GeocodeOutcome = Found | NotFound | Failed


def accept(
    result_postcode: str | None, importance: float | None, query: GeocodeQuery
) -> bool:
    """A hit counts only in the asked postal code and when it is not a guess."""

    if result_postcode is None or importance is None:
        return False
    return (
        result_postcode.strip() == query.postal_code.strip()
        and importance >= MIN_IMPORTANCE
    )


def retry_due(
    outcome: GeoOutcome, attempts: int, geocoded_at: datetime, now: datetime
) -> bool:
    """Only a failure is asked again, at most three times, an hour apart."""

    return (
        outcome is GeoOutcome.FAILED
        and attempts < MAX_ATTEMPTS
        and now - geocoded_at >= RETRY_AFTER
    )


@dataclass(frozen=True, slots=True)
class StoredGeo:
    """What pending needs to know of a stored row."""

    outcome: GeoOutcome
    address_hash: str
    attempts: int
    geocoded_at: datetime
    manual: bool


def is_pending(stored: StoredGeo | None, current_hash: str, now: datetime) -> bool:
    """No row, a row for another address (a manual pin too), or a retry."""

    if stored is None or stored.address_hash != current_hash:
        return True
    return retry_due(stored.outcome, stored.attempts, stored.geocoded_at, now)


@dataclass(frozen=True, slots=True)
class PendingGeocode:
    action_id: UUID
    commitment_id: UUID
    delivery_on: date
    query: GeocodeQuery
    address_hash: str


@dataclass(frozen=True, slots=True)
class PendingStartGeocode:
    """An action's start address to look up; ``query`` None: not parseable."""

    action_id: UUID
    address: str
    query: GeocodeQuery | None
