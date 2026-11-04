"""Identity, role and action-membership invariants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.actions import CharityActionStatus
from leonaid.domain.errors import DomainInvariantError


class AccountStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class GlobalRole(StrEnum):
    SYSTEM_ADMIN = "system_admin"
    FINANCE_READER = "finance_reader"
    FINANCE_MANAGER = "finance_manager"


class ActionRole(StrEnum):
    CHARITY_ADMIN = "charity_admin"
    ACQUIRER = "acquirer"
    FINANCE_READER = "finance_reader"
    DRIVER = "driver"


ALLOWED_ACCOUNT_TRANSITIONS: dict[AccountStatus, frozenset[AccountStatus]] = {
    AccountStatus.INVITED: frozenset({AccountStatus.ACTIVE}),
    AccountStatus.ACTIVE: frozenset({AccountStatus.SUSPENDED, AccountStatus.ARCHIVED}),
    AccountStatus.SUSPENDED: frozenset({AccountStatus.ACTIVE, AccountStatus.ARCHIVED}),
    AccountStatus.ARCHIVED: frozenset(),
}


def require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantError(
            "identity_time_not_aware",
            f"{field} muss eine Zeitzone enthalten.",
        )


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: UUID
    email: str
    display_name: str
    status: AccountStatus
    email_verified_at: datetime | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if (
            self.email != self.email.casefold()
            or self.email.count("@") != 1
            or any(character.isspace() for character in self.email)
        ):
            raise DomainInvariantError(
                "login_email_invalid",
                "Die Login-E-Mail muss kleingeschrieben und gültig sein.",
            )
        if not self.display_name.strip():
            raise DomainInvariantError(
                "display_name_empty",
                "Der Anzeigename darf nicht leer sein.",
            )
        if self.email_verified_at is not None:
            require_aware(self.email_verified_at, "email_verified_at")
        if self.revision < 1:
            raise DomainInvariantError(
                "account_revision_invalid",
                "Die Kontorevision muss positiv sein.",
            )

    @property
    def can_authenticate(self) -> bool:
        return self.status is AccountStatus.ACTIVE

    def transition_to(self, target: AccountStatus) -> UserAccount:
        if target is self.status:
            return self
        if target not in ALLOWED_ACCOUNT_TRANSITIONS[self.status]:
            raise DomainInvariantError(
                "account_status_transition_invalid",
                f"Der Kontostatus darf nicht von {self.status.value} "
                f"nach {target.value} wechseln.",
            )
        return replace(self, status=target, revision=self.revision + 1)


@dataclass(frozen=True, slots=True)
class ActionMembership:
    id: UUID
    action_id: UUID
    action_name: str
    user_id: UUID
    role: ActionRole
    active_from: datetime
    active_until: datetime | None = None
    delegate_user_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.action_name.strip():
            raise DomainInvariantError(
                "action_name_empty",
                "Der Aktionsname darf nicht leer sein.",
            )
        require_aware(self.active_from, "active_from")
        if self.active_until is not None:
            require_aware(self.active_until, "active_until")
            if self.active_until <= self.active_from:
                raise DomainInvariantError(
                    "membership_period_invalid",
                    "Eine Mitgliedschaft muss nach ihrem Beginn enden.",
                )
        if self.delegate_user_id == self.user_id:
            raise DomainInvariantError(
                "membership_delegate_invalid",
                "Ein Mitglied kann sich nicht selbst vertreten.",
            )

    def active_at(self, moment: datetime) -> bool:
        require_aware(moment, "moment")
        return self.active_from <= moment and (
            self.active_until is None or moment < self.active_until
        )


@dataclass(frozen=True, slots=True)
class IdentityPrincipal:
    account: UserAccount
    global_roles: frozenset[GlobalRole]
    action_memberships: tuple[ActionMembership, ...]

    def __post_init__(self) -> None:
        if any(
            membership.user_id != self.account.id
            for membership in self.action_memberships
        ):
            raise DomainInvariantError(
                "membership_user_mismatch",
                "Alle Mitgliedschaften müssen zum Konto gehören.",
            )

    @property
    def is_system_admin(self) -> bool:
        return GlobalRole.SYSTEM_ADMIN in self.global_roles

    def roles_for(self, action_id: UUID) -> frozenset[ActionRole]:
        return frozenset(
            membership.role
            for membership in self.action_memberships
            if membership.action_id == action_id
        )


def can_manage_action_roles(
    principal: IdentityPrincipal,
    action_id: UUID,
) -> bool:
    """Return whether a principal may manage roles in one action scope."""

    return principal.is_system_admin or (
        ActionRole.CHARITY_ADMIN in principal.roles_for(action_id)
    )


#: Actions that can still be operated or changed and so need a lead.
OPEN_ACTION_STATUSES: frozenset[CharityActionStatus] = frozenset(
    {
        CharityActionStatus.DRAFT,
        CharityActionStatus.SCHEDULED,
        CharityActionStatus.ACTIVE,
    }
)


def charity_admin_required(status: CharityActionStatus) -> bool:
    """Whether an action in this status must keep an active lead. The only
    rule for it: server guard, directory flag and client all derive from
    :data:`OPEN_ACTION_STATUSES`."""

    return status in OPEN_ACTION_STATUSES


@dataclass(frozen=True, slots=True)
class AdminCoverage:
    """Who keeps the installation and its open actions manageable.

    Only active accounts count: a suspended, archived or invited account
    cannot sign in, so it covers nothing. ``open_action_leads`` maps each
    open action (draft, scheduled, active) to the active accounts with a
    current charity-admin membership.
    """

    system_admins: frozenset[UUID]
    open_action_leads: Mapping[UUID, frozenset[UUID]]


@dataclass(frozen=True, slots=True)
class AccessRemoval:
    """What one command takes away from one account."""

    user_id: UUID
    #: The account stops counting as system admin.
    system_admin: bool
    #: Actions where it stops counting as lead; ``None`` means every action.
    lead_actions: frozenset[UUID] | None

    @classmethod
    def deactivation(cls, user_id: UUID) -> AccessRemoval:
        """Suspension or archival: the account covers nothing any more."""

        return cls(user_id=user_id, system_admin=True, lead_actions=None)

    @classmethod
    def system_admin_role(cls, user_id: UUID) -> AccessRemoval:
        return cls(user_id=user_id, system_admin=True, lead_actions=frozenset())

    @classmethod
    def lead_role(cls, user_id: UUID, action_id: UUID) -> AccessRemoval:
        return cls(
            user_id=user_id,
            system_admin=False,
            lead_actions=frozenset({action_id}),
        )


class AdminInvariant(StrEnum):
    """The invariant a refused command would have broken."""

    LAST_SYSTEM_ADMIN = "last_system_admin"
    LAST_CHARITY_ADMIN = "last_charity_admin"


def admin_invariant_violation(
    coverage: AdminCoverage,
    removal: AccessRemoval,
) -> AdminInvariant | None:
    """Return the invariant the removal breaks, or ``None``.

    The installation keeps at least one active system admin, and every open
    action keeps at least one active lead. Only a removal that takes away
    the last one is refused; a gap that already exists does not block
    unrelated changes.
    """

    user = removal.user_id
    if (
        removal.system_admin
        and user in coverage.system_admins
        and not coverage.system_admins - {user}
    ):
        return AdminInvariant.LAST_SYSTEM_ADMIN
    for action_id, leads in coverage.open_action_leads.items():
        affected = removal.lead_actions is None or action_id in removal.lead_actions
        if affected and user in leads and not leads - {user}:
            return AdminInvariant.LAST_CHARITY_ADMIN
    return None
