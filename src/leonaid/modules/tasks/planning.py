"""Local calendar-day boundaries for personal task planning."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def require_time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("Unbekannte IANA-Zeitzone.") from error
    return value


def planning_day(
    time_zone: str, *, now: datetime | None = None
) -> tuple[date, datetime, datetime]:
    zone = ZoneInfo(require_time_zone(time_zone))
    local_today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    start = datetime.combine(local_today, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(
        local_today.fromordinal(local_today.toordinal() + 1), time.min, zone
    ).astimezone(timezone.utc)
    return local_today, start, end
