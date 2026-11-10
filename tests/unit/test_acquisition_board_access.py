"""Who may open the action-wide acquisition board (the web pipeline).

The board follows the access levels of the assignments themselves
(``authorized_scope``): the action's charity admins and every system admin.
A sponsor hit of the search links here for exactly these accounts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from leonaid.application.activities import AcquisitionActivityService
from leonaid.application.errors import PermissionDenied
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)

ACTION = UUID("a0000000-0000-4000-8000-000000000001")
OTHER = UUID("b0000000-0000-4000-8000-000000000002")
SINCE = datetime(2025, 11, 3, 12, 0, tzinfo=timezone.utc)


def principal(
    *memberships: tuple[UUID, ActionRole],
    system_admin: bool = False,
    status: AccountStatus = AccountStatus.ACTIVE,
) -> IdentityPrincipal:
    user_id = uuid4()
    return IdentityPrincipal(
        account=UserAccount(user_id, f"{user_id}@example.test", "Klara", status),
        global_roles=(
            frozenset({GlobalRole.SYSTEM_ADMIN}) if system_admin else frozenset()
        ),
        action_memberships=tuple(
            ActionMembership(
                id=uuid4(),
                action_id=action_id,
                action_name="Krapfentaxi",
                user_id=user_id,
                role=role,
                active_from=SINCE,
            )
            for action_id, role in memberships
        ),
    )


def service() -> AcquisitionActivityService:
    # The permission check runs before any dependency is touched.
    untouched = cast(Any, object())
    return AcquisitionActivityService(untouched, untouched, untouched)


@pytest.mark.parametrize(
    "actor",
    [
        principal((ACTION, ActionRole.CHARITY_ADMIN)),
        # No membership at all: the system admin manages every action.
        principal(system_admin=True),
        principal((ACTION, ActionRole.ACQUIRER), system_admin=True),
    ],
)
def test_managers_may_open_the_action_wide_board(actor: IdentityPrincipal) -> None:
    AcquisitionActivityService._require_charity_admin(actor, ACTION)  # noqa: SLF001


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actor",
    [
        principal((ACTION, ActionRole.ACQUIRER)),
        principal((ACTION, ActionRole.FINANCE_READER)),
        principal((OTHER, ActionRole.CHARITY_ADMIN)),
        principal(),
        principal(system_admin=True, status=AccountStatus.SUSPENDED),
        principal((ACTION, ActionRole.CHARITY_ADMIN), status=AccountStatus.SUSPENDED),
    ],
)
async def test_everyone_else_is_refused(actor: IdentityPrincipal) -> None:
    with pytest.raises(PermissionDenied) as error:
        await service().board(actor, ACTION, action_wide=True)
    assert error.value.code == "charity_admin_required"
