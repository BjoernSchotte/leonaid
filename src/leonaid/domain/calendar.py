"""The installation's calendar day.

Dates people enter or read (payment received, invoice date, due date,
"today" on dashboards) are days in the club's local time, not in UTC.
Between 00:00 and 01:00 (02:00 in summer) in Berlin, UTC still has the
previous day; comparing against the UTC day then rejects every valid date.
Every server-side "which day is it" goes through this module.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from zoneinfo import ZoneInfo

# One club per installation, in Germany. There is no per-installation time
# zone setting yet; a delivery configuration's own zone only governs its
# delivery windows.
INSTALLATION_TIME_ZONE = ZoneInfo("Europe/Berlin")


def local_day(moment: datetime, zone: tzinfo = INSTALLATION_TIME_ZONE) -> date:
    """The calendar day of an aware instant in the installation's time zone."""

    if moment.utcoffset() is None:
        raise ValueError("local_day needs an aware datetime")
    return moment.astimezone(zone).date()
