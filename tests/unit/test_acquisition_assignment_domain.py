from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from leonaid.domain.acquisition import (
    AcquisitionAssignment,
    AssignmentPartyKind,
    AssignmentState,
    AssignmentStatus,
)
from leonaid.domain.errors import DomainInvariantError

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMPANY_ID = UUID("40000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
CREATED_AT = datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc)


def assignment(
    *,
    assignment_id: str,
    acquirer_id: UUID,
    name: str,
) -> AcquisitionAssignment:
    return AcquisitionAssignment(
        id=UUID(assignment_id),
        action_id=ACTION_ID,
        party_kind=AssignmentPartyKind.COMPANY,
        party_id=COMPANY_ID,
        acquirer_user_id=acquirer_id,
        acquirer_display_name=name,
        state=AssignmentState(),
        revision=1,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def test_same_party_may_have_distinct_acquirer_assignments() -> None:
    anna = assignment(
        assignment_id="60000000-0000-4000-8000-000000000031",
        acquirer_id=ANNA_ID,
        name="Anna Akquise",
    )
    bernd = assignment(
        assignment_id="60000000-0000-4000-8000-000000000032",
        acquirer_id=BERND_ID,
        name="Bernd Binder",
    )

    assert anna.party_id == bernd.party_id
    assert anna.acquirer_user_id != bernd.acquirer_user_id


def test_work_update_normalizes_text_and_advances_exactly_one_revision() -> None:
    current = assignment(
        assignment_id="60000000-0000-4000-8000-000000000031",
        acquirer_id=ANNA_ID,
        name="Anna Akquise",
    )
    due_at = datetime(2026, 8, 3, 8, 30, tzinfo=timezone.utc)
    changed_at = datetime(2026, 7, 26, 9, 5, tzinfo=timezone.utc)

    changed = current.update_work(
        status=AssignmentStatus.CONTACTED,
        priority=2,
        next_action="  Angebot   persönlich nachfassen  ",
        due_at=due_at,
        occurred_at=changed_at,
    )

    assert changed.revision == 2
    assert changed.updated_at == changed_at
    assert changed.state == AssignmentState(
        status=AssignmentStatus.CONTACTED,
        priority=2,
        next_action="Angebot persönlich nachfassen",
        due_at=due_at,
    )
    assert current.state.snapshot(acquirer_user_id=ANNA_ID) == {
        "status": "open",
        "priority": 0,
        "nextAction": None,
        "dueAt": None,
        "acquirerUserId": str(ANNA_ID),
    }


def test_noop_does_not_invent_a_history_revision() -> None:
    current = assignment(
        assignment_id="60000000-0000-4000-8000-000000000031",
        acquirer_id=ANNA_ID,
        name="Anna Akquise",
    )

    unchanged = current.update_work(
        status=AssignmentStatus.OPEN,
        priority=0,
        next_action=None,
        due_at=None,
        occurred_at=datetime(2026, 7, 26, 9, 5, tzinfo=timezone.utc),
    )

    assert unchanged is current
    assert unchanged.revision == 1


def test_handover_is_terminal_and_cannot_be_smuggled_through_status_update() -> None:
    current = assignment(
        assignment_id="60000000-0000-4000-8000-000000000031",
        acquirer_id=ANNA_ID,
        name="Anna Akquise",
    )
    changed_at = datetime(2026, 7, 26, 9, 5, tzinfo=timezone.utc)

    with pytest.raises(DomainInvariantError, match="ausschließlich"):
        current.update_work(
            status=AssignmentStatus.HANDED_OVER,
            priority=0,
            next_action=None,
            due_at=None,
            occurred_at=changed_at,
        )

    handed_over = current.hand_over(occurred_at=changed_at)
    assert handed_over.state.status is AssignmentStatus.HANDED_OVER
    assert handed_over.revision == 2
    with pytest.raises(DomainInvariantError, match="nicht mehr bearbeitet"):
        handed_over.update_work(
            status=AssignmentStatus.OPEN,
            priority=0,
            next_action=None,
            due_at=None,
            occurred_at=changed_at,
        )


def test_state_rejects_invalid_priority_naive_due_date_and_long_next_action() -> None:
    with pytest.raises(DomainInvariantError, match="zwischen 0 und 3"):
        AssignmentState(priority=4)
    with pytest.raises(DomainInvariantError, match="Zeitzone"):
        AssignmentState(due_at=datetime(2026, 8, 3, 8, 30))
    with pytest.raises(DomainInvariantError, match="300 Zeichen"):
        AssignmentState(next_action="x" * 301)
