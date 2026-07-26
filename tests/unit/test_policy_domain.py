from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.policies import (
    AcquisitionAccessLevel,
    AuthorizedPartyScope,
    has_action_role,
    may_manage_action,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
FOREIGN_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
COMPANY_ID = UUID("40000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("50000000-0000-4000-8000-000000000005")
NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


def principal(
    user_id: UUID,
    *,
    global_roles: frozenset[GlobalRole] = frozenset(),
    action_role: ActionRole | None = None,
) -> IdentityPrincipal:
    memberships = ()
    if action_role is not None:
        memberships = (
            ActionMembership(
                id=UUID("21000000-0000-4000-8000-000000000004"),
                action_id=ACTION_ID,
                action_name="Krapfentaxi 2026",
                user_id=user_id,
                role=action_role,
                active_from=NOW,
            ),
        )
    return IdentityPrincipal(
        account=UserAccount(
            id=user_id,
            email=f"{user_id}@leonaid.invalid",
            display_name="Golden Persona",
            status=AccountStatus.ACTIVE,
        ),
        global_roles=global_roles,
        action_memberships=memberships,
    )


def test_action_roles_are_central_and_system_admin_bypasses_membership() -> None:
    charity_admin = principal(ANNA_ID, action_role=ActionRole.CHARITY_ADMIN)
    acquirer = principal(ANNA_ID, action_role=ActionRole.ACQUIRER)
    system_admin = principal(
        SYSTEM_ID,
        global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}),
    )

    assert may_manage_action(charity_admin, ACTION_ID) is True
    assert may_manage_action(acquirer, ACTION_ID) is False
    assert has_action_role(
        acquirer,
        ACTION_ID,
        frozenset({ActionRole.ACQUIRER}),
    )
    assert may_manage_action(system_admin, FOREIGN_ACTION_ID) is True


def test_authorized_party_scope_never_expands_beyond_server_ids() -> None:
    scope = AuthorizedPartyScope(
        action_id=ACTION_ID,
        actor_user_id=ANNA_ID,
        access_level=AcquisitionAccessLevel.ASSIGNED,
        company_ids=frozenset({COMPANY_ID}),
        person_ids=frozenset({PERSON_ID}),
    )

    assert scope.allows_company(COMPANY_ID)
    assert not scope.allows_company(UUID("40000000-0000-4000-8000-000000000002"))
    assert scope.allows_person(PERSON_ID)
    assert not scope.allows_person(UUID("50000000-0000-4000-8000-000000000001"))
