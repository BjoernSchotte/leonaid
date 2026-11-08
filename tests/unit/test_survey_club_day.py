"""Live survey proofs pick a refused start on the club's day, also after midnight.

Regression: summary_live.py sent "3 hours ago" as a start that must be refused
(range_whole_days). At 00:08 Berlin (CI job 128557004516) that is yesterday,
a whole past day, and the API correctly answered 200.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from leonaid.modules.surveys.application.disclosure import whole_days
from tools.surveys.club_day import REFUSAL_MARGIN, refused_start

UTC = timezone.utc


def refused(start: datetime, api_now: datetime) -> bool:
    created_from, created_before = whole_days(start.isoformat(), None, api_now)
    return created_from is not None and created_from >= created_before


def test_hours_ago_is_a_past_day_just_after_midnight() -> None:
    # 00:08 Berlin on 8 Nov (CET): 3 hours ago is 7 Nov, a whole past day.
    now = datetime(2026, 11, 7, 23, 8, 29, tzinfo=UTC)
    assert not refused(now - timedelta(hours=3), now)


@pytest.mark.parametrize(
    "database_now",
    [
        datetime(2026, 11, 7, 23, 8, 29, tzinfo=UTC),  # 00:08 Berlin
        datetime(2026, 11, 7, 22, 59, 30, tzinfo=UTC),  # 23:59:30 Berlin
        datetime(2026, 11, 8, 11, 0, tzinfo=UTC),  # midday
        datetime(2026, 3, 29, 0, 59, 30, tzinfo=UTC),  # just before CEST starts
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),  # the 25-hour day
        datetime(2026, 6, 30, 21, 59, 59, tzinfo=UTC),  # 23:59:59 CEST
    ],
)
def test_refused_start_holds_while_the_request_travels(database_now: datetime) -> None:
    start = refused_start(database_now)
    # The API reads its clock at or after database_now, within the margin;
    # midnight may pass in between.
    for delay in (timedelta(0), timedelta(seconds=31), REFUSAL_MARGIN):
        assert refused(start, database_now + delay), (database_now, delay)
