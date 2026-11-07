"""Server rules the PWA offline queue relies on (PLAN §11, decisions D1, D5).

Pure rules only: the capture-time bound, the request hashes that bind an
``Idempotency-Key`` to its content, the price-guard inputs and the receipt
lifetime. The behaviour against PostgreSQL is proven in
``tests/integration/test_offline_capture_api.py`` (orders) and
``tools/activities/contract.py`` (activities, real Twenty).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from leonaid.application import activities, commitments
from leonaid.application.activities import activity_request_hash
from leonaid.application.commitments import (
    CommitmentCompletion,
    CommitmentDraft,
    CommitmentLineDraft,
)
from leonaid.application.errors import Conflict
from leonaid.domain.acquisition import (
    ActivityChannel,
    ActivityOutcome,
    AssignmentPartyKind,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.calendar import local_day
from leonaid.domain.captures import (
    CAPTURE_MAX_AGE,
    CAPTURE_MAX_LEAD,
    bounded_captured_at,
)
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
)
from leonaid.domain.errors import DomainInvariantError

ROOT = Path(__file__).resolve().parents[2]
RECEIVED = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
BERLIN = ZoneInfo("Europe/Berlin")
ACTION = UUID("20000000-0000-4000-8000-000000000001")
OFFERING = UUID("70000000-0000-4000-8000-000000000001")
# Computed with the code on main before the offline fields existed (M8): an
# old client's order and completion hashes must stay byte-identical (R3).
MAIN_ORDER_HASH = "cbef405a8ca54642ddaa8e41592ad7f85cb83e702085c5aba46a5428f305db8c"
MAIN_COMPLETION_HASH = (
    "fb485af6e2cfa76bd217f4e4d26277b36393291d96f34f3ea54ce5e2f7ff37bc"
)
# The activity hash is a new contract: a queued entry keeps its key across a
# Core update, so the canonical form must never change silently.
ACTIVITY_HASH = "12a52e1f873e6ed14ce53aad09ac71ace83438ec170a524369e8852c35dc3c21"


def test_queue_retention_and_server_bound_are_the_same_14_days() -> None:
    # D5: the queue keeps unsent entries 14 days; the server accepts them
    # for exactly as long, plus 5 minutes of device clock drift.
    assert CAPTURE_MAX_AGE == timedelta(days=14)
    assert CAPTURE_MAX_LEAD == timedelta(minutes=5)


@pytest.mark.parametrize(
    "captured_at",
    [
        RECEIVED - timedelta(days=14),
        RECEIVED - timedelta(hours=1),
        RECEIVED,
        RECEIVED + timedelta(minutes=5),
    ],
)
def test_capture_time_inside_the_window_is_kept(captured_at: datetime) -> None:
    assert bounded_captured_at(captured_at, received_at=RECEIVED) == captured_at


@pytest.mark.parametrize(
    "captured_at",
    [
        RECEIVED - timedelta(days=14, seconds=1),
        RECEIVED + timedelta(minutes=5, seconds=1),
        RECEIVED - timedelta(days=400),
    ],
)
def test_capture_time_outside_the_window_is_refused(captured_at: datetime) -> None:
    with pytest.raises(DomainInvariantError) as refused:
        bounded_captured_at(captured_at, received_at=RECEIVED)
    assert refused.value.code == "captured_at_out_of_range"


def test_capture_time_needs_an_offset_and_comes_back_in_utc() -> None:
    with pytest.raises(DomainInvariantError):
        bounded_captured_at(datetime(2026, 11, 7, 9), received_at=RECEIVED)
    local = datetime(2026, 11, 7, 10, 30, tzinfo=BERLIN)
    bounded = bounded_captured_at(local, received_at=RECEIVED)
    assert bounded.tzinfo is timezone.utc
    assert bounded == local


@pytest.mark.parametrize(
    ("captured_at", "day"),
    [
        # 00:30 in Berlin is still the previous UTC day, winter and summer.
        (datetime(2026, 11, 4, 0, 30, tzinfo=BERLIN), date(2026, 11, 4)),
        (datetime(2026, 7, 14, 0, 30, tzinfo=BERLIN), date(2026, 7, 14)),
    ],
)
def test_a_capture_at_half_past_midnight_belongs_to_the_club_day(
    captured_at: datetime, day: date
) -> None:
    received = captured_at + timedelta(hours=2)
    stored = bounded_captured_at(captured_at, received_at=received)
    assert stored.date() == day - timedelta(days=1)
    assert local_day(stored) == day


def test_queue_keys_match_the_unchanged_core_key_format() -> None:
    key = f"pwa-q:{uuid4()}"
    assert activities.IDEMPOTENCY_KEY.pattern == commitments.IDEMPOTENCY_KEY.pattern
    assert commitments.IDEMPOTENCY_KEY.fullmatch(key)
    assert not commitments.IDEMPOTENCY_KEY.fullmatch("short")
    assert not commitments.IDEMPOTENCY_KEY.fullmatch(":pwa-q:" + "a" * 10)


def _activity_hash(**changes: object) -> str:
    values: dict[str, object] = {
        "action_id": ACTION,
        "actor_user_id": UUID("10000000-0000-4000-8000-000000000004"),
        "party_kind": AssignmentPartyKind.COMPANY,
        "party_id": UUID("40000000-0000-4000-8000-000000000001"),
        "expected_revision": 3,
        "channel": ActivityChannel.IN_PERSON,
        "outcome": ActivityOutcome.REACHED,
        "note": "Am Stand getroffen.",
        "next_action": "Angebot schicken",
        "due_on": date(2026, 11, 12),
        "captured_at": datetime(2026, 11, 4, 9, 12, 30, tzinfo=BERLIN),
    }
    values.update(changes)
    return activity_request_hash(**values)  # type: ignore[arg-type]


def test_activity_hash_is_stable_across_offsets_of_the_same_instant() -> None:
    same_instant = datetime(2026, 11, 4, 8, 12, 30, tzinfo=timezone.utc)
    assert _activity_hash() == _activity_hash(captured_at=same_instant)
    assert _activity_hash() == ACTIVITY_HASH


@pytest.mark.parametrize(
    "change",
    [
        {"actor_user_id": uuid4()},
        {"action_id": uuid4()},
        {"party_id": uuid4()},
        {"expected_revision": 4},
        {"channel": ActivityChannel.PHONE},
        {"outcome": ActivityOutcome.DECLINED},
        {"note": "Andere Notiz."},
        {"next_action": None, "due_on": None},
        {"due_on": date(2026, 11, 13)},
        {"captured_at": None},
        {"captured_at": datetime(2026, 11, 4, 9, 13, tzinfo=BERLIN)},
    ],
)
def test_activity_hash_binds_every_field_of_the_capture(
    change: dict[str, object],
) -> None:
    # Same key with other content must be idempotency_conflict, and another
    # account can never replay someone else's activity with a copied key.
    assert _activity_hash(**change) != _activity_hash()


def _draft(**changes: object) -> CommitmentDraft:
    values: dict[str, object] = {
        "buyer": BuyerSnapshot(
            party_kind=CommitmentPartyKind.COMPANY,
            twenty_id=UUID("40000000-0000-4000-8000-000000000001"),
            display_name="Musterwerk GmbH",
            email=None,
        ),
        "invoice_recipient": None,
        "lines": (
            CommitmentLineDraft(
                offering_id=OFFERING,
                quantity=2,
                unit=OfferingUnit.BOX,
                quoted_unit_price_minor=3600,
            ),
        ),
    }
    values.update(changes)
    return CommitmentDraft(**values)  # type: ignore[arg-type]


def _fingerprint(draft: CommitmentDraft) -> str:
    return draft.fingerprint(
        action_id=ACTION,
        source=CommitmentSource.ACQUISITION,
        status=CommitmentStatus.REVIEW_READY,
    )


def test_order_hash_without_capture_time_is_the_pre_upgrade_hash() -> None:
    # Online capture ignores the client quote; the offline fields must not
    # change the hash of an old client's request (risk R3).
    unquoted = _draft(
        lines=(
            CommitmentLineDraft(
                offering_id=OFFERING, quantity=2, unit=OfferingUnit.BOX
            ),
        )
    )
    assert _fingerprint(_draft()) == MAIN_ORDER_HASH
    assert _fingerprint(unquoted) == MAIN_ORDER_HASH


def test_queued_order_hash_binds_capture_time_and_quoted_price() -> None:
    captured = datetime(2026, 11, 4, 9, 12, tzinfo=BERLIN)
    queued = _draft(captured_at=captured)
    assert _fingerprint(queued) != _fingerprint(_draft())
    # Accepting a new price is new content: a new key (PLAN §9.3, §11.3).
    repriced = _draft(
        captured_at=captured,
        lines=(
            CommitmentLineDraft(
                offering_id=OFFERING,
                quantity=2,
                unit=OfferingUnit.BOX,
                quoted_unit_price_minor=3800,
            ),
        ),
    )
    assert _fingerprint(repriced) != _fingerprint(queued)
    # The "ausgebucht" confirmation is no content: same key (PLAN §10.2).
    confirmed = _draft(captured_at=captured, allow_full_window=True)
    assert _fingerprint(confirmed) == _fingerprint(queued)


def test_queued_order_needs_the_price_the_acquirer_saw() -> None:
    with pytest.raises(DomainInvariantError) as refused:
        _draft(
            captured_at=RECEIVED,
            lines=(
                CommitmentLineDraft(
                    offering_id=OFFERING, quantity=1, unit=OfferingUnit.BOX
                ),
            ),
        )
    assert refused.value.code == "commitment_client_quote_required"


def test_completion_hash_without_capture_time_is_the_pre_upgrade_hash() -> None:
    def fingerprint(completion: CommitmentCompletion) -> str:
        return completion.fingerprint(
            action_id=ACTION,
            commitment_id=UUID("80000000-0000-4000-8000-000000000001"),
            actor_user_id=UUID("10000000-0000-4000-8000-000000000004"),
        )

    assert fingerprint(CommitmentCompletion()) == MAIN_COMPLETION_HASH
    assert (
        fingerprint(CommitmentCompletion(allow_full_window=True))
        == MAIN_COMPLETION_HASH
    )
    assert fingerprint(CommitmentCompletion(captured_at=RECEIVED)) != (
        MAIN_COMPLETION_HASH
    )


def test_application_errors_carry_json_details_for_the_queue() -> None:
    error = Conflict(
        "commitment_price_changed",
        "Preis geändert.",
        details={"totalMinor": 7600, "currency": "EUR"},
    )
    assert error.details == {"totalMinor": 7600, "currency": "EUR"}
    assert Conflict("x", "y").details is None


def test_command_receipts_are_never_deleted_in_bulk() -> None:
    # PLAN §11.5: receipts must outlive the 14-day queue retention; today
    # they are kept forever. The only deletes discard a command's own
    # unfinished receipt by key. A retention job must keep >= 30 days.
    deletes: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"TRUNCATE[^;]*command_receipt", text, re.I), path
        for match in re.finditer(
            r"DELETE\s+FROM\s+command_receipt(?P<rest>[^\"]*)", text, re.I
        ):
            deletes.append(f"{path.relative_to(ROOT)}")
            rest = " ".join(match.group("rest").split())
            assert "WHERE idempotency_key = $1" in rest, (path, rest)
            assert "AND result IS NULL" in rest, (path, rest)
    assert deletes, "the receipt scan found no statement at all"
    retention = ROOT / "src/leonaid/entrypoints/worker/retention.py"
    assert "command_receipt" not in retention.read_text(encoding="utf-8")
