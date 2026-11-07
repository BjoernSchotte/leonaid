"""Campaign host administration (specs/multi-domain §7).

Only the system admin adds, binds and removes hosts (decision D5). Every
command carries an idempotent command id and the host revision it was
built on; the persistence adapter repeats the system-admin check inside
the transaction, like the campaign alias commands.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import UUID

from leonaid.application.policies import require_system_admin
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.site_hosts import (
    ConfiguredHosts,
    EditionAvailability,
    HostCheckOutcome,
    SiteHostStatus,
    validate_edition_segment,
    validate_site_hostname,
)


def _revision(value: int) -> int:
    if type(value) is not int or value < 1:
        raise DomainInvariantError(
            "site_host_revision_invalid", "Ungültige Version des Hosts."
        )
    return value


@dataclass(frozen=True, slots=True)
class AddSiteHost:
    command_id: UUID
    hostname: str
    kind: Literal["add_host"] = "add_host"


@dataclass(frozen=True, slots=True)
class SetRedirectHost:
    """Make the host a redirect host (``target_host_id``) or a campaign host."""

    command_id: UUID
    host_id: UUID
    revision: int
    target_host_id: UUID | None
    kind: Literal["set_redirect"] = "set_redirect"

    def __post_init__(self) -> None:
        _revision(self.revision)
        if self.target_host_id == self.host_id:
            raise DomainInvariantError(
                "site_host_redirect_self",
                "Ein Host kann nicht auf sich selbst weiterleiten.",
            )


@dataclass(frozen=True, slots=True)
class BindEdition:
    """Bind an action as an edition; ``segment`` None takes the default."""

    command_id: UUID
    host_id: UUID
    revision: int
    action_id: UUID
    segment: str | None
    at_root: bool
    kind: Literal["bind"] = "bind"

    def __post_init__(self) -> None:
        _revision(self.revision)
        if self.segment is not None:
            object.__setattr__(self, "segment", validate_edition_segment(self.segment))
        if type(self.at_root) is not bool:
            raise DomainInvariantError(
                "site_edition_command_invalid", "Ungültige Angabe für die Wurzel."
            )


@dataclass(frozen=True, slots=True)
class ChangeEditionSegment:
    command_id: UUID
    host_id: UUID
    revision: int
    binding_id: UUID
    segment: str
    kind: Literal["change_segment"] = "change_segment"

    def __post_init__(self) -> None:
        _revision(self.revision)
        object.__setattr__(self, "segment", validate_edition_segment(self.segment))


@dataclass(frozen=True, slots=True)
class MoveRootToEdition:
    """Hand ``/`` of the host to an action (§7.7.4); binds it when needed."""

    command_id: UUID
    host_id: UUID
    revision: int
    action_id: UUID
    segment: str | None
    kind: Literal["move_root"] = "move_root"

    def __post_init__(self) -> None:
        _revision(self.revision)
        if self.segment is not None:
            object.__setattr__(self, "segment", validate_edition_segment(self.segment))


@dataclass(frozen=True, slots=True)
class SetPrimaryEdition:
    """Make this binding the canonical one of its action (§7.7.5)."""

    command_id: UUID
    host_id: UUID
    revision: int
    binding_id: UUID
    kind: Literal["set_primary"] = "set_primary"

    def __post_init__(self) -> None:
        _revision(self.revision)


@dataclass(frozen=True, slots=True)
class UnbindEdition:
    command_id: UUID
    host_id: UUID
    revision: int
    binding_id: UUID
    # The only edition of a host holds "/": unbinding it makes "/" a 404.
    confirm_root_removal: bool = False
    kind: Literal["unbind"] = "unbind"

    def __post_init__(self) -> None:
        _revision(self.revision)


@dataclass(frozen=True, slots=True)
class RemoveSiteHost:
    command_id: UUID
    host_id: UUID
    revision: int
    kind: Literal["remove_host"] = "remove_host"

    def __post_init__(self) -> None:
        _revision(self.revision)


SiteHostCommand = (
    AddSiteHost
    | SetRedirectHost
    | BindEdition
    | ChangeEditionSegment
    | MoveRootToEdition
    | SetPrimaryEdition
    | UnbindEdition
    | RemoveSiteHost
)


def command_fingerprint(command: SiteHostCommand, actor_id: UUID) -> str:
    payload = {key: str(value) for key, value in asdict(command).items()}
    payload["actor"] = str(actor_id)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SiteBindingView:
    id: UUID
    action_id: UUID
    action_name: str
    archive_slug: str
    segment: str
    at_root: bool
    is_primary: bool
    availability: EditionAvailability
    edition_url: str
    valid_from: datetime
    valid_to: datetime | None = None
    ended_reason: str | None = None
    revision: int = 1
    # Where the old path leads now (history rows only); None → 404.
    target_url: str | None = None
    # The action has a published CMS page; the campaign host renders only those.
    campaign_page: bool = True


@dataclass(frozen=True, slots=True)
class SiteHostView:
    id: UUID
    hostname: str
    display_hostname: str
    status: SiteHostStatus
    redirect_to_host_id: UUID | None
    redirect_to_hostname: str | None
    verification_token: str
    verified_at: datetime | None
    last_checked_at: datetime | None
    last_check_result: str | None
    failed_checks: int
    revision: int
    created_at: datetime
    bindings: tuple[SiteBindingView, ...] = ()
    history: tuple[SiteBindingView, ...] = ()

    @property
    def kind(self) -> Literal["campaign", "redirect"]:
        return "redirect" if self.redirect_to_host_id is not None else "campaign"


@dataclass(frozen=True, slots=True)
class BindableAction:
    id: UUID
    name: str
    archive_slug: str
    status: str
    availability: EditionAvailability
    campaign_page: bool


@dataclass(frozen=True, slots=True)
class SiteHostOverview:
    configured: ConfiguredHosts
    hosts: tuple[SiteHostView, ...]
    actions: tuple[BindableAction, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class RemovalPreviewItem:
    binding_id: UUID
    action_id: UUID
    action_name: str
    current_url: str
    # The action's canonical URL once the host is gone; None → not public.
    new_url: str | None


@dataclass(frozen=True, slots=True)
class RemovalPreview:
    host_id: UUID
    revision: int
    items: tuple[RemovalPreviewItem, ...]
    redirect_hosts: tuple[str, ...]


class SiteHostRepository(Protocol):
    async def overview(self, actor_id: UUID) -> SiteHostOverview: ...

    async def removal_preview(
        self, actor_id: UUID, host_id: UUID
    ) -> RemovalPreview: ...

    async def host(self, host_id: UUID) -> SiteHostView: ...

    async def execute(
        self,
        actor_id: UUID,
        command: SiteHostCommand,
        *,
        hostname: str | None,
        request_id: str,
    ) -> SiteHostView: ...


class SiteHostChecks(Protocol):
    """The host check of §7.4 and where its outcome is stored."""

    async def target(self, host_id: UUID) -> CheckTarget: ...

    async def due(self, now: datetime) -> list[CheckTarget]: ...

    async def record(
        self,
        target: CheckTarget,
        outcome: HostCheckOutcome,
        *,
        now: datetime,
        actor_id: UUID | None,
        request_id: str,
    ) -> object: ...

    def invalidate(self) -> None: ...


class CampaignHostUrls(Protocol):
    """Canonical URLs of actions that live on an active campaign host (§7.7.3)."""

    async def campaign_host_urls(
        self, action_ids: Iterable[UUID]
    ) -> dict[UUID, str]: ...

    async def campaign_host_url_for_slug(self, archive_slug: str) -> str | None: ...


class HostProbe(Protocol):
    async def check(
        self, hostname: str, token: str, *, tls: bool = True
    ) -> HostCheckOutcome: ...


@dataclass(frozen=True, slots=True)
class CheckTarget:
    id: UUID
    hostname: str
    token: str
    status: SiteHostStatus
    has_live_bindings: bool


class SiteHostService:
    def __init__(
        self,
        repository: SiteHostRepository,
        configured: ConfiguredHosts,
        checks: SiteHostChecks | None = None,
        probe: HostProbe | None = None,
    ) -> None:
        self._repository = repository
        self._configured = configured
        self._checks = checks
        self._probe = probe

    async def check(
        self, actor: IdentityPrincipal, host_id: UUID, *, request_id: str
    ) -> SiteHostView:
        """Prüfen (§7.4): HTTP check, then TLS; the status follows the result."""
        require_system_admin(actor)
        if self._checks is None or self._probe is None:
            raise RuntimeError("site host checks are not configured")
        target = await self._checks.target(host_id)
        await self.run_check(target, actor_id=actor.account.id, request_id=request_id)
        return await self._repository.host(host_id)

    async def run_check(
        self, target: CheckTarget, *, actor_id: UUID | None, request_id: str
    ) -> None:
        assert self._checks is not None and self._probe is not None
        outcome = await self._probe.check(target.hostname, target.token, tls=True)
        await self._checks.record(
            target,
            outcome,
            now=datetime.now(timezone.utc),
            actor_id=actor_id,
            request_id=request_id,
        )

    async def recheck_due(self, *, request_id: str) -> int:
        """The periodic re-check; returns how many hosts were checked."""
        assert self._checks is not None and self._probe is not None
        targets = await self._checks.due(datetime.now(timezone.utc))
        for target in targets:
            await self.run_check(target, actor_id=None, request_id=request_id)
        return len(targets)

    @property
    def configured(self) -> ConfiguredHosts:
        return self._configured

    async def overview(self, actor: IdentityPrincipal) -> SiteHostOverview:
        require_system_admin(actor)
        return await self._repository.overview(actor.account.id)

    async def removal_preview(
        self, actor: IdentityPrincipal, host_id: UUID
    ) -> RemovalPreview:
        require_system_admin(actor)
        return await self._repository.removal_preview(actor.account.id, host_id)

    async def execute(
        self,
        actor: IdentityPrincipal,
        command: SiteHostCommand,
        *,
        request_id: str,
    ) -> SiteHostView:
        require_system_admin(actor)
        hostname = (
            validate_site_hostname(command.hostname, self._configured)
            if isinstance(command, AddSiteHost)
            else None
        )
        try:
            return await self._repository.execute(
                actor.account.id, command, hostname=hostname, request_id=request_id
            )
        finally:
            if self._checks is not None:
                self._checks.invalidate()


__all__ = [
    "AddSiteHost",
    "CampaignHostUrls",
    "CheckTarget",
    "HostProbe",
    "SiteHostChecks",
    "BindEdition",
    "BindableAction",
    "ChangeEditionSegment",
    "MoveRootToEdition",
    "RemovalPreview",
    "RemovalPreviewItem",
    "RemoveSiteHost",
    "SetPrimaryEdition",
    "SetRedirectHost",
    "SiteBindingView",
    "SiteHostCommand",
    "SiteHostOverview",
    "SiteHostRepository",
    "SiteHostService",
    "SiteHostStatus",
    "SiteHostView",
    "UnbindEdition",
    "command_fingerprint",
]
