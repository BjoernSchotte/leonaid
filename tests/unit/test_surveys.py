from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.domain.surveys import (
    Capability,
    SurveyStatus,
    effective_response_status,
    may_access_survey,
    require_transition,
)


def test_timeout_boundary_and_completed_response_are_independent():
    start = datetime(2026, 9, 6, tzinfo=timezone.utc)
    kwargs = dict(created_at=start, last_answer_changed_at=None, timeout_seconds=30)
    assert (
        effective_response_status(
            "in_progress", now=start + timedelta(seconds=29), **kwargs
        )
        == "in_progress"
    )
    assert (
        effective_response_status(
            "in_progress", now=start + timedelta(seconds=30), **kwargs
        )
        == "partial"
    )
    assert (
        effective_response_status("completed", now=start + timedelta(days=3), **kwargs)
        == "completed"
    )
    kwargs["last_answer_changed_at"] = start + timedelta(seconds=29)
    assert (
        effective_response_status(
            "partial", now=start + timedelta(seconds=31), **kwargs
        )
        == "partial"
    )


def test_restore_cannot_reopen_published_survey():
    with pytest.raises(DomainInvariantError):
        require_transition(
            SurveyStatus.DELETED, SurveyStatus.ACTIVE, has_published_version=True
        )
    with pytest.raises(DomainInvariantError):
        require_transition(
            SurveyStatus.DELETED, SurveyStatus.DRAFT, has_published_version=True
        )
    require_transition(
        SurveyStatus.DELETED, SurveyStatus.ENDED, has_published_version=True
    )
    require_transition(
        SurveyStatus.DELETED, SurveyStatus.DRAFT, has_published_version=False
    )


def test_explicit_grant_does_not_escape_action_membership():
    actor_id = UUID(int=1)
    principal = IdentityPrincipal(
        account=UserAccount(
            actor_id, "member@example.invalid", "Member", AccountStatus.ACTIVE
        ),
        global_roles=frozenset(),
        action_memberships=(),
    )
    kwargs = dict(
        owner_user_id=UUID(int=2),
        capability=Capability.VIEW_AGGREGATES,
        grants=frozenset({Capability.VIEW_AGGREGATES}),
    )
    assert may_access_survey(principal, action_id=None, **kwargs)
    assert not may_access_survey(principal, action_id=UUID(int=3), **kwargs)
    assert not may_access_survey(
        principal, action_id=None, **{**kwargs, "capability": Capability.READ_RESPONSES}
    )


def test_accepted_answer_change_is_the_resumption_boundary():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    assert (
        effective_response_status(
            "in_progress",
            created_at=now,
            last_answer_changed_at=now,
            timeout_seconds=30,
            now=now,
        )
        == "in_progress"
    )
    # A persisted partial marker (including survey closure) is sticky until a write
    # changes the stored status. Merely reading never resumes the participation.
    assert (
        effective_response_status(
            "partial",
            created_at=now,
            last_answer_changed_at=now,
            timeout_seconds=30,
            now=now,
        )
        == "partial"
    )
