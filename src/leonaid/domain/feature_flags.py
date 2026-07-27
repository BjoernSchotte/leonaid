"""Provider-neutral feature-flag definitions and state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal


class FeatureFlagKey(StrEnum):
    SYSTEM_STATUS_PANEL = "admin.system_status_panel"
    PREVIEW_NOTICE = "admin.preview_notice"


class FeatureFlagSurface(StrEnum):
    WEB = "web"
    PWA = "pwa"


@dataclass(frozen=True, slots=True)
class FeatureFlagDefinition:
    key: FeatureFlagKey
    title: str
    description: str
    effect: str
    default_enabled: bool
    client_safe: bool


FEATURE_FLAG_CATALOG = (
    FeatureFlagDefinition(
        key=FeatureFlagKey.SYSTEM_STATUS_PANEL,
        title="Technischen Systemstatus anzeigen",
        description=(
            "Blendet für System-Admins einen kompakten Diagnosebereich ein. "
            "Der zugehörige Endpunkt wird zusätzlich im Backend geprüft."
        ),
        effect="Nur System-Administration; keine fachlichen Daten oder Rechte.",
        default_enabled=False,
        client_safe=True,
    ),
    FeatureFlagDefinition(
        key=FeatureFlagKey.PREVIEW_NOTICE,
        title="PoC-Preview-Hinweis anzeigen",
        description=(
            "Zeigt im internen Portal einen Hinweis auf den aktuellen "
            "Erprobungsstand der Oberfläche."
        ),
        effect="Alle angemeldeten Portal-Nutzer sehen den Hinweis.",
        default_enabled=False,
        client_safe=True,
    ),
)

FEATURE_FLAG_DEFINITIONS = {
    definition.key: definition for definition in FEATURE_FLAG_CATALOG
}


def feature_flag_definition(key: str | FeatureFlagKey) -> FeatureFlagDefinition:
    try:
        parsed = FeatureFlagKey(key)
    except ValueError as error:
        raise DomainInvariantError(
            "feature_flag_unknown",
            "Dieses Feature-Flag ist nicht im LeonAid-Katalog registriert.",
        ) from error
    return FEATURE_FLAG_DEFINITIONS[parsed]


@dataclass(frozen=True, slots=True)
class FeatureFlagState:
    id: UUID
    key: FeatureFlagKey
    enabled: bool
    revision: int
    updated_by_user_id: UUID | None
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise DomainInvariantError(
                "feature_flag_revision_invalid",
                "Die Feature-Flag-Version muss mindestens 1 sein.",
            )
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise DomainInvariantError(
                "feature_flag_time_not_aware",
                "Die Feature-Flag-Zeit muss eine Zeitzone enthalten.",
            )


@dataclass(frozen=True, slots=True)
class FeatureEvaluationContext:
    targeting_key: str
    roles: tuple[str, ...]
    surface: FeatureFlagSurface

    @classmethod
    def for_principal(
        cls,
        principal: IdentityPrincipal,
        surface: FeatureFlagSurface,
    ) -> FeatureEvaluationContext:
        roles = tuple(
            sorted(
                {
                    *(role.value for role in principal.global_roles),
                    *(
                        membership.role.value
                        for membership in principal.action_memberships
                    ),
                }
            )
        )
        return cls(
            targeting_key=str(principal.account.id),
            roles=roles,
            surface=surface,
        )


@dataclass(frozen=True, slots=True)
class FeatureFlagEvaluation:
    key: FeatureFlagKey
    enabled: bool
    variant: str
    reason: str
    provider: str
