"""Administration of versioned legal and privacy configuration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.policies import require_system_admin
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.legal_configuration import (
    EVIDENCE_ID,
    LegalConfigurationDraft,
    LegalConfigurationState,
)


class LegalConfigurationRepository(Protocol):
    async def state(self) -> LegalConfigurationState: ...

    async def save_draft(
        self,
        *,
        configuration: LegalConfigurationDraft,
        actor_user_id: UUID,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime,
    ) -> LegalConfigurationState: ...

    async def approve(
        self,
        *,
        version_id: UUID,
        actor_user_id: UUID,
        evidence_id: str,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime,
    ) -> LegalConfigurationState: ...

    async def activate(
        self,
        *,
        version_id: UUID,
        actor_user_id: UUID,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime,
    ) -> LegalConfigurationState: ...


class LegalConfigurationService:
    def __init__(
        self,
        repository: LegalConfigurationRepository,
        *,
        production: bool,
    ) -> None:
        self._repository = repository
        self._production = production

    @property
    def production(self) -> bool:
        return self._production

    async def state(
        self,
        actor: IdentityPrincipal,
    ) -> LegalConfigurationState:
        require_system_admin(actor)
        return await self._repository.state()

    async def save_draft(
        self,
        actor: IdentityPrincipal,
        *,
        configuration: LegalConfigurationDraft,
        expected_revision: int,
        request_id: str,
    ) -> LegalConfigurationState:
        require_system_admin(actor)
        if expected_revision < 1:
            raise Conflict(
                "legal_configuration_revision_invalid",
                "Lade die Konfiguration neu und versuche es erneut.",
            )
        return await self._repository.save_draft(
            configuration=configuration,
            actor_user_id=actor.account.id,
            expected_revision=expected_revision,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def approve(
        self,
        actor: IdentityPrincipal,
        *,
        version_id: UUID,
        evidence_id: str,
        expected_revision: int,
        request_id: str,
    ) -> LegalConfigurationState:
        require_system_admin(actor)
        if EVIDENCE_ID.fullmatch(evidence_id) is None:
            raise Conflict(
                "legal_approval_evidence_invalid",
                "Die Evidence-ID der Vier-Augen-Freigabe ist ungültig.",
            )
        state = await self._repository.state()
        if state.draft is None or state.draft.id != version_id:
            raise ResourceNotFound(
                "legal_configuration_draft_not_found",
                "Der freizugebende Entwurf ist nicht mehr aktuell.",
            )
        if state.draft.created_by_user_id == actor.account.id:
            raise Conflict(
                "legal_configuration_four_eyes_required",
                "Der Ersteller kann den eigenen Entwurf nicht freigeben.",
            )
        return await self._repository.approve(
            version_id=version_id,
            actor_user_id=actor.account.id,
            evidence_id=evidence_id,
            expected_revision=expected_revision,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def activate(
        self,
        actor: IdentityPrincipal,
        *,
        version_id: UUID,
        expected_revision: int,
        request_id: str,
    ) -> LegalConfigurationState:
        require_system_admin(actor)
        state = await self._repository.state()
        if state.draft is None or state.draft.id != version_id:
            raise ResourceNotFound(
                "legal_configuration_draft_not_found",
                "Der zu aktivierende Entwurf ist nicht mehr aktuell.",
            )
        if state.draft_approval is None:
            raise Conflict(
                "legal_configuration_approval_required",
                "Eine zweite System-Administration muss den Entwurf freigeben.",
            )
        blockers = state.draft.configuration.activation_blockers(
            production=self._production
        )
        if blockers:
            if "e_invoice_scope_required" in blockers:
                message = (
                    "Für diesen Betrieb ist eine E-Rechnung erforderlich. "
                    "Der ERP-light-Pilot wird nicht still erweitert."
                )
            else:
                message = (
                    "Die Konfiguration ist noch nicht produktionsreif: "
                    + ", ".join(blockers)
                    + "."
                )
            raise Conflict("legal_configuration_activation_blocked", message)
        return await self._repository.activate(
            version_id=version_id,
            actor_user_id=actor.account.id,
            expected_revision=expected_revision,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )
