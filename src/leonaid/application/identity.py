"""Identity queries, administration and navigation contracts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import (
    AuthenticationRequired,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)


class IdentityRepository(Protocol):
    async def principal_for_session(
        self,
        token_digest: str,
        *,
        now: datetime,
    ) -> IdentityPrincipal | None: ...

    async def transition_account_status(
        self,
        user_id: UUID,
        target: AccountStatus,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> UserAccount | None: ...

    async def grant_global_role(
        self,
        user_id: UUID,
        role: GlobalRole,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...

    async def revoke_global_role(
        self,
        user_id: UUID,
        role: GlobalRole,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...

    async def grant_action_membership(
        self,
        membership: ActionMembership,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...

    async def revoke_action_membership(
        self,
        membership_id: UUID,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class NavigationItem:
    key: str
    label: str
    href: str
    surface: str


@dataclass(frozen=True, slots=True)
class IdentityMembershipView:
    action_id: UUID
    action_name: str
    role: ActionRole
    role_label: str


@dataclass(frozen=True, slots=True)
class CurrentIdentity:
    user_id: UUID
    display_name: str
    global_roles: tuple[GlobalRole, ...]
    action_memberships: tuple[IdentityMembershipView, ...]
    role_labels: tuple[str, ...]
    navigation: tuple[NavigationItem, ...]


ROLE_LABELS: dict[GlobalRole | ActionRole, str] = {
    GlobalRole.SYSTEM_ADMIN: "System-Admin",
    GlobalRole.FINANCE_READER: "Finanzen (Lesen)",
    GlobalRole.FINANCE_MANAGER: "Finanzen",
    ActionRole.CHARITY_ADMIN: "Charity-Admin",
    ActionRole.ACQUIRER: "Akquisiteur",
    ActionRole.FINANCE_READER: "Finanzen",
    ActionRole.DRIVER: "Ausfahrer",
}


def navigation_for(principal: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    items: list[NavigationItem] = [
        NavigationItem("overview-web", "Übersicht", "/admin/", "web"),
        NavigationItem("overview-pwa", "Übersicht", "/app/", "pwa"),
    ]
    action_roles = {membership.role for membership in principal.action_memberships}
    if principal.is_system_admin:
        items.extend(
            (
                NavigationItem("actions", "Charity-Aktionen", "/admin/actions", "web"),
                NavigationItem("members", "Mitglieder", "/admin/members", "web"),
                NavigationItem("system", "System", "/admin/system", "web"),
            )
        )
    if ActionRole.CHARITY_ADMIN in action_roles:
        items.extend(
            (
                NavigationItem("actions", "Charity-Aktionen", "/admin/actions", "web"),
                NavigationItem(
                    "acquisition-web", "Akquise", "/admin/acquisition", "web"
                ),
                NavigationItem("orders", "Bestellungen", "/admin/orders", "web"),
                NavigationItem("invoices", "Rechnungen", "/admin/invoices", "web"),
                NavigationItem("members", "Mitglieder", "/admin/members", "web"),
                NavigationItem("acquisition-pwa", "Akquise", "/app/acquisition", "pwa"),
            )
        )
    if (
        GlobalRole.FINANCE_READER in principal.global_roles
        or GlobalRole.FINANCE_MANAGER in principal.global_roles
        or ActionRole.FINANCE_READER in action_roles
    ):
        items.append(NavigationItem("invoices", "Rechnungen", "/admin/invoices", "web"))
    if ActionRole.ACQUIRER in action_roles:
        items.extend(
            (
                NavigationItem(
                    "sponsors",
                    "Meine Sponsoren",
                    "/app/sponsors",
                    "pwa",
                ),
                NavigationItem(
                    "activities",
                    "Aktivitäten",
                    "/app/activities",
                    "pwa",
                ),
                NavigationItem(
                    "commitment",
                    "Bestellung erfassen",
                    "/app/commitments/new",
                    "pwa",
                ),
            )
        )
    if ActionRole.DRIVER in action_roles:
        items.append(NavigationItem("delivery", "Auslieferung", "/app/delivery", "pwa"))

    seen: set[tuple[str, str]] = set()
    unique: list[NavigationItem] = []
    for item in items:
        identity = (item.surface, item.key)
        if identity not in seen:
            seen.add(identity)
            unique.append(item)
    return tuple(unique)


class IdentityQueryService:
    def __init__(
        self,
        repository: IdentityRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def authenticate(self, session_token: str | None) -> IdentityPrincipal:
        if session_token is None or not session_token.strip():
            raise AuthenticationRequired(
                "authentication_required",
                "Bitte melde dich an, um LeonAid zu verwenden.",
            )
        digest = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        principal = await self._repository.principal_for_session(
            digest,
            now=self._clock(),
        )
        if principal is None:
            raise AuthenticationRequired(
                "session_invalid",
                "Deine Sitzung ist nicht mehr gültig. Bitte melde dich erneut an.",
            )
        return principal

    async def current_identity(self, session_token: str | None) -> CurrentIdentity:
        principal = await self.authenticate(session_token)
        memberships = tuple(
            IdentityMembershipView(
                action_id=membership.action_id,
                action_name=membership.action_name,
                role=membership.role,
                role_label=ROLE_LABELS[membership.role],
            )
            for membership in principal.action_memberships
        )
        all_roles: set[GlobalRole | ActionRole] = set(principal.global_roles)
        all_roles.update(item.role for item in principal.action_memberships)
        return CurrentIdentity(
            user_id=principal.account.id,
            display_name=principal.account.display_name,
            global_roles=tuple(sorted(principal.global_roles, key=str)),
            action_memberships=memberships,
            role_labels=tuple(ROLE_LABELS[role] for role in sorted(all_roles, key=str)),
            navigation=navigation_for(principal),
        )


class IdentityAdministrationService:
    def __init__(
        self,
        repository: IdentityRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def require_system_admin(actor: IdentityPrincipal) -> None:
        if not actor.account.can_authenticate or not actor.is_system_admin:
            raise PermissionDenied(
                "system_admin_required",
                "Diese Änderung ist ausschließlich für System-Admins erlaubt.",
            )

    async def change_status(
        self,
        actor: IdentityPrincipal,
        target_user_id: UUID,
        target: AccountStatus,
        *,
        request_id: str,
    ) -> UserAccount:
        self.require_system_admin(actor)
        changed = await self._repository.transition_account_status(
            target_user_id,
            target,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if changed is None:
            raise ResourceNotFound(
                "user_not_found",
                "Das Benutzerkonto wurde nicht gefunden.",
            )
        return changed

    async def add_global_role(
        self,
        actor: IdentityPrincipal,
        target_user_id: UUID,
        role: GlobalRole,
        *,
        request_id: str,
    ) -> bool:
        self.require_system_admin(actor)
        return await self._repository.grant_global_role(
            target_user_id,
            role,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=self._clock(),
        )

    async def remove_global_role(
        self,
        actor: IdentityPrincipal,
        target_user_id: UUID,
        role: GlobalRole,
        *,
        request_id: str,
    ) -> bool:
        self.require_system_admin(actor)
        return await self._repository.revoke_global_role(
            target_user_id,
            role,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=self._clock(),
        )

    async def add_action_membership(
        self,
        actor: IdentityPrincipal,
        membership: ActionMembership,
        *,
        request_id: str,
    ) -> bool:
        self.require_system_admin(actor)
        return await self._repository.grant_action_membership(
            membership,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=self._clock(),
        )

    async def remove_action_membership(
        self,
        actor: IdentityPrincipal,
        membership_id: UUID,
        *,
        request_id: str,
    ) -> bool:
        self.require_system_admin(actor)
        return await self._repository.revoke_action_membership(
            membership_id,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=self._clock(),
        )
