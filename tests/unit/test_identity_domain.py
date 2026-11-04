from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from leonaid.bootstrap.api import module_navigation
from leonaid.application.errors import ApplicationError
from leonaid.application.identity import (
    AccountStatusChange,
    ROLE_LABELS,
    STATUS_LABELS,
    MemberDirectoryMember,
    MemberDirectoryMembership,
    MemberDirectoryQuery,
    RoleAssignmentChange,
    navigation_for,
    paginate_member_directory,
)
from leonaid.adapters.postgres.identity import (
    replayed_role_assignment,
    replayed_status_change,
    role_assignment_receipt,
    status_change_receipt,
)
from leonaid.domain.actions import CharityActionStatus
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
    can_manage_action_roles,
    OPEN_ACTION_STATUSES,
    AccessRemoval,
    AdminCoverage,
    AdminInvariant,
    admin_invariant_violation,
    charity_admin_required,
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


def test_status_change_receipt_round_trips_asyncpg_json_text() -> None:
    changed = account(AccountStatus.ACTIVE).transition_to(AccountStatus.SUSPENDED)
    receipt = status_change_receipt(
        AccountStatusChange(
            account=changed,
            previous_status=AccountStatus.ACTIVE,
            revoked_session_count=2,
        )
    )

    replayed = replayed_status_change(json.dumps(receipt))

    assert replayed.account == changed
    assert replayed.previous_status is AccountStatus.ACTIVE
    assert replayed.revoked_session_count == 2
    assert replayed.replayed is True


@pytest.mark.parametrize(
    ("change", "expected_role"),
    (
        (
            RoleAssignmentChange(
                user_id=KLARA_ID,
                revision=2,
                role=GlobalRole.FINANCE_READER,
                enabled=True,
            ),
            GlobalRole.FINANCE_READER,
        ),
        (
            RoleAssignmentChange(
                user_id=KLARA_ID,
                revision=3,
                role=ActionRole.ACQUIRER,
                enabled=False,
                action_id=ACTIVE_ACTION_ID,
                action_name="Krapfentaxi 2026",
            ),
            ActionRole.ACQUIRER,
        ),
    ),
)
def test_role_assignment_receipt_round_trips_asyncpg_json_text(
    change: RoleAssignmentChange,
    expected_role: GlobalRole | ActionRole,
) -> None:
    replayed = replayed_role_assignment(json.dumps(role_assignment_receipt(change)))

    assert replayed == RoleAssignmentChange(
        user_id=change.user_id,
        revision=change.revision,
        role=expected_role,
        enabled=change.enabled,
        action_id=change.action_id,
        action_name=change.action_name,
        replayed=True,
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
                revision=1,
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
    assert changed.revision == 2


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


def test_account_requires_positive_revision() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        UserAccount(
            id=KLARA_ID,
            email="klara.kern@leonaid.invalid",
            display_name="Klara Kern",
            status=AccountStatus.ACTIVE,
            revision=0,
        )

    assert captured.value.code == "account_revision_invalid"


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


def test_navigation_gives_acquirer_surveys_without_other_backoffice_access() -> None:
    acquirer = IdentityPrincipal(
        account=account(AccountStatus.ACTIVE),
        global_roles=frozenset(),
        action_memberships=(
            ActionMembership(
                id=UUID("21000000-0000-4000-8000-000000000020"),
                action_id=ACTIVE_ACTION_ID,
                action_name="Krapfentaxi 2026",
                user_id=KLARA_ID,
                role=ActionRole.ACQUIRER,
                active_from=NOW,
            ),
        ),
    )

    navigation = navigation_for(acquirer, module_navigation(frozenset())(acquirer))

    assert {item.key for item in navigation if item.surface == "web"} == {
        "surveys",
        "tasks",
        "materials",
        "knowledge",
        "inbox",
    }
    assert {(item.surface, item.key) for item in navigation} >= {
        ("pwa", "overview-pwa"),
        ("pwa", "surveys"),
        ("pwa", "tasks"),
        ("pwa", "sponsors"),
        ("pwa", "activities"),
        ("pwa", "commitment"),
    }


@pytest.mark.parametrize(
    ("global_roles", "action_role"),
    (
        (frozenset({GlobalRole.SYSTEM_ADMIN}), None),
        (frozenset({GlobalRole.FINANCE_READER}), None),
        (frozenset(), ActionRole.CHARITY_ADMIN),
        (frozenset(), ActionRole.FINANCE_READER),
    ),
)
def test_navigation_keeps_backoffice_overview_for_authorized_roles(
    global_roles: frozenset[GlobalRole],
    action_role: ActionRole | None,
) -> None:
    memberships = (
        (
            ActionMembership(
                id=UUID("21000000-0000-4000-8000-000000000021"),
                action_id=ACTIVE_ACTION_ID,
                action_name="Krapfentaxi 2026",
                user_id=KLARA_ID,
                role=action_role,
                active_from=NOW,
            ),
        )
        if action_role is not None
        else ()
    )
    principal = IdentityPrincipal(
        account=account(AccountStatus.ACTIVE),
        global_roles=global_roles,
        action_memberships=memberships,
    )

    navigation = navigation_for(principal)

    assert any(
        item.surface == "web" and item.key == "overview-web" for item in navigation
    )
    microsites = [item for item in navigation if item.key == "microsite"]
    allowed = principal.is_system_admin or action_role is ActionRole.CHARITY_ADMIN
    assert len(microsites) == int(allowed)
    if allowed:
        assert microsites[0].surface == "web"
        assert microsites[0].href == "/_emdash/admin/content/campaign_pages"


@pytest.mark.parametrize(
    ("global_roles", "action_role", "managed"),
    (
        (frozenset({GlobalRole.SYSTEM_ADMIN}), None, True),
        (frozenset(), ActionRole.CHARITY_ADMIN, True),
        (frozenset(), ActionRole.FINANCE_READER, False),
        (frozenset(), ActionRole.ACQUIRER, False),
    ),
)
@pytest.mark.parametrize("delivery", (True, False))
def test_delivery_navigation_needs_a_managed_action_with_delivery(
    global_roles: frozenset[GlobalRole],
    action_role: ActionRole | None,
    managed: bool,
    delivery: bool,
) -> None:
    memberships = (
        (
            ActionMembership(
                id=UUID("21000000-0000-4000-8000-000000000022"),
                action_id=ACTIVE_ACTION_ID,
                action_name="Krapfentaxi 2026",
                user_id=KLARA_ID,
                role=action_role,
                active_from=NOW,
            ),
        )
        if action_role is not None
        else ()
    )
    principal = IdentityPrincipal(
        account=account(AccountStatus.ACTIVE),
        global_roles=global_roles,
        action_memberships=memberships,
    )

    items = [
        item
        for item in navigation_for(principal, delivery=delivery)
        if item.key == "delivery"
    ]

    assert len(items) == int(managed and delivery)
    if items:
        assert (items[0].surface, items[0].href) == ("web", "/admin/delivery")


def test_role_management_matrix_separates_global_and_action_scopes() -> None:
    charity_admin = IdentityPrincipal(
        account=account(AccountStatus.ACTIVE),
        global_roles=frozenset(),
        action_memberships=(
            ActionMembership(
                id=UUID("21000000-0000-4000-8000-000000000010"),
                action_id=ACTIVE_ACTION_ID,
                action_name="Krapfentaxi 2026",
                user_id=KLARA_ID,
                role=ActionRole.CHARITY_ADMIN,
                active_from=NOW,
            ),
        ),
    )
    system_admin = IdentityPrincipal(
        account=account(AccountStatus.ACTIVE),
        global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}),
        action_memberships=(),
    )

    assert can_manage_action_roles(charity_admin, ACTIVE_ACTION_ID) is True
    assert can_manage_action_roles(charity_admin, ARCHIVED_ACTION_ID) is False
    assert can_manage_action_roles(system_admin, ACTIVE_ACTION_ID) is True
    assert can_manage_action_roles(system_admin, ARCHIVED_ACTION_ID) is True


def test_open_actions_need_a_lead() -> None:
    assert OPEN_ACTION_STATUSES == {
        CharityActionStatus.DRAFT,
        CharityActionStatus.SCHEDULED,
        CharityActionStatus.ACTIVE,
    }
    for status in CharityActionStatus:
        assert charity_admin_required(status) is (status in OPEN_ACTION_STATUSES)


_ADMIN_A = UUID("90000000-0000-4000-8000-00000000000a")
_ADMIN_B = UUID("90000000-0000-4000-8000-00000000000b")
_LEAD_A = UUID("90000000-0000-4000-8000-0000000000a1")
_LEAD_B = UUID("90000000-0000-4000-8000-0000000000b1")
_ACTION_1 = UUID("90000000-0000-4000-8000-000000000001")
_ACTION_2 = UUID("90000000-0000-4000-8000-000000000002")


def _coverage(
    admins: set[UUID], leads: dict[UUID, set[UUID]] | None = None
) -> AdminCoverage:
    return AdminCoverage(
        system_admins=frozenset(admins),
        open_action_leads={
            key: frozenset(value) for key, value in (leads or {}).items()
        },
    )


def test_last_system_admin_keeps_role_and_access() -> None:
    alone = _coverage({_ADMIN_A})
    for removal in (
        AccessRemoval.system_admin_role(_ADMIN_A),
        AccessRemoval.deactivation(_ADMIN_A),
    ):
        assert (
            admin_invariant_violation(alone, removal)
            is AdminInvariant.LAST_SYSTEM_ADMIN
        )
    pair = _coverage({_ADMIN_A, _ADMIN_B})
    assert admin_invariant_violation(pair, AccessRemoval.deactivation(_ADMIN_A)) is None
    assert (
        admin_invariant_violation(pair, AccessRemoval.system_admin_role(_ADMIN_B))
        is None
    )
    # Someone who is not an active system admin removes nothing.
    assert admin_invariant_violation(alone, AccessRemoval.deactivation(_LEAD_A)) is None


def test_last_lead_of_an_open_action_keeps_role_and_access() -> None:
    coverage = _coverage(
        {_ADMIN_A},
        {_ACTION_1: {_LEAD_A}, _ACTION_2: {_LEAD_A, _LEAD_B}},
    )
    assert (
        admin_invariant_violation(coverage, AccessRemoval.lead_role(_LEAD_A, _ACTION_1))
        is AdminInvariant.LAST_CHARITY_ADMIN
    )
    # Suspension and archival take every lead role at once.
    assert (
        admin_invariant_violation(coverage, AccessRemoval.deactivation(_LEAD_A))
        is AdminInvariant.LAST_CHARITY_ADMIN
    )
    # A second active lead covers the action.
    assert (
        admin_invariant_violation(coverage, AccessRemoval.lead_role(_LEAD_A, _ACTION_2))
        is None
    )
    assert (
        admin_invariant_violation(coverage, AccessRemoval.deactivation(_LEAD_B)) is None
    )
    # The system-admin role is not a lead role.
    assert (
        admin_invariant_violation(
            _coverage({_LEAD_A, _ADMIN_A}, {_ACTION_1: {_LEAD_A}}),
            AccessRemoval.system_admin_role(_LEAD_A),
        )
        is None
    )


def test_existing_gaps_do_not_block_unrelated_changes() -> None:
    # No active system admin left already, and an action without any lead:
    # changes that remove neither are allowed.
    coverage = _coverage(set(), {_ACTION_1: set(), _ACTION_2: {_LEAD_A, _LEAD_B}})
    assert (
        admin_invariant_violation(coverage, AccessRemoval.deactivation(_LEAD_B)) is None
    )
    assert (
        admin_invariant_violation(coverage, AccessRemoval.system_admin_role(_ADMIN_A))
        is None
    )


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
