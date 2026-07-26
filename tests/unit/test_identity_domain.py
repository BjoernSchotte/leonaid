from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)

SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ACTIVE_ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ARCHIVED_ACTION_ID = UUID("20000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)


def account(status: AccountStatus) -> UserAccount:
    return UserAccount(
        id=KLARA_ID,
        email="klara.kern@leonaid.invalid",
        display_name="Klara Kern",
        status=status,
    )


@pytest.mark.parametrize(
    ("source", "target"),
    (
        (AccountStatus.INVITED, AccountStatus.ACTIVE),
        (AccountStatus.ACTIVE, AccountStatus.SUSPENDED),
        (AccountStatus.ACTIVE, AccountStatus.ARCHIVED),
        (AccountStatus.SUSPENDED, AccountStatus.ACTIVE),
        (AccountStatus.SUSPENDED, AccountStatus.ARCHIVED),
    ),
)
def test_account_allows_every_declared_status_transition(
    source: AccountStatus,
    target: AccountStatus,
) -> None:
    changed = account(source).transition_to(target)

    assert changed.status is target
    assert changed.email == "klara.kern@leonaid.invalid"


@pytest.mark.parametrize(
    ("source", "target"),
    (
        (AccountStatus.INVITED, AccountStatus.SUSPENDED),
        (AccountStatus.INVITED, AccountStatus.ARCHIVED),
        (AccountStatus.ACTIVE, AccountStatus.INVITED),
        (AccountStatus.SUSPENDED, AccountStatus.INVITED),
        (AccountStatus.ARCHIVED, AccountStatus.ACTIVE),
        (AccountStatus.ARCHIVED, AccountStatus.SUSPENDED),
    ),
)
def test_account_rejects_every_forbidden_status_transition(
    source: AccountStatus,
    target: AccountStatus,
) -> None:
    with pytest.raises(
        DomainInvariantError,
        match="Kontostatus darf nicht",
    ) as captured:
        account(source).transition_to(target)

    assert captured.value.code == "account_status_transition_invalid"


def test_login_email_is_normalized_and_immutable() -> None:
    user = account(AccountStatus.ACTIVE)

    with pytest.raises(FrozenInstanceError):
        user.email = "andere@leonaid.invalid"  # type: ignore[misc]
    with pytest.raises(DomainInvariantError, match="Login-E-Mail"):
        UserAccount(
            id=KLARA_ID,
            email="Klara.Kern@leonaid.invalid",
            display_name="Klara Kern",
            status=AccountStatus.ACTIVE,
        )


def test_principal_keeps_global_and_action_roles_separate() -> None:
    active_admin = ActionMembership(
        id=UUID("21000000-0000-4000-8000-000000000001"),
        action_id=ACTIVE_ACTION_ID,
        action_name="Krapfentaxi 2026",
        user_id=KLARA_ID,
        role=ActionRole.CHARITY_ADMIN,
        active_from=NOW - timedelta(days=10),
    )
    archived_finance = ActionMembership(
        id=UUID("21000000-0000-4000-8000-000000000002"),
        action_id=ARCHIVED_ACTION_ID,
        action_name="Krapfentaxi 2025",
        user_id=KLARA_ID,
        role=ActionRole.FINANCE_READER,
        active_from=NOW - timedelta(days=400),
    )
    principal = IdentityPrincipal(
        account=account(AccountStatus.ACTIVE),
        global_roles=frozenset({GlobalRole.FINANCE_READER}),
        action_memberships=(active_admin, archived_finance),
    )

    assert principal.global_roles == frozenset({GlobalRole.FINANCE_READER})
    assert principal.roles_for(ACTIVE_ACTION_ID) == frozenset(
        {ActionRole.CHARITY_ADMIN}
    )
    assert principal.roles_for(ARCHIVED_ACTION_ID) == frozenset(
        {ActionRole.FINANCE_READER}
    )
    assert principal.is_system_admin is False


def test_membership_period_is_timezone_aware_and_end_exclusive() -> None:
    membership = ActionMembership(
        id=UUID("21000000-0000-4000-8000-000000000001"),
        action_id=ACTIVE_ACTION_ID,
        action_name="Krapfentaxi 2026",
        user_id=KLARA_ID,
        role=ActionRole.CHARITY_ADMIN,
        active_from=NOW,
        active_until=NOW + timedelta(days=1),
        delegate_user_id=SYSTEM_ID,
    )

    assert membership.active_at(NOW) is True
    assert membership.active_at(NOW + timedelta(hours=23)) is True
    assert membership.active_at(NOW + timedelta(days=1)) is False
