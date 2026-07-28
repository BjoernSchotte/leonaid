from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from leonaid.application.errors import ApplicationError
from leonaid.application.identity import (
    ROLE_LABELS,
    STATUS_LABELS,
    MemberDirectoryMember,
    MemberDirectoryMembership,
    MemberDirectoryQuery,
    paginate_member_directory,
)
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
GOLDEN_PATH = Path(__file__).parents[1] / "fixtures" / "golden" / "v1" / "dataset.json"


def account(status: AccountStatus) -> UserAccount:
    return UserAccount(
        id=KLARA_ID,
        email="klara.kern@leonaid.invalid",
        display_name="Klara Kern",
        status=status,
    )


def golden_directory_members() -> tuple[MemberDirectoryMember, ...]:
    dataset = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    actions = {item["id"]: item["name"] for item in dataset["actions"]}
    membership_role = {
        "CHARITY_ADMIN": ActionRole.CHARITY_ADMIN,
        "ACQUIRER": ActionRole.ACQUIRER,
        "FINANCE": ActionRole.FINANCE_READER,
        "DRIVER": ActionRole.DRIVER,
    }
    memberships_by_user: dict[str, list[MemberDirectoryMembership]] = {}
    for item in dataset["actionMemberships"]:
        role = membership_role[item["role"]]
        memberships_by_user.setdefault(item["userId"], []).append(
            MemberDirectoryMembership(
                action_id=UUID(item["actionId"]),
                action_name=actions[item["actionId"]],
                role=role,
                role_label=ROLE_LABELS[role],
            )
        )
    statuses = {
        "INVITED": AccountStatus.INVITED,
        "ACTIVE": AccountStatus.ACTIVE,
        "LOCKED": AccountStatus.SUSPENDED,
        "ARCHIVED": AccountStatus.ARCHIVED,
    }
    result: list[MemberDirectoryMember] = []
    for item in dataset["users"]:
        status = statuses[item["status"]]
        global_roles = (
            (GlobalRole.SYSTEM_ADMIN,) if item["role"] == "SYSTEM_ADMIN" else ()
        )
        result.append(
            MemberDirectoryMember(
                user_id=UUID(item["id"]),
                display_name=f"{item['givenName']} {item['familyName']}",
                email=item["email"],
                status=status,
                status_label=STATUS_LABELS[status],
                global_roles=global_roles,
                global_role_labels=tuple(ROLE_LABELS[role] for role in global_roles),
                action_memberships=tuple(memberships_by_user.get(item["id"], ())),
                last_login_at=None,
                active_session_count=0,
            )
        )
    return tuple(result)


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


def test_member_directory_filters_real_golden_domain_objects() -> None:
    members = golden_directory_members()

    search_page, search_total, _ = paginate_member_directory(
        members,
        MemberDirectoryQuery(search="anna akquise"),
    )
    suspended_page, suspended_total, _ = paginate_member_directory(
        members,
        MemberDirectoryQuery(status=AccountStatus.SUSPENDED),
    )
    foreign_action_page, foreign_action_total, _ = paginate_member_directory(
        members,
        MemberDirectoryQuery(action_id=UUID("20000000-0000-4000-8000-000000000003")),
    )

    assert [item.display_name for item in search_page] == ["Anna Akquise"]
    assert search_total == 1
    assert [item.display_name for item in suspended_page] == ["Gesa Gesperrt"]
    assert suspended_total == 1
    assert [item.display_name for item in foreign_action_page] == ["Felix Fremd"]
    assert foreign_action_total == 1


def test_member_directory_cursor_follows_stable_golden_sort_order() -> None:
    members = golden_directory_members()

    first_page, total, next_cursor = paginate_member_directory(
        members,
        MemberDirectoryQuery(limit=3),
    )
    assert [item.display_name for item in first_page] == [
        "Anna Akquise",
        "Bernd Binder",
        "Carla Club",
    ]
    assert total == 8
    assert next_cursor is not None

    second_page, second_total, second_cursor = paginate_member_directory(
        members,
        MemberDirectoryQuery(limit=3, cursor=next_cursor),
    )
    assert [item.display_name for item in second_page] == [
        "Felix Fremd",
        "Finn Finanzen",
        "Gesa Gesperrt",
    ]
    assert second_total == 8
    assert second_cursor is not None


def test_member_directory_rejects_tampered_cursor() -> None:
    with pytest.raises(ApplicationError) as captured:
        paginate_member_directory(
            golden_directory_members(),
            MemberDirectoryQuery(cursor="not-a-member-cursor"),
        )

    assert captured.value.code == "member_cursor_invalid"
