"""Action-owned delivery schedules and immutable order selections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from leonaid.domain.errors import DomainInvariantError


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

    def __post_init__(self) -> None:
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
        self.bounds(zone_name)
        return {
            "windowId": str(self.id),
            "deliveryOn": self.delivery_on.isoformat(),
            "startsAt": self.starts_at.isoformat(timespec="minutes"),
            "endsAt": self.ends_at.isoformat(timespec="minutes"),
            "timezone": zone_name,
        }


@dataclass(frozen=True, slots=True)
class DeliveryConfiguration:
    action_id: UUID
    enabled: bool = False
    timezone: str = "Europe/Berlin"
    revision: int = 1
    windows: tuple[DeliveryWindow, ...] = ()

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
            not starts_on <= window.delivery_on <= ends_on for window in self.windows
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

    def form_definition(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "requireAddress": self.enabled,
            "requireWindow": self.enabled,
            "allowContact": self.enabled,
            "allowInstructions": self.enabled,
            "contactNameMaxLength": 200,
            "contactPhoneMaxLength": 50,
            "instructionsMaxLength": 1000,
        }
