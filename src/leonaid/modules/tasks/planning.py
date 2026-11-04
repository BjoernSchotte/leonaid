"""Local calendar-day boundaries for personal task planning.

Planning is personal: "today" is the viewer's day in the zone their client
sends, not the club's. The day arithmetic is the shared calendar helper's.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from leonaid.domain.calendar import local_day, local_day_bounds


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
    local_today = local_day(now or datetime.now(timezone.utc), zone)
    start, end = local_day_bounds(local_today, zone)
    return local_today, start, end
