"""Stable HTTP schemas; application and domain objects stay transport-neutral."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class TransportModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            part if index == 0 else part.capitalize()
            for index, part in enumerate(value.split("_"))
        ),
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class PlatformStatusResponse(TransportModel):
    service: str = Field(examples=["leonaid-api"])
    status: Literal["live"] = Field(examples=["live"])


class PlatformInformationResponse(TransportModel):
    service: str = Field(examples=["leonaid-api"])
    release: str = Field(examples=["0.0.0"])
    api_version: str = Field(examples=["v1"])


class DependencyStatusResponse(TransportModel):
    status: Literal["ready", "not-ready"]
    details: dict[str, str | int | bool]


class ReadinessResponse(TransportModel):
    service: str = Field(examples=["leonaid-api"])
    status: Literal["ready", "not-ready"]
    checks: dict[str, DependencyStatusResponse]


class IdentityMembershipResponse(TransportModel):
    action_id: UUID
    action_name: str
    role: Literal["charity_admin", "acquirer", "finance_reader", "driver"]
    role_label: str


class NavigationItemResponse(TransportModel):
    key: str
    label: str
    href: str
    surface: Literal["web", "pwa"]


class CurrentIdentityResponse(TransportModel):
    user_id: UUID
    display_name: str
    global_roles: list[Literal["system_admin", "finance_reader", "finance_manager"]]
    action_memberships: list[IdentityMembershipResponse]
    role_labels: list[str]
    navigation: list[NavigationItemResponse]
    session_expires_at: datetime
    session_last_seen_at: datetime
    fresh_login_at: datetime
    fresh_until: datetime


ActionRoleValue = Literal[
    "charity_admin",
    "acquirer",
    "finance_reader",
    "driver",
]


def normalized_invitation_email(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized.endswith(".invalid"):
        local, separator, domain = normalized.partition("@")
        if (
            separator
            and local
            and domain.endswith(".invalid")
            and normalized.count("@") == 1
            and not any(character.isspace() for character in normalized)
            and len(normalized) <= 320
        ):
            return normalized
    try:
        return validate_email(
            normalized,
            check_deliverability=False,
        ).normalized
    except EmailNotValidError as error:
        raise ValueError("Die E-Mail-Adresse ist ungültig.") from error


class InviteableActionResponse(TransportModel):
    id: UUID
    name: str
    status: Literal["draft", "scheduled", "active"]


class InvitationRoleOptionResponse(TransportModel):
    value: ActionRoleValue
    label: str


class InvitationOptionsResponse(TransportModel):
    actions: list[InviteableActionResponse]
    roles: list[InvitationRoleOptionResponse]


class CreateInvitationRequest(TransportModel):
    action_id: UUID
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    role: ActionRoleValue

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalized_invitation_email(value)


class InvitationDispatchResponse(TransportModel):
    invitation_id: UUID
    status: Literal["queued"]


class AcceptInvitationRequest(TransportModel):
    magic_token: str | None = Field(default=None, min_length=32, max_length=256)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return normalized_invitation_email(value) if value is not None else None

    @model_validator(mode="after")
    def exactly_one_credential(self) -> AcceptInvitationRequest:
        magic = self.magic_token is not None
        code = self.email is not None and self.code is not None
        if magic == code or (self.email is None) != (self.code is None):
            raise ValueError("Magic Token oder E-Mail mit Code ist erforderlich.")
        return self


class InvitationAcceptanceResponse(TransportModel):
    status: Literal["accepted"]
    action_id: UUID
    action_name: str
    role: ActionRoleValue


class InvitationRevocationResponse(TransportModel):
    status: Literal["revoked"]


class RequestLoginRequest(TransportModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalized_invitation_email(value)


class LoginDispatchResponse(TransportModel):
    status: Literal["queued"]


class CompleteLoginRequest(TransportModel):
    magic_token: str | None = Field(default=None, min_length=32, max_length=256)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return normalized_invitation_email(value) if value is not None else None

    @model_validator(mode="after")
    def exactly_one_credential(self) -> CompleteLoginRequest:
        magic = self.magic_token is not None
        code = self.email is not None and self.code is not None
        if magic == code or (self.email is None) != (self.code is None):
            raise ValueError("Magic Token oder E-Mail mit Code ist erforderlich.")
        return self


class CompleteFreshLoginRequest(TransportModel):
    magic_token: str | None = Field(default=None, min_length=32, max_length=256)
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @model_validator(mode="after")
    def exactly_one_credential(self) -> CompleteFreshLoginRequest:
        if (self.magic_token is None) == (self.code is None):
            raise ValueError("Magic Token oder Code ist erforderlich.")
        return self


class SessionAuthenticationResponse(TransportModel):
    status: Literal["authenticated"]
    user_id: UUID
    display_name: str
    expires_at: datetime
    fresh_login_at: datetime


class FreshLoginStatusResponse(TransportModel):
    status: Literal["fresh"]
    fresh_until: datetime


class LogoutResponse(TransportModel):
    status: Literal["signed_out"]


class SessionRevocationResponse(TransportModel):
    status: Literal["revoked"]
    revoked_count: int = Field(ge=0)


ActionCapabilityValue = Literal[
    "acquisition",
    "offerings",
    "ordering",
    "invoicing",
]
CharityActionStatusValue = Literal[
    "draft",
    "scheduled",
    "active",
    "completed",
    "archived",
]


def decimal_text(value: str) -> str:
    normalized = value.strip()
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError("Der Wert muss eine Dezimalzahl sein.") from error
    if not parsed.is_finite():
        raise ValueError("Der Wert muss eine endliche Dezimalzahl sein.")
    return normalized


class ActionGoalRequest(TransportModel):
    goal_value: str | None = None
    actual_value: str = "0"
    unit: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("goal_value", "actual_value")
    @classmethod
    def validate_decimal(cls, value: str | None) -> str | None:
        return decimal_text(value) if value is not None else None


class ActionGoalResponse(TransportModel):
    goal_value: str | None
    actual_value: str
    unit: str | None
    currency: str | None


class BeneficiaryDraftRequest(TransportModel):
    organization_name: str = Field(min_length=1, max_length=200)
    public_description: str = Field(min_length=1, max_length=2_000)


class BeneficiaryResponse(TransportModel):
    id: UUID
    organization_name: str
    public_description: str
    sort_order: int = Field(ge=0)


class CreateCharityActionRequest(TransportModel):
    carrier_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2_000)
    starts_on: date
    ends_on: date
    archive_slug: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    capabilities: list[ActionCapabilityValue]
    beneficiaries: list[BeneficiaryDraftRequest] = Field(min_length=1)
    goal: ActionGoalRequest


class CharityActionResponse(TransportModel):
    id: UUID
    carrier_name: str
    name: str
    purpose: str
    status: CharityActionStatusValue
    starts_on: date
    ends_on: date
    archive_slug: str
    capabilities: list[ActionCapabilityValue]
    beneficiaries: list[BeneficiaryResponse]
    goal: ActionGoalResponse


class SetActionGoalRequest(ActionGoalRequest):
    pass


class SetActionCapabilitiesRequest(TransportModel):
    capabilities: list[ActionCapabilityValue]


class SetActionBeneficiariesRequest(TransportModel):
    beneficiaries: list[BeneficiaryDraftRequest] = Field(min_length=1)


class TransitionCharityActionRequest(TransportModel):
    target_status: CharityActionStatusValue


class QueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AcquisitionSearchQuery(QueryModel):
    q: str | None = Field(default=None, min_length=1, max_length=100)


class PaginationQuery(QueryModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class AcquisitionPageQuery(QueryModel):
    q: str | None = Field(default=None, min_length=1, max_length=100)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class AcquisitionPartyResponse(TransportModel):
    party_kind: Literal["company", "person"]
    twenty_id: UUID
    display_name: str
    postal_code: str | None
    city: str | None
    email: str | None
    assigned_acquirer_ids: list[UUID]


class AcquisitionPartyListResponse(TransportModel):
    items: list[AcquisitionPartyResponse]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class AcquisitionPartyCountResponse(TransportModel):
    total: int = Field(ge=0)


class AcquisitionPartyExportResponse(TransportModel):
    action_id: UUID
    items: list[AcquisitionPartyResponse]


class AcquisitionActivityResponse(TransportModel):
    id: UUID
    action_id: UUID
    party_kind: Literal["company", "person"]
    party_id: UUID
    actor_user_id: UUID | None
    outcome: str
    channel: str
    note: str | None
    occurred_at: datetime


class AcquisitionActivityListResponse(TransportModel):
    items: list[AcquisitionActivityResponse]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class AcquisitionDocumentResponse(TransportModel):
    id: UUID
    action_id: UUID
    party_kind: Literal["company", "person"]
    party_id: UUID
    document_type: str
    media_type: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: int = Field(ge=1)
    created_at: datetime


class ApiErrorDetail(TransportModel):
    code: str = Field(examples=["endpoint_not_found"])
    message: str = Field(
        examples=["Dieser API-Endpunkt existiert nicht."],
    )
    request_id: str = Field(
        min_length=8,
        max_length=128,
        examples=["poc023:contract:golden-v1"],
    )


class ApiErrorResponse(TransportModel):
    error: ApiErrorDetail


ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {
        "model": ApiErrorResponse,
        "description": "Endpunkt oder Fachobjekt wurde nicht gefunden.",
    },
    422: {
        "model": ApiErrorResponse,
        "description": "Transport- oder Fachvalidierung ist fehlgeschlagen.",
    },
    500: {
        "model": ApiErrorResponse,
        "description": "Unerwarteter interner Fehler.",
    },
    503: {
        "model": ApiErrorResponse,
        "description": "Eine erforderliche externe Anbindung ist nicht konfiguriert.",
    },
}

AUTHENTICATED_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {
        "model": ApiErrorResponse,
        "description": "Keine gültige serverseitige Sitzung.",
    },
    403: {
        "model": ApiErrorResponse,
        "description": "Die angemeldete Persona besitzt nicht die nötigen Rechte.",
    },
    **ERROR_RESPONSES,
}

AUTHENTICATED_CONFLICT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTHENTICATED_ERROR_RESPONSES,
    409: {
        "model": ApiErrorResponse,
        "description": "Änderung kollidiert mit dem aktuellen Zustand.",
    },
}

RequestIdHeader = Annotated[
    str | None,
    Field(
        description="Optionaler Korrelationsschlüssel; ungültige Werte werden ersetzt.",
        examples=["poc023:contract:golden-v1"],
    ),
]
