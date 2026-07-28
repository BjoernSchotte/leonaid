"""Identity, role and action-membership invariants."""

from __future__ import annotations

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


def removes_last_active_system_admin(
    *,
    role: GlobalRole,
    enabled: bool,
    active_admin_count: int,
) -> bool:
    """Protect an installation from losing its final active system admin."""

    return not enabled and role is GlobalRole.SYSTEM_ADMIN and active_admin_count <= 1


def removes_last_required_charity_admin(
    *,
    action_status: CharityActionStatus,
    role: ActionRole,
    enabled: bool,
    active_admin_count: int,
) -> bool:
    """Protect actions that can still be operated or changed."""

    return (
        not enabled
        and role is ActionRole.CHARITY_ADMIN
        and action_status
        in {
            CharityActionStatus.DRAFT,
            CharityActionStatus.SCHEDULED,
            CharityActionStatus.ACTIVE,
        }
        and active_admin_count <= 1
    )
