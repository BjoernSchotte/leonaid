"""Sponsor search index: what an entry keeps and when the full pass is due.

The sync itself is proven against the real Twenty of the test stack
(``tools/sponsor_search/contract.py``); these are its pure rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from leonaid.application.crm import CrmPartyKind
from leonaid.application.sponsor_search import (
    CHANGED_LOOKBACK_MAX,
    CHANGED_OVERLAP,
    CHANGED_WINDOW,
    CITY_MAX_LENGTH,
    NAME_MAX_LENGTH,
    SYNC_CONTINUE_SECONDS,
    SYNC_INTERVAL_SECONDS,
    SYNC_REQUEST_BUDGET,
    PartyKey,
    SponsorParty,
    SyncReport,
    SyncState,
    changed_since,
    full_pass_due,
    retry_delay_seconds,
)
from leonaid.bootstrap.worker import SponsorSearchSyncStatus

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


# --- the changed pass reads from the last complete one ----------------------


def test_changed_pass_reads_the_window_when_runs_are_on_time() -> None:
    now = at(10, 14)
    # First changed pass ever, and one that follows a run 15 minutes ago.
    assert changed_since(None, now) == now - CHANGED_WINDOW
    assert changed_since(now - timedelta(minutes=15), now) == now - CHANGED_WINDOW


def test_changed_pass_reaches_back_over_failed_or_missed_runs() -> None:
    now = at(10, 14)
    # Two runs ended on a 429 and the worker was down: the last complete
    # pass started 50 minutes ago. A rename 45 minutes ago is still read.
    last = now - timedelta(minutes=50)
    since = changed_since(last, now)
    assert since == last - CHANGED_OVERLAP
    assert since < now - timedelta(minutes=45)


def test_changed_pass_lookback_is_bounded_after_a_long_outage() -> None:
    now = at(10, 14)
    # Older changes are the nightly full pass's.
    assert changed_since(now - timedelta(days=9), now) == now - CHANGED_LOOKBACK_MAX
    assert CHANGED_LOOKBACK_MAX > timedelta(hours=24)


# --- CRM failures: growing pause, visible age --------------------------------


def failed(code: str = "crm_unavailable", *, retryable: bool = True) -> SyncReport:
    return SyncReport(
        mode="full",
        requests=1,
        complete=False,
        crm_error=code,
        crm_error_retryable=retryable,
    )


def test_healthy_runs_keep_their_rhythm() -> None:
    assert retry_delay_seconds(SyncReport(mode="changed"), 0) == SYNC_INTERVAL_SECONDS
    assert retry_delay_seconds(SyncReport(mode="skipped"), 0) == SYNC_INTERVAL_SECONDS
    assert (
        retry_delay_seconds(SyncReport(mode="full", complete=False), 0)
        == SYNC_CONTINUE_SECONDS
    )


def test_pause_doubles_after_each_failed_run_up_to_the_interval() -> None:
    delays = [retry_delay_seconds(failed(), runs) for runs in range(1, 8)]
    assert delays == [60.0, 120.0, 240.0, 480.0, 900.0, 900.0, 900.0]
    # A 429 is a retryable failure like an outage.
    limited = SyncReport(
        mode="full", complete=False, rate_limited=True, crm_error="crm_rate_limited"
    )
    assert retry_delay_seconds(limited, 1) == 60.0
    assert retry_delay_seconds(limited, 3) == 240.0
    # Far fewer than one request a minute for ever.
    assert retry_delay_seconds(failed(), 500) == SYNC_INTERVAL_SECONDS


def test_an_error_that_waiting_does_not_cure_waits_the_interval_at_once() -> None:
    refused = failed("crm_permission_denied", retryable=False)
    assert retry_delay_seconds(refused, 1) == SYNC_INTERVAL_SECONDS


def test_last_success_is_the_newest_completed_pass() -> None:
    full, changed = at(10, 3, 5), at(10, 14)
    assert SyncState(None, None).last_success is None
    assert SyncState(full, None).last_success == full
    assert SyncState(full, None, changed_read_until=changed).last_success == changed
    assert SyncState(None, None, changed_read_until=changed).last_success == changed


def test_sync_age_counts_from_the_last_success_or_from_the_start() -> None:
    started = at(10, 8)
    status = SponsorSearchSyncStatus(started_at=started)
    # Never succeeded (wrong key from the first day): the age still grows.
    assert status.last_success_age_seconds(started + timedelta(hours=25)) == 90_000
    status.last_success = at(10, 9)
    assert status.last_success_age_seconds(at(10, 9, 30)) == 1_800
    assert status.last_success_age_seconds(at(10, 8)) == 0
