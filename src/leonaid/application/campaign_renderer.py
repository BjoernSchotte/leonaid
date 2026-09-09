"""Explicit primary renderer selection; independent from order processing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError


@dataclass(frozen=True, slots=True)
class CampaignRendererCommand:
    command_id: UUID
    alias_id: UUID
    action_id: UUID
    revision: int
    renderer: Literal["legacy", "campaign"]

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or type(self.renderer) is not str
            or self.renderer not in {"legacy", "campaign"}
        ):
            raise DomainInvariantError(
                "campaign_renderer_command_invalid", "Ungültiger Renderer-Vorgang."
            )

    def fingerprint(self, actor_id: UUID) -> str:
        payload = asdict(self)
        del payload["command_id"]
        return hashlib.sha256(
            json.dumps(
                {**payload, "actor_id": actor_id},
                default=str,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class CampaignRendererResult:
    alias_id: UUID
    action_id: UUID
    alias: str
    revision: int
    renderer: Literal["legacy", "campaign"]
