"""The installation's calendar day.

Dates people enter or read (payment received, invoice date, due date,
"today" on dashboards) are days in the club's local time, not in UTC.
Between 00:00 and 01:00 (02:00 in summer) in Berlin, UTC still has the
previous day; comparing against the UTC day then rejects every valid date.

Server-side "which day is it" for the club goes through this module. Two
places use another zone on purpose and still call these helpers with it:
task planning uses the viewer's own zone (their personal "today"), and
delivery windows use the zone of their delivery configuration.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from leonaid.domain.identity import require_aware

# One club per installation, in Germany. There is no per-installation time
# zone setting yet. The invoice date is stored at issue (``invoice.issued_on``),
# so changing this later never moves the date of an issued invoice.
INSTALLATION_TIME_ZONE = ZoneInfo("Europe/Berlin")


def local_day(moment: datetime, zone: tzinfo = INSTALLATION_TIME_ZONE) -> date:
    """The calendar day of an aware instant in ``zone`` (default: the club's)."""

    require_aware(moment, "moment")
    return moment.astimezone(zone).date()


def local_day_bounds(
    day: date, zone: tzinfo = INSTALLATION_TIME_ZONE
) -> tuple[datetime, datetime]:
    """The UTC instants where ``day`` starts and the next day starts in ``zone``.

    23 or 25 hours apart on the nights the clocks change.
    """

    start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(
        timezone.utc
    )
    return start, end
