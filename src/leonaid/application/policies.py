"""Application-level authorization guards with non-leaking failures."""

from __future__ import annotations

from uuid import UUID

from leonaid.application.errors import PermissionDenied, ResourceNotFound
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.policies import PolicySurface, may_manage_action


def require_system_admin(
    principal: IdentityPrincipal,
    surface: PolicySurface = PolicySurface.SYSTEM_ADMINISTRATION,
) -> None:
    if principal.account.can_authenticate and principal.is_system_admin:
        return
    raise PermissionDenied(
        "system_admin_required",
        f"Diese {surface.value}-Aktion ist ausschließlich für System-Admins erlaubt.",
    )


def require_action_manager(
    principal: IdentityPrincipal,
    action_id: UUID,
    surface: PolicySurface = PolicySurface.ACTION_MANAGEMENT,
    *,
    code: str = "action_management_required",
    message: str | None = None,
) -> None:
    if principal.account.can_authenticate and may_manage_action(principal, action_id):
        return
    raise PermissionDenied(
        code,
        message
        or f"Diese {surface.value}-Aktion erfordert die Verwaltung der Charity-Aktion.",
    )


def require_action_creator(principal: IdentityPrincipal) -> None:
    may_create = principal.is_system_admin or any(
        membership.role is ActionRole.CHARITY_ADMIN
        for membership in principal.action_memberships
    )
    if principal.account.can_authenticate and may_create:
        return
    raise PermissionDenied(
        "action_creation_forbidden",
        "Nur Charity- oder System-Admins dürfen Charity-Aktionen anlegen.",
    )


def concealed_resource() -> ResourceNotFound:
    return ResourceNotFound(
        "resource_not_found",
        "Der angeforderte Datensatz wurde nicht gefunden.",
    )
