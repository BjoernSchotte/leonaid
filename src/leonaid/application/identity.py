"""Identity queries, administration and navigation contracts."""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.application.policies import require_system_admin
from leonaid.domain.identity import (
    AccountStatus,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
    can_manage_action_roles,
)
from leonaid.domain.sessions import UserSession


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    principal: IdentityPrincipal
    session: UserSession


class IdentityRepository(Protocol):
    async def principal_for_session(
        self,
        token_digest: str,
        *,
        now: datetime,
    ) -> AuthenticatedIdentity | None: ...

    async def transition_account_status(
        self,
        user_id: UUID,
        target: AccountStatus,
        *,
        actor_user_id: UUID,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> AccountStatusChange | None: ...

    async def grant_global_role(
        self,
        user_id: UUID,
        role: GlobalRole,
        *,
        enabled: bool,
        actor_user_id: UUID,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> RoleAssignmentChange | None: ...

    async def grant_action_membership(
        self,
        user_id: UUID,
        action_id: UUID,
        role: ActionRole,
        *,
        enabled: bool,
        actor: IdentityPrincipal,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> RoleAssignmentChange | None: ...

    async def member_directory_snapshot(
        self,
        *,
        visible_action_ids: tuple[UUID, ...] | None,
        include_global_roles: bool,
        now: datetime,
    ) -> MemberDirectorySnapshot: ...


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
    session_expires_at: datetime
    session_last_seen_at: datetime
    fresh_login_at: datetime
    fresh_until: datetime


@dataclass(frozen=True, slots=True)
class MemberDirectoryMembership:
    action_id: UUID
    action_name: str
    role: ActionRole
    role_label: str


@dataclass(frozen=True, slots=True)
class MemberDirectoryMember:
    user_id: UUID
    display_name: str
    email: str
    status: AccountStatus
    status_label: str
    revision: int
    global_roles: tuple[GlobalRole, ...]
    global_role_labels: tuple[str, ...]
    action_memberships: tuple[MemberDirectoryMembership, ...]
    last_login_at: datetime | None
    active_session_count: int


@dataclass(frozen=True, slots=True)
class MemberDirectoryAction:
    action_id: UUID
    action_name: str
    available_roles: tuple[ActionRole, ...]


@dataclass(frozen=True, slots=True)
class MemberDirectorySnapshot:
    members: tuple[MemberDirectoryMember, ...]
    actions: tuple[MemberDirectoryAction, ...]


@dataclass(frozen=True, slots=True)
class MemberDirectoryQuery:
    search: str = ""
    status: AccountStatus | None = None
    action_id: UUID | None = None
    cursor: str | None = None
    limit: int = 6

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("Das Mitgliederlimit muss zwischen 1 und 100 liegen.")
        if len(self.search) > 160:
            raise ValueError("Die Mitgliedersuche darf höchstens 160 Zeichen haben.")


@dataclass(frozen=True, slots=True)
class MemberDirectoryPage:
    items: tuple[MemberDirectoryMember, ...]
    actions: tuple[MemberDirectoryAction, ...]
    total: int
    next_cursor: str | None
    partial: bool


@dataclass(frozen=True, slots=True)
class AccountStatusChange:
    account: UserAccount
    previous_status: AccountStatus
    revoked_session_count: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class RoleAssignmentChange:
    user_id: UUID
    revision: int
    role: GlobalRole | ActionRole
    enabled: bool
    action_id: UUID | None = None
    action_name: str | None = None
    replayed: bool = False


ROLE_LABELS: dict[GlobalRole | ActionRole, str] = {
    GlobalRole.SYSTEM_ADMIN: "System-Admin",
    GlobalRole.FINANCE_READER: "Finanzen (Lesen)",
    GlobalRole.FINANCE_MANAGER: "Finanzen",
    ActionRole.CHARITY_ADMIN: "Charity-Admin",
    ActionRole.ACQUIRER: "Akquisiteur",
    ActionRole.FINANCE_READER: "Finanzen",
    ActionRole.DRIVER: "Ausfahrer",
}

STATUS_LABELS: dict[AccountStatus, str] = {
    AccountStatus.INVITED: "Eingeladen",
    AccountStatus.ACTIVE: "Aktiv",
    AccountStatus.SUSPENDED: "Gesperrt",
    AccountStatus.ARCHIVED: "Archiviert",
}


def member_directory_sort_key(
    member: MemberDirectoryMember,
) -> tuple[str, str, str]:
    return (
        member.display_name.casefold(),
        member.email.casefold(),
        str(member.user_id),
    )


def member_matches_directory_query(
    member: MemberDirectoryMember,
    query: MemberDirectoryQuery,
) -> bool:
    search_terms = tuple(term for term in query.search.casefold().split() if term)
    searchable = f"{member.display_name} {member.email}".casefold()
    if any(term not in searchable for term in search_terms):
        return False
    if query.status is not None and member.status is not query.status:
        return False
    if query.action_id is not None and all(
        membership.action_id != query.action_id
        for membership in member.action_memberships
    ):
        return False
    return True


def encode_member_cursor(user_id: UUID) -> str:
    return base64.urlsafe_b64encode(user_id.bytes).decode("ascii").rstrip("=")


def decode_member_cursor(value: str) -> UUID:
    try:
        padded = value + ("=" * (-len(value) % 4))
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        if len(raw) != 16:
            raise ValueError
        return UUID(bytes=raw)
    except (binascii.Error, ValueError) as error:
        raise ApplicationError(
            "member_cursor_invalid",
            "Die Mitgliederseite ist nicht mehr gültig. Bitte starte die Suche neu.",
        ) from error


def paginate_member_directory(
    members: tuple[MemberDirectoryMember, ...],
    query: MemberDirectoryQuery,
) -> tuple[tuple[MemberDirectoryMember, ...], int, str | None]:
    filtered = tuple(
        sorted(
            (
                member
                for member in members
                if member_matches_directory_query(member, query)
            ),
            key=member_directory_sort_key,
        )
    )
    start = 0
    if query.cursor is not None:
        cursor_user_id = decode_member_cursor(query.cursor)
        for index, member in enumerate(filtered):
            if member.user_id == cursor_user_id:
                start = index + 1
                break
        else:
            raise ApplicationError(
                "member_cursor_invalid",
                "Die Mitgliederseite ist nicht mehr gültig. Bitte starte die Suche neu.",
            )
    page = filtered[start : start + query.limit]
    has_more = start + len(page) < len(filtered)
    next_cursor = encode_member_cursor(page[-1].user_id) if page and has_more else None
    return page, len(filtered), next_cursor


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
                NavigationItem("privacy", "Datenschutz", "/admin/privacy", "web"),
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
                NavigationItem("activities", "Neues", "/admin/activities", "web"),
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
                    "Neues",
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
        fresh_login_window: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if fresh_login_window <= timedelta(0):
            raise ValueError("Das Fresh-Login-Fenster muss positiv sein.")
        self._repository = repository
        self._fresh_login_window = fresh_login_window
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def authenticate_session(
        self,
        session_token: str | None,
    ) -> AuthenticatedIdentity:
        if session_token is None or not session_token.strip():
            raise AuthenticationRequired(
                "authentication_required",
                "Bitte melde dich an, um LeonAid zu verwenden.",
            )
        digest = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        identity = await self._repository.principal_for_session(
            digest,
            now=self._clock(),
        )
        if identity is None:
            raise AuthenticationRequired(
                "session_invalid",
                "Deine Sitzung ist nicht mehr gültig. Bitte melde dich erneut an.",
            )
        return identity

    async def authenticate(self, session_token: str | None) -> IdentityPrincipal:
        return (await self.authenticate_session(session_token)).principal

    async def authenticate_fresh(
        self,
        session_token: str | None,
    ) -> IdentityPrincipal:
        return (await self.authenticate_fresh_session(session_token)).principal

    async def authenticate_fresh_session(
        self,
        session_token: str | None,
    ) -> AuthenticatedIdentity:
        now = self._clock()
        identity = await self.authenticate_session(session_token)
        if not identity.session.fresh_at(now, self._fresh_login_window):
            raise AuthenticationRequired(
                "fresh_login_required",
                "Bitte bestätige deine Anmeldung erneut, um diese Änderung auszuführen.",
            )
        return identity

    async def fresh_until(self, session_token: str | None) -> datetime:
        identity = await self.authenticate_fresh_session(session_token)
        return identity.session.fresh_login_at + self._fresh_login_window

    async def current_identity(self, session_token: str | None) -> CurrentIdentity:
        identity = await self.authenticate_session(session_token)
        principal = identity.principal
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
            session_expires_at=identity.session.expires_at,
            session_last_seen_at=identity.session.last_seen_at,
            fresh_login_at=identity.session.fresh_login_at,
            fresh_until=identity.session.fresh_login_at + self._fresh_login_window,
        )

    @staticmethod
    def _member_scope(actor: IdentityPrincipal) -> tuple[UUID, ...] | None:
        if actor.is_system_admin:
            return None
        action_ids = tuple(
            dict.fromkeys(
                membership.action_id
                for membership in actor.action_memberships
                if membership.role is ActionRole.CHARITY_ADMIN
            )
        )
        if not action_ids:
            raise PermissionDenied(
                "member_directory_forbidden",
                "Nur Charity- oder System-Admins dürfen Mitglieder einsehen.",
            )
        return action_ids

    async def list_members(
        self,
        actor: IdentityPrincipal,
        query: MemberDirectoryQuery,
    ) -> MemberDirectoryPage:
        visible_action_ids = self._member_scope(actor)
        if (
            visible_action_ids is not None
            and query.action_id is not None
            and query.action_id not in visible_action_ids
        ):
            raise PermissionDenied(
                "member_action_scope_forbidden",
                "Du darfst Mitglieder nur in selbst verwalteten Aktionen einsehen.",
            )
        snapshot = await self._repository.member_directory_snapshot(
            visible_action_ids=visible_action_ids,
            include_global_roles=actor.is_system_admin,
            now=self._clock(),
        )
        items, total, next_cursor = paginate_member_directory(
            snapshot.members,
            query,
        )
        return MemberDirectoryPage(
            items=items,
            actions=snapshot.actions,
            total=total,
            next_cursor=next_cursor,
            partial=visible_action_ids is not None,
        )

    async def get_member(
        self,
        actor: IdentityPrincipal,
        user_id: UUID,
    ) -> MemberDirectoryMember:
        visible_action_ids = self._member_scope(actor)
        snapshot = await self._repository.member_directory_snapshot(
            visible_action_ids=visible_action_ids,
            include_global_roles=actor.is_system_admin,
            now=self._clock(),
        )
        for member in snapshot.members:
            if member.user_id == user_id:
                return member
        raise ResourceNotFound(
            "member_not_found",
            "Das Mitglied wurde nicht gefunden.",
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
        require_system_admin(actor)

    @staticmethod
    def _validate_role_command(
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> None:
        if expected_revision < 1:
            raise ApplicationError(
                "account_revision_invalid",
                "Die erwartete Kontorevision muss positiv sein.",
            )
        if not 8 <= len(idempotency_key) <= 160 or any(
            character.isspace() for character in idempotency_key
        ):
            raise ApplicationError(
                "role_assignment_idempotency_key_invalid",
                "Die Vorgangs-ID muss zwischen 8 und 160 Zeichen lang sein "
                "und darf keine Leerzeichen enthalten.",
            )

    async def change_status(
        self,
        actor: IdentityPrincipal,
        target_user_id: UUID,
        target: AccountStatus,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_id: str,
    ) -> AccountStatusChange:
        self.require_system_admin(actor)
        if actor.account.id == target_user_id and target in {
            AccountStatus.SUSPENDED,
            AccountStatus.ARCHIVED,
        }:
            raise Conflict(
                "account_self_status_change_forbidden",
                "Du kannst deinen eigenen Zugang nicht sperren oder archivieren.",
            )
        if expected_revision < 1:
            raise ApplicationError(
                "account_revision_invalid",
                "Die erwartete Kontorevision muss positiv sein.",
            )
        if not 8 <= len(idempotency_key) <= 160 or any(
            character.isspace() for character in idempotency_key
        ):
            raise ApplicationError(
                "account_status_idempotency_key_invalid",
                "Die Vorgangs-ID muss zwischen 8 und 160 Zeichen lang sein "
                "und darf keine Leerzeichen enthalten.",
            )
        request_hash = hashlib.sha256(
            (
                f"{actor.account.id}:{target_user_id}:{target.value}:"
                f"{expected_revision}"
            ).encode("utf-8")
        ).hexdigest()
        changed = await self._repository.transition_account_status(
            target_user_id,
            target,
            actor_user_id=actor.account.id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
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
        enabled: bool,
        expected_revision: int,
        idempotency_key: str,
        request_id: str,
    ) -> RoleAssignmentChange:
        self.require_system_admin(actor)
        self._validate_role_command(
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
        request_hash = hashlib.sha256(
            (
                f"{actor.account.id}:{target_user_id}:global:{role.value}:"
                f"{enabled}:{expected_revision}"
            ).encode("utf-8")
        ).hexdigest()
        result = await self._repository.grant_global_role(
            target_user_id,
            role,
            enabled=enabled,
            actor_user_id=actor.account.id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if result is None:
            raise ResourceNotFound(
                "user_not_found",
                "Das Benutzerkonto wurde nicht gefunden.",
            )
        return result

    async def add_action_membership(
        self,
        actor: IdentityPrincipal,
        target_user_id: UUID,
        action_id: UUID,
        role: ActionRole,
        *,
        enabled: bool,
        expected_revision: int,
        idempotency_key: str,
        request_id: str,
    ) -> RoleAssignmentChange:
        if not can_manage_action_roles(actor, action_id):
            raise PermissionDenied(
                "role_action_scope_forbidden",
                "Du darfst Rollen nur in selbst verwalteten Aktionen ändern.",
            )
        self._validate_role_command(
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
        request_hash = hashlib.sha256(
            (
                f"{actor.account.id}:{target_user_id}:{action_id}:{role.value}:"
                f"{enabled}:{expected_revision}"
            ).encode("utf-8")
        ).hexdigest()
        result = await self._repository.grant_action_membership(
            target_user_id,
            action_id,
            role,
            enabled=enabled,
            actor=actor,
            actor_user_id=actor.account.id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_id=request_id,
            occurred_at=self._clock(),
        )
        if result is None:
            raise ResourceNotFound(
                "user_or_action_not_found",
                "Mitglied oder Charity-Aktion wurde nicht gefunden.",
            )
        return result
