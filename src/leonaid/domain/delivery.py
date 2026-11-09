"""Action-owned delivery schedules and immutable order selections."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata
from datetime import date, datetime, time, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.delivery_geo import GeoPoint
from leonaid.domain.errors import DomainInvariantError


@dataclass(frozen=True, slots=True)
class DeliveryContactSnapshot:
    name: str | None = None
    phone: str | None = None

    def __post_init__(self) -> None:
        for field, limit in (("name", 200), ("phone", 40)):
            value = getattr(self, field)
            if value is None:
                continue
            if any(character in value for character in "\r\n"):
                raise DomainInvariantError(
                    "delivery_contact_invalid",
                    "Bitte den Lieferkontakt einzeilig angeben.",
                )
            value = value.strip()
            if len(value) > limit:
                raise DomainInvariantError(
                    "delivery_contact_too_long",
                    f"Das Lieferkontaktfeld darf höchstens {limit} Zeichen enthalten.",
                )
            if (
                field == "phone"
                and value
                and (
                    not re.fullmatch(r"[+0-9 ()/.\-]+", value)
                    or not any(c.isdigit() for c in value)
                )
            ):
                raise DomainInvariantError(
                    "delivery_contact_phone_invalid",
                    "Bitte eine gültige Telefonnummer für die Lieferung angeben.",
                )
            object.__setattr__(self, field, value or None)

    @property
    def empty(self) -> bool:
        return self.name is None and self.phone is None

    def payload(self) -> dict[str, str | None]:
        return {"name": self.name, "phone": self.phone}

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> DeliveryContactSnapshot:
        return cls(
            name=str(payload["name"]) if payload.get("name") is not None else None,
            phone=str(payload["phone"]) if payload.get("phone") is not None else None,
        )


def local_instant(day: date, clock: time, zone_name: str) -> datetime:
    """Reject ambiguous/nonexistent wall times instead of choosing a DST fold."""
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise DomainInvariantError(
            "delivery_timezone_invalid", "Die Lieferzeitzone ist ungültig."
        ) from error
    if clock.tzinfo is not None or clock.second or clock.microsecond:
        raise DomainInvariantError(
            "delivery_time_invalid", "Bitte eine lokale Uhrzeit in Minuten angeben."
        )
    naive = datetime.combine(day, clock)
    candidates = {
        instant
        for fold in (0, 1)
        if (instant := naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc))
        .astimezone(zone)
        .replace(tzinfo=None)
        == naive
    }
    if len(candidates) != 1:
        raise DomainInvariantError(
            "delivery_time_dst_invalid",
            "Diese Uhrzeit ist wegen der Zeitumstellung nicht eindeutig verfügbar.",
        )
    return candidates.pop()


@dataclass(frozen=True, slots=True)
class DeliveryWindow:
    id: UUID
    action_id: UUID
    delivery_on: date
    starts_at: time
    ends_at: time
    retired: bool = False
    # Manual "ausgebucht" switch: closes the window for public orders only.
    fully_booked: bool = False

    def __post_init__(self) -> None:
        if self.retired and self.fully_booked:
            raise DomainInvariantError(
                "delivery_window_full_retired",
                "Ein stillgelegtes Lieferfenster kann nicht ausgebucht sein.",
            )
        if (
            self.starts_at.tzinfo is not None
            or self.ends_at.tzinfo is not None
            or self.starts_at >= self.ends_at
        ):
            raise DomainInvariantError(
                "delivery_window_range_invalid",
                "Das Ende muss am selben Tag nach dem Beginn liegen.",
            )

    def bounds(self, zone_name: str) -> tuple[datetime, datetime]:
        return (
            local_instant(self.delivery_on, self.starts_at, zone_name),
            local_instant(self.delivery_on, self.ends_at, zone_name),
        )

    def snapshot(self, zone_name: str) -> dict[str, str]:
        start, end = self.bounds(zone_name)
        return {
            "windowId": str(self.id),
            "startsAt": start.isoformat(),
            "endsAt": end.isoformat(),
            "timezone": zone_name,
        }


def _one_line(value: str, limit: int) -> str | None:
    """The trimmed value, or None if it is empty, too long or not one line."""

    if any(
        unicodedata.category(character) in ("Cc", "Zl", "Zp") for character in value
    ):
        return None
    text = value.strip()
    return text if 1 <= len(text) <= limit else None


@dataclass(frozen=True, slots=True)
class DeliveryStartPoint:
    """Where the drivers pick up the Krapfen in the morning (D11).

    ``point`` is None until the worker found the address or the manager set
    a pin. ``locating``: the worker will still look the address up; it is
    read from the store and ignored on save.
    """

    label: str
    address: str
    point: GeoPoint | None = None
    locating: bool = False

    def __post_init__(self) -> None:
        label = _one_line(self.label, 80)
        address = _one_line(self.address, 200)
        if label is None or address is None:
            raise DomainInvariantError(
                "delivery_start_invalid",
                "Startpunkt: Bezeichnung (bis 80 Zeichen) und Adresse (bis 200"
                " Zeichen) jeweils einzeilig angeben.",
            )
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "address", address)


def merged_start(
    stored: DeliveryStartPoint | None, requested: DeliveryStartPoint | None
) -> DeliveryStartPoint | None:
    """The start point to store.

    A request without a point keeps the stored point of the same address,
    whether the geocoder found it or the manager set it. A new address
    without a point has none until the worker looks it up.
    """

    if (
        requested is None
        or requested.point is not None
        or stored is None
        or stored.address != requested.address
    ):
        return requested
    return replace(requested, point=stored.point)


@dataclass(frozen=True, slots=True)
class DeliveryConfiguration:
    action_id: UUID
    enabled: bool = False
    timezone: str = INSTALLATION_TIME_ZONE.key
    revision: int = 1
    windows: tuple[DeliveryWindow, ...] = ()
    start: DeliveryStartPoint | None = None

    def __post_init__(self) -> None:
        local_instant(date(2026, 1, 1), time(12), self.timezone)
        if self.revision < 1:
            raise DomainInvariantError(
                "delivery_revision_invalid", "Die Lieferrevision muss positiv sein."
            )
        if len({window.id for window in self.windows}) != len(self.windows):
            raise DomainInvariantError(
                "delivery_window_duplicate", "Ein Lieferfenster ist doppelt vorhanden."
            )
        ordered = tuple(
            sorted(self.windows, key=lambda item: (item.delivery_on, item.starts_at))
        )
        previous: DeliveryWindow | None = None
        for window in ordered:
            if window.action_id != self.action_id:
                raise DomainInvariantError(
                    "delivery_window_action_mismatch",
                    "Das Lieferfenster gehört nicht zu dieser Aktion.",
                )
            window.bounds(self.timezone)
            if window.retired:
                continue
            if (
                previous is not None
                and previous.delivery_on == window.delivery_on
                and previous.ends_at > window.starts_at
            ):
                raise DomainInvariantError(
                    "delivery_windows_overlap",
                    "Lieferfenster dürfen sich nicht überlappen.",
                )
            previous = window
        object.__setattr__(self, "windows", ordered)

    def validate_period(self, starts_on: date, ends_on: date) -> None:
        if any(
            not starts_on <= window.delivery_on <= ends_on
            for window in self.windows
            if not window.retired
        ):
            raise DomainInvariantError(
                "delivery_date_outside_action",
                "Die Liefertage müssen innerhalb der Aktionslaufzeit liegen.",
            )

    def select(self, window_id: UUID, *, now: datetime) -> DeliveryWindow:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Delivery selection requires an aware current time")
        for window in self.windows:
            if (
                self.enabled
                and window.id == window_id
                and not window.retired
                and window.bounds(self.timezone)[0] > now
            ):
                return window
        raise DomainInvariantError(
            "delivery_window_unavailable",
            "Dieses Lieferfenster ist nicht mehr verfügbar. Bitte erneut auswählen.",
        )

    def validate_order(
        self,
        *,
        window_id: UUID | None,
        has_address: bool,
        contact: DeliveryContactSnapshot | None,
        complete: bool,
        now: datetime,
    ) -> dict[str, str] | None:
        if not self.enabled and (window_id is not None or contact is not None):
            raise DomainInvariantError(
                "delivery_not_supported",
                "Für diese Aktion ist keine Lieferplanung aktiviert.",
            )
        if self.enabled and complete and (not has_address or window_id is None):
            raise DomainInvariantError(
                "delivery_required", "Bitte Lieferadresse und Lieferfenster ergänzen."
            )
        return (
            self.select(window_id, now=now).snapshot(self.timezone)
            if window_id is not None
            else None
        )

    def select_historical(self, window_id: UUID, *, now: datetime) -> DeliveryWindow:
        """A configured window that has already started, retired or not.

        Only the manager completion of an existing order may use this, to
        record when an order was actually delivered. Retired windows are
        included because retiring is how new bookings are paused and past
        windows cannot be created afterwards: a retired past window may be
        the only record of the slot that was used. A retired window that has
        not started yet stays unavailable; it is not history.
        """
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Delivery selection requires an aware current time")
        for window in self.windows:
            if (
                self.enabled
                and window.id == window_id
                and window.bounds(self.timezone)[0] <= now
            ):
                return window
        raise DomainInvariantError(
            "delivery_window_unavailable",
            "Dieses Lieferfenster ist nicht mehr verfügbar. Bitte erneut auswählen.",
        )

    def validate_manager_completion(
        self,
        *,
        window_id: UUID | None,
        has_address: bool,
        contact: DeliveryContactSnapshot | None,
        now: datetime,
    ) -> tuple[dict[str, str] | None, bool]:
        """Validate a manager completion; return the snapshot and whether it is historical.

        Bookable (future, active) windows behave exactly like order capture.
        Windows that have already started are accepted as a historical record.
        """
        if self.enabled and window_id is not None and has_address:
            try:
                snapshot = self.validate_order(
                    window_id=window_id,
                    has_address=has_address,
                    contact=contact,
                    complete=True,
                    now=now,
                )
            except DomainInvariantError as error:
                if error.code != "delivery_window_unavailable":
                    raise
            else:
                return snapshot, False
            return self.select_historical(window_id, now=now).snapshot(
                self.timezone
            ), True
        return (
            self.validate_order(
                window_id=window_id,
                has_address=has_address,
                contact=contact,
                complete=True,
                now=now,
            ),
            False,
        )
