"""The one landing rule of the admin host (specs/multi-domain §6.7).

Björn, 2026-11-03: any acquirer role → acquisition app, even next to other
roles; otherwise system admin → /admin/system, charity admin → /admin/,
finance roles → /admin/invoices. A chosen start area wins while the member
has a role for it. Members without back-office roles start in the PWA.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.application.identity import (
    PreferredSurface,
    landing_path,
    navigation_for,
)
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.platform.base_paths import ADMIN_BASE, PWA_BASE
from leonaid.platform.navigation import NavigationItem

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
USER = UUID("10000000-0000-4000-8000-000000000042")
ACTION = UUID("30000000-0000-4000-8000-000000000001")
# Module pages every member gets in both apps.
MODULES = (
    NavigationItem("tasks", "Aufgaben", ADMIN_BASE + "tasks", "web"),
    NavigationItem("tasks", "Aufgaben", PWA_BASE + "tasks", "pwa"),
)


def principal(
    *roles: ActionRole, global_roles: frozenset[GlobalRole] = frozenset()
) -> IdentityPrincipal:
    return IdentityPrincipal(
        account=UserAccount(
            id=USER,
            email="member@leonaid.org",
            display_name="Member",
            status=AccountStatus.ACTIVE,
        ),
        global_roles=global_roles,
        action_memberships=tuple(
            ActionMembership(
                id=uuid4(),
                action_id=ACTION,
                action_name="Krapfentaxi 2026",
                user_id=USER,
                role=role,
                active_from=NOW,
            )
            for role in roles
        ),
    )


def land(
    member: IdentityPrincipal,
    preferred: PreferredSurface | None = None,
    *,
    delivery: bool = False,
) -> str:
    return landing_path(
        member, navigation_for(member, MODULES, delivery=delivery), preferred
    )


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        (principal(ActionRole.ACQUIRER), PWA_BASE),
        # An acquirer role wins over every back-office role (new rule).
        (principal(ActionRole.ACQUIRER, ActionRole.CHARITY_ADMIN), PWA_BASE),
        (
            principal(
                ActionRole.ACQUIRER, global_roles=frozenset({GlobalRole.SYSTEM_ADMIN})
            ),
            PWA_BASE,
        ),
        (
            principal(global_roles=frozenset({GlobalRole.SYSTEM_ADMIN})),
            ADMIN_BASE + "system",
        ),
        (principal(ActionRole.CHARITY_ADMIN), ADMIN_BASE),
        (principal(ActionRole.FINANCE_READER), ADMIN_BASE + "invoices"),
        (
            principal(global_roles=frozenset({GlobalRole.FINANCE_MANAGER})),
            ADMIN_BASE + "invoices",
        ),
        (
            principal(global_roles=frozenset({GlobalRole.FINANCE_READER})),
            ADMIN_BASE + "invoices",
        ),
        # Module pages alone open no back office: the PWA holds them too.
        (principal(), PWA_BASE),
    ],
)
def test_default_landing(member: IdentityPrincipal, expected: str) -> None:
    assert land(member) == expected


def test_driver_starts_in_the_pwa() -> None:
    assert land(principal(ActionRole.DRIVER), delivery=True) == PWA_BASE


def test_preference_wins_while_the_member_has_a_role_for_it() -> None:
    both = principal(ActionRole.ACQUIRER, ActionRole.CHARITY_ADMIN)
    assert land(both, PreferredSurface.WEB) == ADMIN_BASE
    assert land(both, PreferredSurface.PWA) == PWA_BASE
    admin = principal(global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}))
    # No PWA work: the preference is ignored, never a dead end.
    assert land(admin, PreferredSurface.PWA) == ADMIN_BASE + "system"
    acquirer = principal(ActionRole.ACQUIRER)
    assert land(acquirer, PreferredSurface.WEB) == PWA_BASE


def test_landing_is_always_below_a_base_path() -> None:
    for member in (
        principal(ActionRole.ACQUIRER),
        principal(ActionRole.CHARITY_ADMIN),
        principal(global_roles=frozenset({GlobalRole.SYSTEM_ADMIN})),
        principal(),
    ):
        for preferred in (None, PreferredSurface.WEB, PreferredSurface.PWA):
            assert land(member, preferred).startswith((ADMIN_BASE, PWA_BASE))
