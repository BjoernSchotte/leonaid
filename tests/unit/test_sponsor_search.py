"""Sponsor search index: what an entry keeps and when the full pass is due.

The sync itself is proven against the real Twenty of the test stack
(``tools/sponsor_search/contract.py``); these are its pure rules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from leonaid.application.crm import CrmPartyKind
from leonaid.application.sponsor_search import (
    CHANGED_WINDOW,
    CITY_MAX_LENGTH,
    NAME_MAX_LENGTH,
    SYNC_CONTINUE_SECONDS,
    SYNC_INTERVAL_SECONDS,
    SYNC_REQUEST_BUDGET,
    PartyKey,
    SponsorParty,
    SyncReport,
    full_pass_due,
)

BERLIN = ZoneInfo("Europe/Berlin")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A November 2026 instant in Berlin time (UTC+1)."""
    return datetime(2026, 11, day, hour, minute, tzinfo=BERLIN).astimezone(timezone.utc)


def party(name: str, city: str | None = None) -> SponsorParty:
    return SponsorParty(PartyKey(CrmPartyKind.COMPANY, uuid4()), name, city)


def test_entry_keeps_a_trimmed_name_and_city() -> None:
    entry = party("  Bäckerei   Krapf ", "  Augsburg ")
    assert (entry.display_name, entry.city) == ("Bäckerei Krapf", "Augsburg")
    assert party("Krapf", "   ").city is None
    assert party("Krapf").city is None


def test_entry_cuts_values_to_the_column_width() -> None:
    entry = party("x" * 500, "y" * 300)
    assert len(entry.display_name) == NAME_MAX_LENGTH
    assert entry.city is not None and len(entry.city) == CITY_MAX_LENGTH


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_entry_needs_a_name(name: str) -> None:
    with pytest.raises(ValueError):
        party(name)


def test_first_full_pass_is_due_at_once() -> None:
    assert full_pass_due(None, at(10, 14), BERLIN)


@pytest.mark.parametrize(
    ("completed", "now", "due"),
    [
        # Finished after tonight's 03:00: not again today.
        (at(10, 3, 5), at(10, 14), False),
        (at(10, 3, 5), at(11, 2, 59), False),
        # The next night's 03:00 passed.
        (at(10, 3, 5), at(11, 3, 0), True),
        # Finished yesterday afternoon (first deploy): due after 03:00.
        (at(9, 15), at(10, 2, 59), False),
        (at(9, 15), at(10, 3, 1), True),
        # The worker was down for days.
        (at(5, 3, 5), at(10, 1), True),
    ],
)
def test_full_pass_is_due_once_per_night(
    completed: datetime, now: datetime, due: bool
) -> None:
    assert full_pass_due(completed, now, BERLIN) is due


def test_full_pass_time_follows_the_local_clock_in_summer() -> None:
    # 03:00 in Berlin is 01:00 UTC in summer, 02:00 UTC in winter.
    done = datetime(2026, 7, 1, 1, 10, tzinfo=timezone.utc)
    assert not full_pass_due(
        done, datetime(2026, 7, 2, 0, 59, tzinfo=timezone.utc), BERLIN
    )
    assert full_pass_due(done, datetime(2026, 7, 2, 1, 0, tzinfo=timezone.utc), BERLIN)


def test_an_unfinished_full_pass_continues_after_the_short_pause() -> None:
    assert SyncReport(mode="full", complete=False).continue_soon
    assert not SyncReport(mode="full", complete=True).continue_soon
    assert not SyncReport(mode="changed", complete=False).continue_soon
    assert not SyncReport(mode="skipped").continue_soon


def test_budget_leaves_the_api_most_of_the_crm_quota() -> None:
    # Twenty allows 100 requests a minute; the loop never sends more than its
    # budget in one minute, and one missed run loses no change.
    assert SYNC_REQUEST_BUDGET == 30
    assert SYNC_CONTINUE_SECONDS >= 60
    assert CHANGED_WINDOW.total_seconds() == 2 * SYNC_INTERVAL_SECONDS
