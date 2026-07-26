"""Central role and row-level policy vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import ActionRole, IdentityPrincipal


class PolicySurface(StrEnum):
    ACTION_MANAGEMENT = "action_management"
    SYSTEM_ADMINISTRATION = "system_administration"
    DETAIL = "detail"
    LIST = "list"
    SEARCH = "search"
    COUNT = "count"
    EXPORT = "export"
    ACTIVITY = "activity"
    DOCUMENT = "document"
    WRITE = "write"


class AcquisitionAccessLevel(StrEnum):
    MANAGE = "manage"
    ASSIGNED = "assigned"


@dataclass(frozen=True, slots=True)
class AuthorizedPartyScope:
    action_id: UUID
    actor_user_id: UUID
    access_level: AcquisitionAccessLevel
    company_ids: frozenset[UUID]
    person_ids: frozenset[UUID]

    def __post_init__(self) -> None:
        if self.actor_user_id.int == 0 or self.action_id.int == 0:
            raise DomainInvariantError(
                "policy_scope_identifier_invalid",
                "Ein Berechtigungs-Scope benötigt gültige Bezeichner.",
            )

    def allows_company(self, company_id: UUID) -> bool:
        return company_id in self.company_ids

    def allows_person(self, person_id: UUID) -> bool:
        return person_id in self.person_ids


def has_action_role(
    principal: IdentityPrincipal,
    action_id: UUID,
    allowed_roles: frozenset[ActionRole],
) -> bool:
    return principal.is_system_admin or bool(
        principal.roles_for(action_id) & allowed_roles
    )


def may_manage_action(principal: IdentityPrincipal, action_id: UUID) -> bool:
    return has_action_role(
        principal,
        action_id,
        frozenset({ActionRole.CHARITY_ADMIN}),
    )
