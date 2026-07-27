"""Privacy evidence, suppression and data-subject workflow orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.policies import require_system_admin
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.privacy import (
    ContactChannel,
    ConsentRecord,
    PrivacyErasureResult,
    PrivacyPurpose,
    PrivacySubjectReport,
    normalize_recipient,
)

OPEN_LEGAL_DECISIONS = (
    "Rechtsgrundlage für öffentliche Bestellungen fachlich und rechtlich bestätigen.",
    "Aufbewahrungs- und Löschfristen je Objektart verbindlich festlegen.",
    "Löschung im Twenty-CRM und Benachrichtigung von Empfängern operationalisieren.",
)


class PrivacyRepository(Protocol):
    async def subject_report(self, normalized_email: str) -> PrivacySubjectReport: ...

    async def revoke_consent(
        self,
        *,
        consent_id: UUID,
        actor_user_id: UUID,
        reason: str,
        request_id: str,
        occurred_at: datetime,
    ) -> ConsentRecord | None: ...

    async def erase_subject(
        self,
        *,
        normalized_email: str,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        open_decisions: tuple[str, ...],
    ) -> PrivacyErasureResult | None: ...

    async def suppressed_channels(
        self,
        recipients: tuple[tuple[str, ContactChannel], ...],
        *,
        purpose: PrivacyPurpose,
    ) -> frozenset[tuple[str, ContactChannel]]: ...


class PrivacyService:
    def __init__(self, repository: PrivacyRepository) -> None:
        self._repository = repository

    async def lookup(
        self,
        actor: IdentityPrincipal,
        *,
        email: str,
    ) -> PrivacySubjectReport:
        require_system_admin(actor)
        normalized = normalize_recipient(email, ContactChannel.EMAIL)
        return await self._repository.subject_report(normalized)

    async def export(
        self,
        actor: IdentityPrincipal,
        *,
        email: str,
    ) -> PrivacySubjectReport:
        require_system_admin(actor)
        normalized = normalize_recipient(email, ContactChannel.EMAIL)
        report = await self._repository.subject_report(normalized)
        if not report.found:
            raise ResourceNotFound(
                "privacy_subject_not_found",
                "Zu dieser E-Mail-Adresse wurden keine LeonAid-Daten gefunden.",
            )
        return report

    async def revoke(
        self,
        actor: IdentityPrincipal,
        *,
        consent_id: UUID,
        reason: str,
        request_id: str,
    ) -> ConsentRecord:
        require_system_admin(actor)
        normalized_reason = " ".join(reason.split())
        if not normalized_reason or len(normalized_reason) > 500:
            raise Conflict(
                "privacy_revocation_reason_invalid",
                "Gib einen kurzen, nachvollziehbaren Sperrgrund an.",
            )
        consent = await self._repository.revoke_consent(
            consent_id=consent_id,
            actor_user_id=actor.account.id,
            reason=normalized_reason,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )
        if consent is None:
            raise ResourceNotFound(
                "privacy_consent_not_found",
                "Der Nachweis wurde nicht gefunden.",
            )
        return consent

    async def erase(
        self,
        actor: IdentityPrincipal,
        *,
        email: str,
        confirmation: str,
        request_id: str,
    ) -> PrivacyErasureResult:
        require_system_admin(actor)
        normalized = normalize_recipient(email, ContactChannel.EMAIL)
        if confirmation != normalized:
            raise Conflict(
                "privacy_erasure_confirmation_mismatch",
                "Bestätige die Löschung mit der exakt eingegebenen E-Mail-Adresse.",
            )
        result = await self._repository.erase_subject(
            normalized_email=normalized,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
            open_decisions=OPEN_LEGAL_DECISIONS,
        )
        if result is None:
            raise ResourceNotFound(
                "privacy_subject_not_found",
                "Zu dieser E-Mail-Adresse wurden keine LeonAid-Daten gefunden.",
            )
        return result

    async def suppressed_channels(
        self,
        recipients: tuple[tuple[str, ContactChannel], ...],
        *,
        purpose: PrivacyPurpose = PrivacyPurpose.ACQUISITION,
    ) -> frozenset[tuple[str, ContactChannel]]:
        normalized = tuple(
            (normalize_recipient(value, channel), channel)
            for value, channel in recipients
            if value
        )
        if not normalized:
            return frozenset()
        return await self._repository.suppressed_channels(
            normalized,
            purpose=purpose,
        )
