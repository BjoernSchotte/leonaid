"""Campaign redirect commands, independent from HTTP and CMS storage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from leonaid.application.policies import require_action_manager
from leonaid.domain.actions import PublicActionAlias
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal


@dataclass(frozen=True, slots=True)
class CampaignAliasCommand:
    command_id: UUID
    alias_id: UUID
    action_id: UUID
    target_action_id: UUID
    operation: Literal["create", "update", "remove"]
    revision: int
    alias: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.operation not in {"create", "update", "remove"}:
            raise DomainInvariantError(
                "campaign_alias_command_invalid", "Ungültiger Alias-Vorgang."
            )
        if type(self.revision) is not int or (
            (self.operation == "create" and self.revision != 0)
            or (self.operation != "create" and self.revision < 1)
        ):
            raise DomainInvariantError(
                "campaign_alias_revision_invalid", "Ungültige Alias-Version."
            )
        if type(self.enabled) is not bool:
            raise DomainInvariantError(
                "campaign_alias_command_invalid", "Ungültiger Alias-Status."
            )
        if self.operation == "remove":
            if self.alias is not None or self.target_action_id != self.action_id:
                raise DomainInvariantError(
                    "campaign_alias_command_invalid", "Ungültiger Löschvorgang."
                )
        else:
            if self.alias is None or len(self.alias) > 160:
                raise DomainInvariantError(
                    "campaign_alias_invalid", "Ungültige Alias-Adresse."
                )
            PublicActionAlias(self.alias)
        if self.operation == "create" and self.action_id != self.target_action_id:
            raise DomainInvariantError(
                "campaign_alias_command_invalid",
                "Alias muss für die gewählte Aktion angelegt werden.",
            )

    def fingerprint(self, actor_id: UUID) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "actor": str(actor_id),
                    "id": str(self.alias_id),
                    "source": str(self.action_id),
                    "target": str(self.target_action_id),
                    "operation": self.operation,
                    "revision": self.revision,
                    "alias": self.alias,
                    "enabled": self.enabled,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class CampaignAliasResult:
    alias_id: UUID
    action_id: UUID
    alias: str
    enabled: bool
    revision: int
    removed: bool


class CampaignAliasRepository(Protocol):
    async def list_for_action(
        self, actor_id: UUID, action_id: UUID
    ) -> CampaignAliasList: ...

    async def mutate(
        self, actor_id: UUID, command: CampaignAliasCommand, *, request_id: str
    ) -> CampaignAliasResult: ...


class CampaignAliasService:
    def __init__(self, repository: CampaignAliasRepository) -> None:
        self._repository = repository

    async def list_for_action(
        self, actor: IdentityPrincipal, action_id: UUID
    ) -> CampaignAliasList:
        require_action_manager(actor, action_id)
        return await self._repository.list_for_action(actor.account.id, action_id)

    async def mutate(
        self,
        actor: IdentityPrincipal,
        command: CampaignAliasCommand,
        *,
        request_id: str,
    ) -> CampaignAliasResult:
        require_action_manager(actor, command.action_id)
        require_action_manager(actor, command.target_action_id)
        # The persistence transaction repeats current account/membership checks;
        # a principal obtained before waiting for a lock is not sufficient.
        return await self._repository.mutate(
            actor.account.id, command, request_id=request_id
        )


@dataclass(frozen=True, slots=True)
class CampaignAliasItem:
    alias_id: UUID
    action_id: UUID
    alias: str
    is_primary: bool
    enabled: bool
    revision: int


@dataclass(frozen=True, slots=True)
class CampaignAliasList:
    action_id: UUID
    canonical_path: str
    items: tuple[CampaignAliasItem, ...]
