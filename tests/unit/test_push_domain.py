"""Push rules without a database: payload, throttle and the daily window."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.push import (
    PUSH_THROTTLE,
    TEST_KIND,
    DEVICE_FAILURE_DAYS,
    DEVICE_FAILURE_LIMIT,
    DEVICE_FAILURE_PERIOD,
    DispatchState,
    PushKind,
    PushMessage,
    PushOutcome,
    PushResult,
    device_is_dead,
    follow_up_push_due,
    plan_dispatch,
)

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def test_a_payload_carries_kind_count_and_path_only() -> None:
    payload = json.loads(PushMessage(PushKind.FOLLOW_UPS, 3).payload())

    assert payload == {
        "kind": "follow_ups",
        "count": 3,
        "path": "/app/activities?view=contacts",
    }


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("feed", "/app/activities"),
        ("tasks", "/app/tasks"),
        ("delivery", "/app/delivery"),
        (TEST_KIND, "/app/notifications"),
    ],
)
def test_every_kind_opens_its_own_page(kind: str, path: str) -> None:
    assert json.loads(PushMessage(kind, 1).payload())["path"] == path


def test_a_message_of_an_unknown_kind_or_without_a_count_cannot_exist() -> None:
    with pytest.raises(DomainInvariantError) as unknown:
        PushMessage("orders", 1)
    assert unknown.value.code == "push_kind_unknown"
    for count in (0, -1, True):
        with pytest.raises(DomainInvariantError) as invalid:
            PushMessage(PushKind.FEED, count)
        assert invalid.value.code == "push_count_invalid"


def test_the_first_event_is_pushed_at_once() -> None:
    event = uuid4()

    plan = plan_dispatch(DispatchState(), event_id=event, count=1, now=NOW)

    assert plan.send_count == 1
    assert plan.flush_at is None
    assert plan.state == DispatchState(
        last_sent_at=NOW, pending_count=0, sending_event_id=event, sending_count=1
    )


def test_events_within_15_minutes_are_counted_and_sent_together() -> None:
    first = plan_dispatch(DispatchState(), event_id=uuid4(), count=1, now=NOW)

    second = plan_dispatch(
        first.state, event_id=uuid4(), count=2, now=NOW + timedelta(minutes=1)
    )
    third = plan_dispatch(
        second.state, event_id=uuid4(), count=1, now=NOW + timedelta(minutes=14)
    )

    # Held back; one job is asked for, at the end of the 15 minutes.
    assert second.send_count is None
    assert second.flush_at == NOW + PUSH_THROTTLE
    assert third.send_count is None
    assert third.flush_at is None
    assert third.state.pending_count == 3
    assert third.state.last_sent_at == NOW

    flush_event = uuid4()
    flushed = plan_dispatch(
        third.state, event_id=flush_event, count=0, now=NOW + PUSH_THROTTLE
    )

    assert flushed.send_count == 3
    assert flushed.state == DispatchState(
        last_sent_at=NOW + PUSH_THROTTLE,
        pending_count=0,
        sending_event_id=flush_event,
        sending_count=3,
    )


def test_an_event_after_15_minutes_takes_the_held_back_ones_along() -> None:
    state = DispatchState(last_sent_at=NOW, pending_count=2)

    plan = plan_dispatch(
        state, event_id=uuid4(), count=1, now=NOW + timedelta(minutes=15)
    )

    assert plan.send_count == 3


def test_a_flush_with_nothing_held_back_sends_nothing() -> None:
    state = DispatchState(last_sent_at=NOW)

    plan = plan_dispatch(state, event_id=uuid4(), count=0, now=NOW + PUSH_THROTTLE)

    assert plan.send_count is None
    assert plan.flush_at is None
    assert plan.state == state


def test_a_job_that_runs_again_sends_its_count_again_and_counts_once() -> None:
    event = uuid4()
    first = plan_dispatch(DispatchState(), event_id=event, count=2, now=NOW)

    again = plan_dispatch(
        first.state, event_id=event, count=2, now=NOW + timedelta(seconds=30)
    )

    assert again.send_count == 2
    assert again.state == first.state


def test_a_flush_that_comes_early_keeps_the_count() -> None:
    state = DispatchState(last_sent_at=NOW, pending_count=2)

    plan = plan_dispatch(
        state, event_id=uuid4(), count=0, now=NOW + timedelta(minutes=5)
    )

    assert plan.send_count is None
    assert plan.state.pending_count == 2
    # The job that was asked for with the first held-back event still comes.
    assert plan.flush_at is None


@pytest.mark.parametrize(
    ("moment", "due"),
    [
        # Winter: Berlin is UTC+1.
        (datetime(2026, 11, 10, 6, 59, tzinfo=timezone.utc), False),
        (datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 10, 18, 59, tzinfo=timezone.utc), True),
        (datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc), False),
        # Summer: Berlin is UTC+2.
        (datetime(2026, 7, 10, 5, 59, tzinfo=timezone.utc), False),
        (datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc), True),
    ],
)
def test_follow_ups_are_announced_from_8_club_time(moment: datetime, due: bool) -> None:
    assert follow_up_push_due(moment) is due


def test_a_device_is_removed_after_failures_on_several_days_only() -> None:
    """Five messages in a row the push service did not take, on at least
    three different days, the first at least three days ago."""
    since = NOW - DEVICE_FAILURE_PERIOD
    assert (DEVICE_FAILURE_LIMIT, DEVICE_FAILURE_DAYS, DEVICE_FAILURE_PERIOD) == (
        5,
        3,
        timedelta(days=3),
    )
    assert device_is_dead(5, since, 3, now=NOW) is True
    assert device_is_dead(50, since, 9, now=NOW) is True
    # Two short outages days apart: one failure on Monday, four on Friday.
    assert device_is_dead(5, NOW - timedelta(days=4), 2, now=NOW) is False
    # Many failures within one long weekend: not for long enough.
    assert device_is_dead(50, NOW - timedelta(days=2, hours=23), 3, now=NOW) is False
    # Little traffic: not often enough.
    assert device_is_dead(4, NOW - timedelta(days=30), 4, now=NOW) is False
    assert device_is_dead(0, None, 0, now=NOW) is False


def test_only_an_answer_of_the_push_service_blames_the_device() -> None:
    assert PushResult(PushOutcome.REJECTED, "fcm.googleapis.com", 403).blames_device
    assert PushResult(PushOutcome.UNAVAILABLE, "fcm.googleapis.com", 503).blames_device
    # No answer at all (no route, DNS, timeout) is our side.
    assert not PushResult(PushOutcome.UNAVAILABLE, "fcm.googleapis.com").blames_device
    assert not PushResult(PushOutcome.UNAVAILABLE, "").blames_device
    assert not PushResult(
        PushOutcome.DELIVERED, "fcm.googleapis.com", 201
    ).blames_device
    assert not PushResult(PushOutcome.GONE, "fcm.googleapis.com", 410).blames_device
