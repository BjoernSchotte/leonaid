"""Stable HTTP schemas; application and domain objects stay transport-neutral."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from leonaid.platform.http import (
    ApiErrorDetail as ApiErrorDetail,
    ApiErrorResponse as ApiErrorResponse,
    TransportModel as TransportModel,
)


class PlatformStatusResponse(TransportModel):
    service: str = Field(examples=["leonaid-api"])
    status: Literal["live"] = Field(examples=["live"])


class DeliveryWindowRequest(TransportModel):
    id: UUID | None = None
    delivery_on: date
    starts_at: time
    ends_at: time
    retired: bool = False
    # Accepted so a client can send a loaded window back unchanged, but
    # ignored: the switch has its own command and the stored value stays.
    # A new window (no id) with true is refused (delivery_window_full_new).
    fully_booked: bool | None = Field(
        default=None,
        description=(
            "Read-only echo, ignored for existing windows; use "
            'setDeliveryWindowFullyBooked for "ausgebucht". True on a new '
            "window is refused."
        ),
        json_schema_extra={"readOnly": True},
    )


class DeliveryWindowResponse(TransportModel):
    id: UUID
    delivery_on: date
    starts_at: time
    ends_at: time
    retired: bool
    # "Ausgebucht": closed for public orders; admin and acquisition capture
    # may still book it with allowFullWindow.
    fully_booked: bool


class DeliveryWindowFullyBookedRequest(TransportModel):
    fully_booked: bool


Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


class DeliveryStartPointRequest(TransportModel):
    """Where the drivers pick up the Krapfen (D11). Without lat/lon the
    stored point of the same address stays; a new address is looked up by
    the server later."""

    label: str = Field(min_length=1, max_length=80)
    address: str = Field(
        min_length=1,
        max_length=200,
        description='One line, best "Straße Nr, PLZ Ort" so it can be found.',
    )
    lat: Latitude | None = None
    lon: Longitude | None = None

    @model_validator(mode="after")
    def whole_point(self) -> DeliveryStartPointRequest:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon come together")
        return self


class DeliveryStartPointResponse(TransportModel):
    label: str
    address: str
    lat: float | None
    lon: float | None
    # The server will still look the address up; false with no point means
    # "not found – set the pin on the map".
    locating: bool


class DeliveryConfigurationRequest(TransportModel):
    expected_revision: int = Field(ge=1)
    enabled: bool
    timezone: str = Field(min_length=1, max_length=100)
    windows: list[DeliveryWindowRequest] = Field(max_length=1000)
    start_point: DeliveryStartPointRequest | None = Field(
        default=None,
        description="Absent: the stored start point stays. Null: no start point.",
    )


class DeliveryConfigurationResponse(TransportModel):
    action_id: UUID
    enabled: bool
    timezone: str
    revision: int
    windows: list[DeliveryWindowResponse]
    # Managers only; null in the public order form and in capture.
    start_point: DeliveryStartPointResponse | None


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


class InstallationResponse(TransportModel):
    """Installation facts every signed-in surface shows (one club per install)."""

    club_name: str


class CurrentIdentityResponse(TransportModel):
    user_id: UUID
    display_name: str
    email: str
    global_roles: list[Literal["system_admin", "finance_reader", "finance_manager"]]
    action_memberships: list[IdentityMembershipResponse]
    role_labels: list[str]
    navigation: list[NavigationItemResponse]
    session_expires_at: datetime
    session_last_seen_at: datetime
    fresh_login_at: datetime
    fresh_until: datetime
    installation: InstallationResponse
    # Start area after login and on `/` of the admin host (§6.7): a path
    # below the admin or PWA base path, computed by Core.
    landing_path: str = Field(examples=["/app/", "/admin/system"])
    preferred_surface: Literal["web", "pwa"] | None = None


class PreferredSurfaceRequest(TransportModel):
    """The start area a member chooses; null returns to the default rule."""

    surface: Literal["web", "pwa"] | None


class MemberDirectoryMembershipResponse(TransportModel):
    action_id: UUID
    action_name: str
    role: Literal["charity_admin", "acquirer", "finance_reader", "driver"]
    role_label: str


class MemberDirectoryMemberResponse(TransportModel):
    user_id: UUID
    display_name: str
    email: str
    status: Literal["invited", "active", "suspended", "archived"]
    status_label: str
    revision: int = Field(ge=1)
    global_roles: list[Literal["system_admin", "finance_reader", "finance_manager"]]
    global_role_labels: list[str]
    action_memberships: list[MemberDirectoryMembershipResponse]
    last_login_at: datetime | None
    active_session_count: int = Field(ge=0)


class ChangeMemberStatusRequest(TransportModel):
    status: Literal["active", "suspended", "archived"]
    expected_revision: int = Field(ge=1)


class MemberStatusChangeResponse(TransportModel):
    user_id: UUID
    display_name: str
    status: Literal["active", "suspended", "archived"]
    status_label: str
    previous_status: Literal["active", "suspended"]
    previous_status_label: str
    revision: int = Field(ge=2)
    revoked_session_count: int = Field(ge=0)
    replayed: bool


class ChangeMemberRoleRequest(TransportModel):
    enabled: bool
    expected_revision: int = Field(ge=1)


class MemberRoleChangeResponse(TransportModel):
    user_id: UUID
    revision: int = Field(ge=2)
    scope: Literal["global", "action"]
    role: Literal[
        "system_admin",
        "finance_reader",
        "finance_manager",
        "charity_admin",
        "acquirer",
        "driver",
    ]
    role_label: str
    enabled: bool
    action_id: UUID | None
    action_name: str | None
    replayed: bool


class MemberDirectoryActionResponse(TransportModel):
    action_id: UUID
    action_name: str
    available_roles: list[
        Literal["charity_admin", "acquirer", "finance_reader", "driver"]
    ]
    lead_required: bool = Field(
        description=(
            "Revoking the last charity admin of this action is refused "
            "(draft, scheduled and active actions)."
        )
    )


class MemberDirectoryResponse(TransportModel):
    items: list[MemberDirectoryMemberResponse]
    actions: list[MemberDirectoryActionResponse]
    total: int = Field(ge=0)
    next_cursor: str | None
    partial: bool


class SearchResultResponse(TransportModel):
    id: UUID
    type: Literal["action", "order", "invoice", "sponsor", "member"]
    title: str
    context: str
    href: str = Field(examples=["/admin/actions/00000000-0000-4000-8000-000000000001"])


class SearchResponse(TransportModel):
    results: list[SearchResultResponse]


FeatureFlagKeyValue = Literal[
    "admin.system_status_panel",
    "admin.preview_notice",
    "pwa.offline_queue",
    "delivery.tours",
]


class FeatureFlagEvaluationResponse(TransportModel):
    key: FeatureFlagKeyValue
    enabled: bool
    variant: str
    reason: str
    provider: str


class FeatureFlagEvaluationListResponse(TransportModel):
    surface: Literal["web", "pwa"]
    flags: list[FeatureFlagEvaluationResponse]


class FeatureFlagAdminResponse(TransportModel):
    key: FeatureFlagKeyValue
    title: str
    description: str
    effect: str
    enabled: bool
    default_enabled: bool
    client_safe: bool
    revision: int
    updated_by_user_id: UUID | None
    updated_at: datetime


class FeatureFlagAdminListResponse(TransportModel):
    flags: list[FeatureFlagAdminResponse]


class UpdateFeatureFlagRequest(TransportModel):
    enabled: bool
    expected_revision: int = Field(ge=1)


class FeatureFlagSystemStatusResponse(TransportModel):
    status: Literal["operational"]
    evaluated_by: Literal["openfeature"]
    provider: str
    checked_at: datetime


class PrivacySubjectRequest(TransportModel):
    email: str = Field(min_length=3, max_length=320)


class PrivacyConsentResponse(TransportModel):
    id: UUID
    action_id: UUID | None
    commitment_id: UUID | None
    purpose: Literal["public_order_fulfilment", "acquisition", "marketing"]
    channel: Literal["email", "phone", "postal"]
    text_version: str
    source: str
    evidence_kind: Literal["notice_acknowledgement", "explicit_consent"]
    legal_basis_status: Literal["legal_review_pending", "confirmed"]
    granted_at: datetime
    revoked_at: datetime | None


class PrivacySuppressionResponse(TransportModel):
    id: UUID
    channel: Literal["email", "phone", "postal"]
    purpose: Literal["public_order_fulfilment", "acquisition", "marketing"]
    reason: str
    suppressed_at: datetime


class PrivacyReferenceResponse(TransportModel):
    id: UUID
    reference_type: Literal[
        "commitment",
        "invoice",
        "document",
        "assignment",
        "activity",
        "inbox_case",
    ]
    action_id: UUID | None
    status: str | None
    label: str


class PrivacyRetentionResponse(TransportModel):
    legal_configuration_version_id: UUID
    legal_configuration_version: int
    invoice_days: int
    commitment_days: int
    contact_days: int
    consent_evidence_days: int
    audit_days: int


class GeoPointResponse(TransportModel):
    lat: float
    lon: float


class PrivacyOrderDeliveryResponse(TransportModel):
    commitment_id: UUID
    action_id: UUID
    delivery_window_id: UUID | None
    delivery_window_snapshot: dict[str, str] | None
    delivery_contact: DeliveryContactRequest | None
    # Geocoded or pinned coordinates of the delivery address.
    coordinates: GeoPointResponse | None


class PrivacySubjectReportResponse(TransportModel):
    found: bool
    subject_email: str
    crm_deletion_status: Literal["pending_manual_review"]
    retention: PrivacyRetentionResponse
    consents: list[PrivacyConsentResponse]
    suppressions: list[PrivacySuppressionResponse]
    references: list[PrivacyReferenceResponse]
    order_deliveries: list[PrivacyOrderDeliveryResponse]
    open_legal_decisions: list[str]
    generated_at: datetime


class RevokePrivacyConsentRequest(TransportModel):
    reason: str = Field(min_length=3, max_length=500)


class PrivacyErasureRequest(TransportModel):
    email: str = Field(min_length=3, max_length=320)
    confirmation: str = Field(min_length=3, max_length=320)


class PrivacyErasureResponse(TransportModel):
    case_id: UUID
    subject_hash: str
    status: Literal["completed_with_retention"]
    retention: PrivacyRetentionResponse
    anonymized_commitments: int
    cleared_activity_notes: int
    cleared_reminders: int
    revoked_consents: int
    retained_invoice_ids: list[UUID]
    retained_document_ids: list[UUID]
    retention_reasons: list[str]
    open_decisions: list[str]
    completed_at: datetime


# Carrier's legal form; decides the register § 5 Abs. 1 Nr. 4 DDG requires.
LegalFormValue = Literal[
    "registered_association",
    "unregistered_association",
    "ggmbh",
    "gmbh",
    "cooperative",
    "foundation",
    "other",
]


class LegalIssuerRequest(TransportModel):
    legal_name: str = Field(min_length=2, max_length=200)
    street_line_1: str = Field(min_length=2, max_length=200)
    postal_code: str = Field(min_length=2, max_length=20)
    city: str = Field(min_length=2, max_length=120)
    country_code: str = Field(default="DE", pattern=r"^[A-Z]{2}$")
    tax_identifier: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=320)


class LegalRetentionRequest(TransportModel):
    invoice_days: int = Field(ge=1, le=36_500)
    commitment_days: int = Field(ge=1, le=36_500)
    contact_days: int = Field(ge=1, le=36_500)
    consent_evidence_days: int = Field(ge=1, le=36_500)
    audit_days: int = Field(ge=1, le=36_500)


class SaveLegalConfigurationDraftRequest(TransportModel):
    expected_revision: int = Field(ge=1)
    issuer: LegalIssuerRequest
    bank_account_holder: str = Field(min_length=2, max_length=200)
    iban: str = Field(min_length=15, max_length=40)
    bic: str | None = Field(default=None, min_length=8, max_length=11)
    tax_treatment: Literal["standard_vat", "small_business", "tax_exempt"]
    tax_rate_basis_points: int = Field(ge=0, le=10_000)
    tax_note: str = Field(min_length=8, max_length=1_000)
    number_prefix: str = Field(min_length=1, max_length=24)
    number_width: int = Field(ge=3, le=8)
    payment_terms_days: int = Field(ge=1, le=120)
    public_order_legal_basis: str = Field(min_length=12, max_length=2_000)
    public_order_notice_text: str = Field(min_length=40, max_length=10_000)
    consent_text_version: str = Field(min_length=3, max_length=64)
    privacy_contact_email: str = Field(min_length=3, max_length=320)
    retention: LegalRetentionRequest
    e_invoice_decision: Literal["pending", "not_required", "required"]
    tax_evidence_id: str = Field(min_length=3, max_length=120)
    privacy_evidence_id: str = Field(min_length=3, max_length=120)
    e_invoice_evidence_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=120,
    )
    legal_form: LegalFormValue | None = None
    # Impressum (§ 5 DDG). Optional in the contract; production activation
    # lists the missing mandatory ones as activation blockers.
    imprint_representatives: str | None = Field(default=None, max_length=1_000)
    imprint_phone: str | None = Field(default=None, max_length=40)
    imprint_register_court: str | None = Field(default=None, max_length=200)
    imprint_register_number: str | None = Field(default=None, max_length=60)
    imprint_vat_id: str | None = Field(default=None, max_length=20)
    imprint_content_responsible_name: str | None = Field(default=None, max_length=200)
    imprint_content_responsible_address: str | None = Field(
        default=None, max_length=400
    )
    privacy_policy_text: str | None = Field(default=None, max_length=60_000)
    member_privacy_notice_text: str | None = Field(default=None, max_length=30_000)


class ApproveLegalConfigurationRequest(TransportModel):
    evidence_id: str = Field(min_length=3, max_length=120)
    expected_revision: int = Field(ge=1)


class ActivateLegalConfigurationRequest(TransportModel):
    expected_revision: int = Field(ge=1)


class LegalIssuerResponse(TransportModel):
    legal_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    tax_identifier: str
    email: str


class LegalRetentionResponse(TransportModel):
    invoice_days: int
    commitment_days: int
    contact_days: int
    consent_evidence_days: int
    audit_days: int


class LegalConfigurationValuesResponse(TransportModel):
    issuer: LegalIssuerResponse
    bank_account_holder: str
    iban: str
    bic: str | None
    tax_treatment: Literal["standard_vat", "small_business", "tax_exempt"]
    tax_rate_basis_points: int
    tax_note: str
    number_prefix: str
    number_width: int
    payment_terms_days: int
    public_order_legal_basis: str
    public_order_notice_text: str
    consent_text_version: str
    privacy_contact_email: str
    retention: LegalRetentionResponse
    e_invoice_decision: Literal["pending", "not_required", "required"]
    tax_evidence_id: str
    privacy_evidence_id: str
    e_invoice_evidence_id: str | None
    activation_blockers: list[str]
    legal_form: LegalFormValue | None = None
    imprint_representatives: str | None = None
    imprint_phone: str | None = None
    imprint_register_court: str | None = None
    imprint_register_number: str | None = None
    imprint_vat_id: str | None = None
    imprint_content_responsible_name: str | None = None
    imprint_content_responsible_address: str | None = None
    privacy_policy_text: str | None = None
    member_privacy_notice_text: str | None = None


class LegalConfigurationVersionResponse(TransportModel):
    id: UUID
    version: int
    values: LegalConfigurationValuesResponse
    created_by_user_id: UUID
    created_by_display_name: str
    created_at: datetime


class LegalConfigurationApprovalResponse(TransportModel):
    approved_by_user_id: UUID
    approved_by_display_name: str
    evidence_id: str
    approved_at: datetime


class LegalConfigurationStateResponse(TransportModel):
    revision: int
    production: bool
    draft: LegalConfigurationVersionResponse | None
    active: LegalConfigurationVersionResponse | None
    draft_approval: LegalConfigurationApprovalResponse | None


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


InvitationStatusValue = Literal["pending", "accepted", "expired", "revoked"]


class InvitationSummaryResponse(TransportModel):
    id: UUID
    action_id: UUID
    action_name: str
    email: str
    display_name: str
    role: ActionRoleValue
    status: InvitationStatusValue
    invited_by_name: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    expired_at: datetime | None
    supersedes_invitation_id: UUID | None


class InvitationListResponse(TransportModel):
    items: list[InvitationSummaryResponse]


class CorrectInvitationAddressRequest(TransportModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalized_invitation_email(value)


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


class CreateEmailChangeRequest(TransportModel):
    new_email: str = Field(min_length=3, max_length=320)

    @field_validator("new_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalized_invitation_email(value)


class EmailChangeDispatchResponse(TransportModel):
    change_id: UUID
    status: Literal["pending"]


class ConfirmEmailChangeRequest(TransportModel):
    magic_token: str | None = Field(default=None, min_length=32, max_length=256)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return normalized_invitation_email(value) if value is not None else None

    @model_validator(mode="after")
    def exactly_one_credential(self) -> ConfirmEmailChangeRequest:
        magic = self.magic_token is not None
        code = self.email is not None and self.code is not None
        if magic == code or (self.email is None) != (self.code is None):
            raise ValueError("Magic Token oder E-Mail mit Code ist erforderlich.")
        return self


class EmailChangeConfirmationResponse(TransportModel):
    status: Literal["confirmed"]
    revoked_session_count: int = Field(ge=0)


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
    "delivery",
]
CharityActionStatusValue = Literal[
    "draft",
    "scheduled",
    "active",
    "completed",
    "archived",
]
# Template keys are open data (any published template), validated as slugs.
ActionTemplateKeyValue = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
PresentationThemeValue = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
BOX_FIELD_DEPRECATION = (
    "Boxes are one offering unit among others; use quantities instead."
)
OfferingStatusValue = Literal["draft", "active", "inactive"]
OfferingUnitValue = Literal["box", "piece", "package", "sponsoring"]


class UnitQuantityResponse(TransportModel):
    unit: OfferingUnitValue
    quantity: int = Field(gt=0)


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


class CharityActionSummaryResponse(TransportModel):
    """One managed action in the "Aktionen verwalten" list."""

    id: UUID
    name: str
    status: Literal["draft", "scheduled", "active", "completed", "archived"]
    starts_on: date
    ends_on: date
    template_name: str | None
    lead_names: list[str]
    goal: ActionGoalResponse


class CharityActionListResponse(TransportModel):
    items: list[CharityActionSummaryResponse]


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
    is_published: bool
    id: UUID
    carrier_name: str
    name: str
    purpose: str
    status: CharityActionStatusValue
    starts_on: date
    ends_on: date
    publication_starts_at: datetime | None
    publication_ends_at: datetime | None
    archive_slug: str
    revision: int = Field(ge=1)
    capabilities: list[ActionCapabilityValue]
    beneficiaries: list[BeneficiaryResponse]
    goal: ActionGoalResponse
    presentation_theme: PresentationThemeValue | None


class PublicOfferingResponse(TransportModel):
    id: UUID
    code: str
    name: str
    unit: Literal["box", "piece", "package", "sponsoring"]
    pieces_per_unit: int | None
    unit_price_minor: int = Field(ge=0)
    currency: str


class PublicOrderFormResponse(TransportModel):
    delivery_configuration: DeliveryConfigurationResponse | None = None
    form_key: str
    title: str
    introduction: str
    submit_label: str
    require_company_name: bool
    require_contact_name: bool
    require_email: bool
    require_phone: bool
    require_delivery_address: bool
    require_billing_address: bool
    allow_message: bool
    access_token: str
    privacy_notice_version: str
    privacy_notice_text: str
    legal_basis: str
    privacy_contact_email: str


class PublicCharityActionResponse(TransportModel):
    id: UUID
    carrier_name: str
    name: str
    purpose: str
    starts_on: date
    ends_on: date
    archive_slug: str
    beneficiaries: list[BeneficiaryResponse]
    goal: ActionGoalResponse
    offerings: list[PublicOfferingResponse]
    order_form: PublicOrderFormResponse | None
    capabilities: list[ActionCapabilityValue]
    presentation_theme: PresentationThemeValue | None


class PublicActionRouteResponse(TransportModel):
    route_kind: Literal["alias", "archive"]
    route_value: str
    route_path: str
    canonical_path: str
    availability: Literal["published", "inactive", "archive"]
    submissions_allowed: bool
    action: PublicCharityActionResponse | None
    redirect_path: str | None = None
    # The action's canonical URL when it lives on a campaign host
    # (specs/multi-domain §7.7.3); its pages on the public host redirect there.
    campaign_host_url: str | None = None


class PublicLegalProviderResponse(TransportModel):
    """The carrier named in the Impressum (the active legal configuration).

    The optional fields are null when the active version has none: register
    and VAT ID only apply to some carriers, and versions before the
    Impressum fields existed have none of them.
    """

    legal_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    email: str
    phone: str | None = None
    representatives: str | None = None
    register_court: str | None = None
    register_number: str | None = None
    # "Vereinsregister", "Handelsregister", … from the number or legal form.
    register_label: str | None = None
    vat_id: str | None = None
    content_responsible_name: str | None = None
    content_responsible_address: str | None = None


class PublicLegalNoticeResponse(TransportModel):
    """Impressum data of the installation; provider is null until activated."""

    provider: PublicLegalProviderResponse | None


class PublicCampaignListItemResponse(TransportModel):
    """An active campaign for the public home page (no internal ids)."""

    archive_slug: str
    name: str
    purpose: str
    carrier_name: str
    presentation_theme: str | None
    starts_on: date
    ends_on: date
    # Path of the campaign's page on the public host, and the same page as an
    # absolute URL (stage 2: possibly on a campaign host).
    canonical_path: str
    canonical_url: str


class PublicCampaignListResponse(TransportModel):
    items: list[PublicCampaignListItemResponse]


class PublicPrivacyPolicyContentResponse(TransportModel):
    """The privacy page of the active legal configuration version."""

    version: int
    controller: PublicLegalProviderResponse
    privacy_contact_email: str
    policy_text: str | None
    member_notice_text: str | None
    order_notice_text: str
    order_legal_basis: str


class PublicPrivacyPolicyResponse(TransportModel):
    """Privacy page of the installation; policy is null until activated."""

    policy: PublicPrivacyPolicyContentResponse | None


class PublicCampaignRouteResponse(TransportModel):
    route_kind: Literal["campaign"] = "campaign"
    route_value: str
    route_path: str
    canonical_path: str
    availability: Literal["published", "inactive", "archive"]
    submissions_allowed: bool
    action: PublicCharityActionResponse | None
    order_alias: str | None
    # The canonical URL on a campaign host, if the action has one (§7.7.3).
    campaign_host_url: str | None = None


class PublicOrderPartyRequest(TransportModel):
    company_name: str | None = Field(default=None, max_length=300)
    given_name: str = Field(min_length=1, max_length=200)
    family_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    phone: str | None = Field(default=None, max_length=40)


class PublicOrderDeliveryRecipientRequest(TransportModel):
    recipient_name: str = Field(min_length=1, max_length=200)
    street_line_1: str = Field(min_length=1, max_length=200)
    postal_code: str = Field(min_length=1, max_length=20)
    city: str = Field(min_length=1, max_length=120)
    country_code: str = Field(default="DE", pattern=r"^[A-Z]{2}$")


class PublicOrderInvoiceRecipientRequest(PublicOrderDeliveryRecipientRequest):
    email: str = Field(min_length=3, max_length=320)


class PublicOrderLineRequest(TransportModel):
    offering_id: UUID
    quantity: int = Field(ge=1, le=1_000_000)
    unit: OfferingUnitValue
    quoted_unit_price_minor: int = Field(ge=0)


class DeliveryContactRequest(TransportModel):
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    driver_note: str | None = Field(default=None, max_length=200)


class CreatePublicOrderRequest(TransportModel):
    access_token: str = Field(min_length=40, max_length=2_000)
    command_id: UUID
    delivery_window_id: UUID | None = None
    delivery_contact: DeliveryContactRequest | None = None
    party: PublicOrderPartyRequest
    # Required only when the action has the delivery capability.
    delivery_recipient: PublicOrderDeliveryRecipientRequest | None = None
    invoice_recipient: PublicOrderInvoiceRecipientRequest
    lines: list[PublicOrderLineRequest] = Field(min_length=1, max_length=100)
    message: str | None = Field(default=None, max_length=1_000)
    privacy_acknowledged: bool
    binding_order_confirmed: bool
    privacy_notice_version: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$",
    )
    website: str | None = Field(default=None, max_length=300)


class PublicOrderQuantityResponse(TransportModel):
    unit: Literal["box", "piece", "package", "sponsoring"]
    quantity: int = Field(gt=0)
    pieces_per_unit: int | None = Field(gt=0)


class PublicOrderResultResponse(TransportModel):
    commitment_id: UUID
    public_reference: str
    status: Literal["review_ready"]
    total_minor: int = Field(ge=0)
    currency: str
    total_boxes: int = Field(ge=0, deprecated=BOX_FIELD_DEPRECATION)
    total_pieces: int = Field(ge=0)
    quantities: list[PublicOrderQuantityResponse] = Field(min_length=1)
    crm_outcome: Literal["created", "reused"]
    replayed: bool


class ActionTemplateSummaryResponse(TransportModel):
    key: ActionTemplateKeyValue
    version: int = Field(ge=1)
    display_name: str
    description: str
    capabilities: list[ActionCapabilityValue]
    offering_count: int = Field(ge=0)
    has_order_form: bool
    presentation_theme: PresentationThemeValue | None


class ActionTemplateListResponse(TransportModel):
    items: list[ActionTemplateSummaryResponse]


class CreateActionFromTemplateRequest(TransportModel):
    template_key: ActionTemplateKeyValue
    template_version: int | None = Field(default=None, ge=1)
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
    beneficiaries: list[BeneficiaryDraftRequest] = Field(min_length=1)
    goal: ActionGoalRequest


class CopyCharityActionRequest(TransportModel):
    name: str = Field(min_length=1, max_length=200)
    starts_on: date
    ends_on: date
    archive_slug: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )


class ActionTemplateSnapshotResponse(TransportModel):
    key: ActionTemplateKeyValue
    version: int = Field(ge=1)
    display_name: str
    copied_from_action_id: UUID | None


class ConfiguredOfferingResponse(TransportModel):
    id: UUID
    code: str
    name: str
    status: OfferingStatusValue
    unit: OfferingUnitValue
    allowed_quantity_units: list[OfferingUnitValue]
    pieces_per_unit: int | None
    unit_price_minor: int = Field(ge=0)
    currency: str
    available_from: datetime | None
    available_until: datetime | None


class OrderFormConfigurationResponse(TransportModel):
    id: UUID
    form_key: str
    title: str
    introduction: str
    submit_label: str
    require_company_name: bool
    require_contact_name: bool
    require_email: bool
    require_phone: bool
    require_delivery_address: bool
    require_billing_address: bool
    allow_message: bool


class CharityActionConfigurationResponse(TransportModel):
    action: CharityActionResponse
    template: ActionTemplateSnapshotResponse
    offerings: list[ConfiguredOfferingResponse]
    order_form: OrderFormConfigurationResponse | None


class CommitmentBuyerRequest(TransportModel):
    party_kind: Literal["company", "person"]
    twenty_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return normalized_invitation_email(value) if value is not None else None


class CommitmentInvoiceRecipientRequest(TransportModel):
    recipient_name: str = Field(min_length=1, max_length=200)
    street_line_1: str = Field(min_length=1, max_length=200)
    postal_code: str = Field(min_length=1, max_length=20)
    city: str = Field(min_length=1, max_length=120)
    country_code: str = Field(default="DE", pattern=r"^[A-Z]{2}$")
    email: str | None = Field(default=None, min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return normalized_invitation_email(value) if value is not None else None


class CommitmentLineRequest(TransportModel):
    offering_id: UUID
    quantity: int = Field(ge=1, le=1_000_000)
    unit: OfferingUnitValue
    quoted_unit_price_minor: int | None = Field(default=None, ge=0)


class CreateCommitmentRequest(TransportModel):
    source: Literal["acquisition", "admin"]
    ready_for_review: bool = False
    captured_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the capture was saved on the device (ISO 8601 with offset), "
            "sent by the PWA offline queue; acquisition source only. With it, every line needs `quotedUnitPriceMinor` and a price that differs from the server price is refused with 409 `commitment_price_changed` (details: new unit prices and total). At most 14 days before and 5 "
            "minutes after the server time, otherwise 422 "
            "`captured_at_out_of_range`. Rights, prices, windows and "
            "suppression are still checked at send time."
        ),
    )
    # Confirms booking a window marked "ausgebucht" (otherwise 409).
    allow_full_window: bool = False
    delivery_recipient: PublicOrderDeliveryRecipientRequest | None = None
    delivery_window_id: UUID | None = None
    delivery_contact: DeliveryContactRequest | None = None
    buyer: CommitmentBuyerRequest
    invoice_recipient: CommitmentInvoiceRecipientRequest | None = None
    lines: list[CommitmentLineRequest] = Field(min_length=1, max_length=100)


class CompleteCommitmentRequest(TransportModel):
    allow_full_window: bool = False
    captured_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the capture was saved on the device (ISO 8601 with offset), "
            "sent by the PWA offline queue. At most 14 days before and 5 "
            "minutes after the server time, otherwise 422 "
            "`captured_at_out_of_range`. Rights, prices, windows and "
            "suppression are still checked at send time."
        ),
    )
    delivery_recipient: PublicOrderDeliveryRecipientRequest | None = None
    delivery_window_id: UUID | None = None
    delivery_contact: DeliveryContactRequest | None = None


class CompleteCommitmentDeliveryRequest(TransportModel):
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    allow_full_window: bool = False
    invoice_recipient: CommitmentInvoiceRecipientRequest
    delivery_recipient: PublicOrderDeliveryRecipientRequest | None = None
    delivery_window_id: UUID | None = None
    delivery_contact: DeliveryContactRequest | None = None


class CommitmentBuyerResponse(TransportModel):
    party_kind: Literal["company", "person"]
    twenty_id: UUID
    display_name: str
    email: str | None


class CommitmentInvoiceRecipientResponse(TransportModel):
    recipient_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    email: str | None


class CommitmentLineResponse(TransportModel):
    id: UUID
    offering_id: UUID
    description: str
    quantity: int = Field(ge=1)
    unit: OfferingUnitValue
    pieces_per_unit: int | None
    piece_count: int = Field(ge=0)
    box_count: int = Field(ge=0, deprecated=BOX_FIELD_DEPRECATION)
    unit_price_minor: int = Field(ge=0)
    line_total_minor: int = Field(ge=0)
    currency: str


class CommitmentResponse(TransportModel):
    id: UUID
    action_id: UUID
    source: Literal["acquisition", "public_form", "admin"]
    status: Literal[
        "draft",
        "review_ready",
        "confirmed",
        "invoiced",
        "cancelled",
    ]
    delivery_recipient: PublicOrderDeliveryRecipientRequest | None = None
    delivery_window_id: UUID | None = None
    delivery_window_snapshot: dict[str, str] | None = None
    delivery_contact: DeliveryContactRequest | None = None
    public_reference: str = Field(
        description=(
            "The order number the buyer can quote (`LA-…`). Every order has "
            "one, whatever its source."
        )
    )
    buyer: CommitmentBuyerResponse
    invoice_recipient: CommitmentInvoiceRecipientResponse | None
    lines: list[CommitmentLineResponse]
    total_minor: int = Field(ge=0)
    currency: str
    total_pieces: int = Field(ge=0)
    total_boxes: int = Field(ge=0, deprecated=BOX_FIELD_DEPRECATION)
    quantities: list[UnitQuantityResponse]
    replayed: bool
    captured_at: datetime | None = Field(
        default=None,
        description=(
            "When an acquirer saved the order on the device, if it was sent "
            "from the PWA queue. `createdAt` of the order list stays the "
            "server time and drives lists, weekly values and invoices."
        ),
    )
    delivery_completion_version: str = Field(
        description=(
            "Optimistic version of status, delivery and billing details. "
            "Send it back unchanged when completing delivery details or "
            "cancelling the order."
        )
    )


class CommitmentCaptureContextResponse(TransportModel):
    delivery_configuration: DeliveryConfigurationResponse | None = None
    action_id: UUID
    action_name: str
    offerings: list[ConfiguredOfferingResponse]
    internal_order_mails: bool = Field(
        default=False,
        description=(
            "The action sends the order confirmation and the cancellation "
            "notice to the buyer of an order recorded here. The capture form "
            "shows the address they go to."
        ),
    )
    delivery_day_mail: bool = Field(
        default=False,
        description="The action sends the buyer a mail on the delivery day.",
    )


class CommitmentInvoiceSummaryResponse(TransportModel):
    id: UUID
    number: str
    status: Literal["issued", "sent", "paid", "cancelled"]
    payment_recorded: bool = Field(
        description="An active payment entry is booked; it blocks the order cancellation."
    )
    paid_minor: int = Field(
        default=0,
        ge=0,
        description="Sum of the active (not reversed) payment entries.",
    )


class CommitmentCancellationResponse(TransportModel):
    id: UUID
    previous_status: Literal["draft", "review_ready", "confirmed", "invoiced"]
    reason: str
    note: str | None = None
    requested_by_display_name: str | None = None
    requested_at: datetime
    invoice_cancellation_id: UUID | None = Field(
        default=None,
        description="The invoice cancellation (ADR-0009) this order cancellation caused.",
    )
    invoice_number: str | None = None


class CommitmentRecordResponse(TransportModel):
    commitment: CommitmentResponse
    created_at: datetime
    captured_by_display_name: str | None
    cancellation: CommitmentCancellationResponse | None = None
    invoice: CommitmentInvoiceSummaryResponse | None = None
    delivered: bool = Field(
        default=False,
        description="Marked delivered on the delivery board; blocks cancellation.",
    )
    buyer_mail_due: bool = Field(
        description=(
            "Cancelling this order now sends the buyer a cancellation notice: "
            "the buyer has an e-mail address and the order came through the "
            "public form or the action sends mails for orders that members "
            "enter. False for a cancelled order."
        )
    )


class CancelCommitmentRequest(TransportModel):
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=8, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


class CommitmentCancellationResultResponse(TransportModel):
    commitment: CommitmentResponse
    cancellation: CommitmentCancellationResponse
    replayed: bool


# "delivery_day" is the mail on the delivery day (stage 2 of the buyer mails,
# specs/mails-documents-donations-push §6.3). Until that stage ships, the
# list never returns it and a resend of it answers 409.
BuyerMailKindValue = Literal["confirmation", "cancellation", "delivery_day"]


class BuyerMailConfigurationRequest(TransportModel):
    expected_revision: int = Field(ge=1)
    internal_order_mails: bool = Field(
        description=(
            "Confirmation and cancellation notice for orders that members "
            "and acquirers enter."
        )
    )
    delivery_day_mail: bool = Field(
        description="The mail on the delivery day; needs the `delivery` capability."
    )
    delivery_day_send_time: str = Field(
        pattern=r"^\d{2}:\d{2}$",
        description="Local time of the action, `HH:MM`, from 05:00 to 12:00.",
        examples=["07:00"],
    )


class BuyerMailConfigurationResponse(TransportModel):
    action_id: UUID
    internal_order_mails: bool
    delivery_day_mail: bool
    delivery_day_send_time: str = Field(pattern=r"^\d{2}:\d{2}$", examples=["07:00"])
    revision: int = Field(ge=1)


BuyerMailReasonValue = Literal[
    "no_email",
    "switched_off",
    "order_draft",
    "order_cancelled",
    "not_requested",
    "not_sent",
    "recipient_limit",
    "delivery_failed",
    "delivery_recorded",
    "window_over",
    "action_closed",
    "scheduled",
    "window_before_send_time",
]


class BuyerMailStatusResponse(TransportModel):
    kind: BuyerMailKindValue
    state: Literal["not_due", "queued", "sent", "failed", "skipped"]
    sent_at: datetime | None = Field(
        description="When the mail of this kind was last sent, if ever."
    )
    reason: BuyerMailReasonValue | None = Field(
        description=(
            "Set for `not_due`, `skipped` and `failed`. `not_requested` and "
            "`not_sent` mean that the mail is due but never went out; "
            "`canResend` is then true. A `failed` confirmation with "
            "`delivery_recorded`, `window_over` or `action_closed` was queued "
            "in time and reached by the worker too late; it is not sent any "
            "more. `scheduled` and `window_before_send_time` belong to the "
            "delivery-day mail."
        )
    )
    can_resend: bool = Field(
        description=(
            "`resendBuyerMail` is allowed for this kind now: the mail is due "
            "and no job of it waits. With `sentAt` null it is the first send."
        )
    )


class BuyerMailResendResponse(BuyerMailStatusResponse):
    replayed: bool = Field(
        description=(
            "The `Idempotency-Key` was used before: this call wrote no new "
            "job and sends no further mail."
        )
    )


class BuyerMailCompletionResponse(TransportModel):
    confirmation_due: bool = Field(
        description=("Whether completing the draft now sends the order confirmation.")
    )
    reason: BuyerMailReasonValue | None = Field(
        description="Why no confirmation would be sent; null when one is due."
    )


class BuyerMailListResponse(TransportModel):
    commitment_id: UUID
    mails: list[BuyerMailStatusResponse]
    completion: BuyerMailCompletionResponse | None = Field(
        description=(
            "Only for a draft: what completing it now would send. The rule is "
            "the one of the mail status. A delivery window that the completion "
            "itself selects is not known here."
        )
    )


class CommitmentCurrencyTotalResponse(TransportModel):
    currency: str
    total_minor: int = Field(ge=0)


class CommitmentListResponse(TransportModel):
    action_id: UUID
    items: list[CommitmentRecordResponse]
    currency_totals: list[CommitmentCurrencyTotalResponse]
    total_pieces: int = Field(ge=0)
    total_boxes: int = Field(ge=0, deprecated=BOX_FIELD_DEPRECATION)
    quantities: list[UnitQuantityResponse]


class IssueInvoiceRequest(TransportModel):
    service_on: date


class RecordInvoicePaymentRequest(TransportModel):
    # Any received amount in cents: partial and over payments are entries too.
    amount_minor: int = Field(ge=1, le=10_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    received_on: date
    reference: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=500)
    # `settlementVersion` of the invoice the form was opened with; a stale
    # value is rejected with 409 `invoice_settlement_stale`.
    expected_settlement_version: int | None = Field(default=None, ge=0)


class ReverseInvoicePaymentRequest(TransportModel):
    reason: str = Field(min_length=8, max_length=500)
    expected_settlement_version: int | None = Field(default=None, ge=0)


class CancelInvoiceRequest(TransportModel):
    reason: str = Field(min_length=8, max_length=500)


class InvoiceIssuerResponse(TransportModel):
    legal_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    tax_identifier: str
    email: str


class InvoicePaymentDetailsResponse(TransportModel):
    account_holder: str
    iban: str
    bic: str | None


class InvoiceProfileResponse(TransportModel):
    legal_configuration_version_id: UUID | None
    issuer: InvoiceIssuerResponse
    payment_details: InvoicePaymentDetailsResponse | None
    tax_treatment: Literal["standard_vat", "small_business", "tax_exempt"]
    tax_rate_basis_points: int = Field(ge=0, le=10_000)
    tax_note: str
    next_invoice_number: str
    payment_terms_days: int = Field(ge=1, le=120)
    confirmed_at: datetime | None
    ready_to_issue: bool


class InvoiceLineResponse(TransportModel):
    description: str
    quantity: int = Field(ge=1)
    unit: OfferingUnitValue
    unit_price_gross_minor: int = Field(ge=0)
    tax_rate_basis_points: int = Field(ge=0, le=10_000)
    net_minor: int = Field(ge=0)
    tax_minor: int = Field(ge=0)
    gross_minor: int = Field(ge=0)
    currency: str


class InvoiceResponse(TransportModel):
    id: UUID
    action_id: UUID
    commitment_id: UUID
    number: str
    status: Literal["issued", "sent", "paid", "cancelled"]
    issued_at: datetime
    service_on: date
    due_on: date
    issuer: InvoiceIssuerResponse
    payment_details: InvoicePaymentDetailsResponse
    recipient: CommitmentInvoiceRecipientResponse
    lines: list[InvoiceLineResponse]
    tax_treatment: Literal["standard_vat", "small_business", "tax_exempt"]
    tax_note: str
    net_minor: int = Field(ge=0)
    tax_minor: int = Field(ge=0)
    gross_minor: int = Field(ge=0)
    currency: str
    payment_reference: str
    approved_by_user_id: UUID
    replayed: bool


class InvoiceContextResponse(TransportModel):
    action_id: UUID
    action_name: str
    starts_on: date
    ends_on: date
    profile: InvoiceProfileResponse | None
    may_issue: bool
    may_manage_settlements: bool


class InvoiceDeliveryResponse(TransportModel):
    id: UUID
    action_id: UUID
    invoice_id: UUID
    generated_document_id: UUID
    recipient_email: str
    subject: str
    status: Literal["queued", "sending", "retrying", "failed", "sent"]
    message_id: str | None
    attempts: int = Field(ge=0)
    last_error_code: str | None
    last_error_detail: str | None
    requested_at: datetime
    sent_at: datetime | None
    can_retry: bool


class InvoicePaymentReversalResponse(TransportModel):
    id: UUID
    action_id: UUID
    invoice_id: UUID
    payment_id: UUID
    reason: str
    reversed_by_user_id: UUID
    reversed_by_display_name: str | None
    reversed_at: datetime
    replayed: bool


class InvoicePaymentResponse(TransportModel):
    id: UUID
    action_id: UUID
    invoice_id: UUID
    amount_minor: int = Field(ge=1)
    currency: str
    received_on: date
    reference: str
    recorded_by_user_id: UUID
    recorded_by_display_name: str | None
    recorded_at: datetime
    replayed: bool
    note: str | None = None
    # Set once the entry is reversed; it then no longer counts as paid.
    reversal: InvoicePaymentReversalResponse | None = None


class InvoiceCancellationResponse(TransportModel):
    id: UUID
    action_id: UUID
    invoice_id: UUID
    original_status: Literal["issued", "sent", "paid"]
    reason: str
    requested_by_user_id: UUID
    requested_by_display_name: str | None
    requested_at: datetime
    replayed: bool


class InvoiceRecordResponse(TransportModel):
    invoice: InvoiceResponse
    buyer_display_name: str
    # Remainder still to be received: total minus active payment entries.
    open_minor: int = Field(ge=0)
    payment: InvoicePaymentResponse | None = Field(
        description=(
            "Deprecated: the newest active (not reversed) payment entry. Before "
            "partial payments (ADR-0014) a non-null value meant fully paid; it "
            "no longer does. Use `settlementStatus`, `openMinor` and `payments`."
        ),
    )
    cancellation: InvoiceCancellationResponse | None
    deliveries: list[InvoiceDeliveryResponse]
    # Every payment entry, reversed ones included, oldest first.
    payments: list[InvoicePaymentResponse] = Field(default_factory=list)
    paid_minor: int = Field(default=0, ge=0)
    overpaid_minor: int = Field(default=0, ge=0)
    settlement_status: Literal[
        "open", "partially_paid", "paid", "overpaid", "cancelled"
    ] = "open"
    settlement_version: int = Field(default=0, ge=0)


class InvoiceCurrencyTotalResponse(TransportModel):
    currency: str
    gross_minor: int = Field(ge=0)
    open_minor: int = Field(ge=0)


class InvoiceListResponse(TransportModel):
    action_id: UUID
    items: list[InvoiceRecordResponse]
    currency_totals: list[InvoiceCurrencyTotalResponse]


class DashboardGoalResponse(TransportModel):
    configured: bool
    actual_value: str
    target_value: str | None
    unit: str | None
    currency: str
    progress_basis_points: int | None = Field(default=None, ge=0)


class DashboardPipelineResponse(TransportModel):
    open: int = Field(ge=0)
    contacted: int = Field(ge=0)
    committed: int = Field(ge=0)
    declined: int = Field(ge=0)
    handed_over: int = Field(ge=0)
    total: int = Field(ge=0)


class DashboardReminderResponse(TransportModel):
    overdue: int = Field(ge=0)
    today: int = Field(ge=0)
    upcoming: int = Field(ge=0)
    unscheduled: int = Field(ge=0)
    total: int = Field(ge=0)


class DashboardCommitmentResponse(TransportModel):
    draft: int = Field(ge=0)
    review_ready: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    invoiced: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    total: int = Field(ge=0)
    active_total: int = Field(ge=0)
    active_total_minor: int = Field(ge=0)
    total_boxes: int = Field(ge=0, deprecated=BOX_FIELD_DEPRECATION)
    total_pieces: int = Field(ge=0)
    quantities: list[UnitQuantityResponse]
    currency: str


class DashboardInvoiceResponse(TransportModel):
    issued: int = Field(ge=0)
    sent: int = Field(ge=0)
    open: int = Field(ge=0)
    paid: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    total: int = Field(ge=0)
    invoiced_amount_minor: int = Field(ge=0)
    open_amount_minor: int = Field(ge=0)
    overdue: int = Field(ge=0)
    overdue_amount_minor: int = Field(ge=0)
    delivery_failed: int = Field(ge=0)
    currency: str


class DashboardOrderValueWeekResponse(TransportModel):
    week_start: date
    iso_week: int = Field(ge=1, le=53)
    total_minor: int = Field(ge=0)


class DashboardDeliveryWindowResponse(TransportModel):
    id: UUID
    starts_at: datetime
    ends_at: datetime
    commitments: int = Field(ge=0)
    quantities: list[UnitQuantityResponse]
    fully_booked: bool


class DashboardDeliveryResponse(TransportModel):
    enabled: bool
    windows: list[DashboardDeliveryWindowResponse]


class AcquirerDashboardResponse(TransportModel):
    pipeline: DashboardPipelineResponse
    reminders: DashboardReminderResponse
    activity_count: int = Field(ge=0)


class CharityAdminDashboardResponse(TransportModel):
    pipeline: DashboardPipelineResponse
    commitments: DashboardCommitmentResponse
    invoices: DashboardInvoiceResponse
    order_value_weeks: list[DashboardOrderValueWeekResponse]
    delivery: DashboardDeliveryResponse


class DashboardMetricDefinitionResponse(TransportModel):
    key: str
    label: str
    description: str
    href: str


class DashboardResponse(TransportModel):
    action_id: UUID
    action_name: str
    beneficiaries: list[str]
    goal: DashboardGoalResponse
    acquirer: AcquirerDashboardResponse | None
    charity_admin: CharityAdminDashboardResponse | None
    metric_definitions: list[DashboardMetricDefinitionResponse]
    generated_at: datetime


GeneratedDocumentReferenceKindValue = Literal[
    "action",
    "commitment",
    "invoice",
    "twenty_company",
    "twenty_person",
]


class GeneratedDocumentResponse(TransportModel):
    id: UUID
    action_id: UUID
    commitment_id: UUID | None
    invoice_id: UUID | None
    twenty_company_id: UUID | None
    twenty_person_id: UUID | None
    document_type: Literal["invoice_pdf"]
    media_type: str
    filename: str | None
    size_bytes: Annotated[int, Field(ge=1)] | None
    render_version: str | None
    version: int = Field(ge=1)
    status: Literal["pending", "available", "deleted"]
    created_at: datetime
    available_at: datetime | None
    sent_at: datetime | None


class GeneratedDocumentRecordResponse(TransportModel):
    document: GeneratedDocumentResponse
    invoice_number: str | None
    buyer_display_name: str


class GeneratedDocumentReferenceResponse(TransportModel):
    kind: GeneratedDocumentReferenceKindValue
    id: UUID


class GeneratedDocumentListResponse(TransportModel):
    action_id: UUID
    reference: GeneratedDocumentReferenceResponse
    items: list[GeneratedDocumentRecordResponse]


class UpdateActionDetailsRequest(TransportModel):
    revision: int = Field(ge=1)
    carrier_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2_000)
    starts_on: date
    ends_on: date


class SetActionPublicationRequest(TransportModel):
    revision: int = Field(ge=1)
    publication_starts_at: datetime | None = None
    publication_ends_at: datetime | None = None
    public_alias: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )


class CreateCampaignAliasRequest(TransportModel):
    command_id: UUID
    alias_id: UUID
    alias: str = Field(
        min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    enabled: bool = Field(default=True, strict=True)


class UpdateCampaignAliasRequest(TransportModel):
    command_id: UUID
    revision: int = Field(ge=1, strict=True)
    target_action_id: UUID
    alias: str = Field(
        min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    enabled: bool = Field(strict=True)


class RemoveCampaignAliasRequest(TransportModel):
    command_id: UUID
    revision: int = Field(ge=1, strict=True)


class SelectCampaignRendererRequest(TransportModel):
    command_id: UUID
    revision: int = Field(ge=1, strict=True)
    renderer: Literal["legacy", "campaign"]


class CampaignRendererResponse(TransportModel):
    alias_id: UUID
    action_id: UUID
    alias: str
    revision: int
    renderer: Literal["legacy", "campaign"]


class CampaignAliasMutationResponse(TransportModel):
    alias_id: UUID
    action_id: UUID
    alias: str
    enabled: bool
    revision: int
    removed: bool


class CampaignAliasItemResponse(TransportModel):
    alias_id: UUID
    action_id: UUID
    alias: str
    is_primary: bool
    enabled: bool
    revision: int


class CampaignAliasTargetResponse(TransportModel):
    action_id: UUID
    name: str
    canonical_path: str


class CampaignAliasListResponse(TransportModel):
    action_id: UUID
    canonical_path: str
    items: list[CampaignAliasItemResponse]
    targets: list[CampaignAliasTargetResponse]


class AdministratorOptionResponse(TransportModel):
    user_id: UUID
    display_name: str
    email: str
    is_available: bool
    is_responsible: bool


class ActionManagementResponse(TransportModel):
    action: CharityActionResponse
    public_alias: str | None
    administrator_options: list[AdministratorOptionResponse]
    allowed_transitions: list[CharityActionStatusValue]


class SetResponsibleAdministratorsRequest(TransportModel):
    revision: int = Field(ge=1)
    user_ids: list[UUID] = Field(min_length=1)


class SetActionGoalRequest(ActionGoalRequest):
    revision: int = Field(ge=1)


class SetActionCapabilitiesRequest(TransportModel):
    revision: int = Field(ge=1)
    capabilities: list[ActionCapabilityValue]


class SetActionBeneficiariesRequest(TransportModel):
    revision: int = Field(ge=1)
    beneficiaries: list[BeneficiaryDraftRequest] = Field(min_length=1)


class TransitionCharityActionRequest(TransportModel):
    revision: int = Field(ge=1)
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


class SponsorDraftRequest(TransportModel):
    company_name: str | None = Field(default=None, max_length=300)
    given_name: str | None = Field(default=None, max_length=200)
    family_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    street_line_1: str | None = Field(default=None, max_length=300)
    postal_code: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_optional_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return normalized_invitation_email(value)

    @model_validator(mode="after")
    def validate_match_key(self) -> SponsorDraftRequest:
        company_name = (self.company_name or "").strip()
        given_name = (self.given_name or "").strip()
        family_name = (self.family_name or "").strip()
        email = (self.email or "").strip()
        if not company_name and (not given_name or not family_name):
            raise ValueError("Bitte einen Firmennamen oder Vor- und Nachnamen angeben.")
        if (
            company_name
            and (given_name or family_name or email)
            and (not given_name or not family_name)
        ):
            raise ValueError(
                "Für einen Firmenkontakt bitte Vor- und Nachnamen gemeinsam angeben."
            )
        return self


class AssignedAcquirerResponse(TransportModel):
    user_id: UUID
    display_name: str


class SponsorMatchCandidateResponse(TransportModel):
    party_kind: Literal["company", "person"]
    twenty_id: UUID
    display_name: str
    postal_code: str | None
    city: str | None
    email: str | None
    assigned_acquirers: list[AssignedAcquirerResponse]


class SponsorDraftResponse(TransportModel):
    company_name: str | None
    given_name: str | None
    family_name: str | None
    email: str | None
    street_line_1: str | None
    postal_code: str | None
    city: str | None


class SponsorMatchResponse(TransportModel):
    status: Literal["no_match", "single_match", "ambiguous_match"]
    party_kind: Literal["company", "person"]
    normalized_key: str
    input: SponsorDraftResponse
    candidates: list[SponsorMatchCandidateResponse]


class ResolveSponsorMatchRequest(TransportModel):
    command_id: UUID
    sponsor: SponsorDraftRequest
    expected_status: Literal["no_match", "single_match", "ambiguous_match"]
    selected_twenty_id: UUID | None = None
    confirm_existing_assignments: bool = False


class SponsorResolutionResponse(TransportModel):
    outcome: Literal["created", "reused"]
    party_kind: Literal["company", "person"]
    twenty_id: UUID
    display_name: str
    normalized_key: str
    assignment_id: UUID
    assignment_created: bool
    prior_assignees: list[AssignedAcquirerResponse]
    contact_twenty_id: UUID | None
    replayed: bool


AssignmentPartyKindValue = Literal["company", "person"]
AssignmentStatusValue = Literal[
    "open",
    "contacted",
    "committed",
    "declined",
    "handed_over",
]


class CreateAcquisitionAssignmentRequest(TransportModel):
    party_kind: AssignmentPartyKindValue
    party_id: UUID
    acquirer_user_id: UUID


class UpdateAcquisitionAssignmentRequest(TransportModel):
    revision: int = Field(ge=1)
    status: Literal["open", "contacted", "committed", "declined"]
    priority: int = Field(ge=0, le=3)
    next_action: str | None = Field(default=None, max_length=300)
    due_at: datetime | None = None


class HandOverAcquisitionAssignmentRequest(TransportModel):
    revision: int = Field(ge=1)
    target_acquirer_user_id: UUID


class AcquisitionAssignmentResponse(TransportModel):
    id: UUID
    action_id: UUID
    party_kind: AssignmentPartyKindValue
    party_id: UUID
    acquirer_user_id: UUID
    acquirer_display_name: str
    status: AssignmentStatusValue
    priority: int = Field(ge=0, le=3)
    next_action: str | None
    due_at: datetime | None
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class AcquisitionAssignmentMutationResponse(TransportModel):
    assignment: AcquisitionAssignmentResponse
    created: bool


class AcquisitionAssignmentHistoryResponse(TransportModel):
    id: UUID
    assignment_id: UUID
    changed_by_user_id: UUID
    changed_by_display_name: str
    previous_state: dict[str, object]
    new_state: dict[str, object]
    changed_at: datetime


class AcquisitionAssignmentDetailsResponse(TransportModel):
    assignment: AcquisitionAssignmentResponse
    history: list[AcquisitionAssignmentHistoryResponse]


class AcquisitionAssignmentHandoverResponse(TransportModel):
    source: AcquisitionAssignmentResponse
    target: AcquisitionAssignmentResponse
    target_created: bool


ActivityChannelValue = Literal[
    "phone",
    "email",
    "in_person",
]
ActivityOutcomeValue = Literal[
    "reached",
    "no_answer",
    "interested",
    "follow_up",
    "committed",
    "declined",
]
ReminderUrgencyValue = Literal["overdue", "today", "upcoming", "none"]


class RecordAcquisitionActivityRequest(TransportModel):
    party_kind: AssignmentPartyKindValue
    party_id: UUID
    revision: int = Field(ge=1)
    channel: ActivityChannelValue
    outcome: ActivityOutcomeValue
    note: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=300)
    due_on: date | None = None
    captured_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the capture was saved on the device (ISO 8601 with offset), "
            "sent by the PWA offline queue. It becomes `occurredAt` of the activity. With it, a moved assignment no longer refuses the contact: it is recorded and `assignmentUpdated` is false. At most 14 days before and 5 "
            "minutes after the server time, otherwise 422 "
            "`captured_at_out_of_range`. Rights, prices, windows and "
            "suppression are still checked at send time."
        ),
    )

    @model_validator(mode="after")
    def validate_reminder_pair(self) -> RecordAcquisitionActivityRequest:
        if (self.next_action is None) != (self.due_on is None):
            raise ValueError(
                "Wiedervorlage benötigt nächste Aktion und Fälligkeitsdatum."
            )
        return self


class AcquisitionActivityWorkItemResponse(TransportModel):
    assignment_id: UUID
    party_kind: AssignmentPartyKindValue
    party_id: UUID
    party_display_name: str
    postal_code: str | None
    city: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    suppressed_channels: list[Literal["email", "phone", "postal"]]
    assigned_acquirers: list[AssignedAcquirerResponse]
    status: AssignmentStatusValue
    priority: int = Field(ge=0, le=3)
    next_action: str | None
    due_at: datetime | None
    urgency: ReminderUrgencyValue
    revision: int = Field(ge=1)


class RecordedAcquisitionActivityResponse(TransportModel):
    id: UUID
    action_id: UUID
    assignment_id: UUID
    party_kind: AssignmentPartyKindValue
    party_id: UUID
    party_display_name: str
    actor_user_id: UUID
    actor_display_name: str
    channel: ActivityChannelValue
    outcome: ActivityOutcomeValue
    note: str | None
    next_action: str | None
    due_at: datetime | None
    assignment_revision: int = Field(
        ge=1,
        description=(
            "The assignment revision this activity produced; for a contact "
            "kept on a moved assignment (`assignmentUpdated` false) the "
            "revision it met. Stable across replays."
        ),
    )
    occurred_at: datetime


class AcquisitionActivityBoardResponse(TransportModel):
    action_id: UUID
    generated_at: datetime
    work_items: list[AcquisitionActivityWorkItemResponse]
    activities: list[RecordedAcquisitionActivityResponse]


class RecordAcquisitionActivityResponse(TransportModel):
    assignment: AcquisitionAssignmentResponse
    activity: RecordedAcquisitionActivityResponse
    assignment_updated: bool = Field(
        default=True,
        description=(
            "False when a capture with `capturedAt` met an assignment that "
            "changed meanwhile: the contact is recorded, status, next action "
            "and due date stay as `assignment` shows them. A queue moves the "
            "base revision of its later entries only when this is true, and "
            "only to `activity.assignmentRevision` (never to "
            "`assignment.revision`, which may contain someone else's change)."
        ),
    )
    replayed: bool = Field(
        default=False,
        description=(
            "True when the `Idempotency-Key` was already processed. The "
            "answer then carries the stored activity with the revision that "
            "send produced (`activity.assignmentRevision`) and the stored "
            "`assignmentUpdated`; `assignment` is the current assignment."
        ),
    )


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


ActivityFeedStatusValue = Literal["all", "unread"]


class ActivityFeedQuery(TransportModel):
    status: ActivityFeedStatusValue = "all"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class ActivityFeedItemResponse(TransportModel):
    id: UUID
    action_id: UUID
    action_name: str
    event_type: Literal["public_order_received"]
    party_kind: Literal["company", "person"]
    party_id: UUID
    party_display_name: str
    commitment_id: UUID
    public_reference: str
    total_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    total_boxes: int = Field(ge=0, deprecated=BOX_FIELD_DEPRECATION)
    total_pieces: int = Field(ge=0)
    quantities: list[UnitQuantityResponse]
    next_action_label: str
    next_action_href: str
    occurred_at: datetime
    read_at: datetime | None
    is_read: bool


class ActivityFeedResponse(TransportModel):
    items: list[ActivityFeedItemResponse]
    total: int = Field(ge=0)
    unread_count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class UpdateActivityFeedItemRequest(TransportModel):
    read: bool


class ActivityFeedReadAllResponse(TransportModel):
    updated: int = Field(ge=0)


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


class OperationalApiMetricsResponse(TransportModel):
    requests: int = Field(ge=0)
    errors: int = Field(ge=0)
    average_latency_ms: float = Field(ge=0)


class OperationalDependencyResponse(TransportModel):
    dependency: Literal["twenty", "rustfs", "mail", "worker"]
    status: Literal["ready", "unavailable"]
    latency_ms: float = Field(ge=0)
    request_id: str
    error_code: str | None


class OperationalStatusCountsResponse(TransportModel):
    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    completed: int = Field(ge=0)
    dead_letter: int = Field(ge=0)


class OperationalLoginMetricsResponse(TransportModel):
    challenges_last24h: int = Field(ge=0)
    completions_last24h: int = Field(ge=0)
    failures_last24h: int = Field(ge=0)


class OperationalFailedJobResponse(TransportModel):
    id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    attempts: int = Field(ge=1)
    last_error_code: str
    failed_at: datetime
    manual_retry_count: int = Field(ge=0)


class OperationalCheckResponse(TransportModel):
    key: Literal["backup", "disk", "tls"]
    status: Literal["ready", "critical"]
    value: float


class OperationalAlertResponse(TransportModel):
    name: str
    severity: Literal["P0", "P1", "P2"]
    category: str
    summary: str
    runbook_url: str


class OperationalMonitoringResponse(TransportModel):
    status: Literal["inactive", "ready", "attention", "unavailable"]
    checks: list[OperationalCheckResponse]
    active_alerts: list[OperationalAlertResponse]


class OperationalSiteHostResponse(TransportModel):
    """A campaign host whose check failed or that waits for its certificate."""

    hostname: str
    status: Literal["pending", "verified", "active", "disabled"]
    failed_checks: int = Field(ge=0)
    last_check_result: str | None
    last_checked_at: datetime | None
    live_bindings: int = Field(ge=0)


class OperationsOverviewResponse(TransportModel):
    generated_at: datetime
    request_id: str
    api: OperationalApiMetricsResponse
    dependencies: list[OperationalDependencyResponse]
    outbox: OperationalStatusCountsResponse
    next_pending_attempt_at: datetime | None = Field(
        default=None,
        description="Earliest available_at of a pending job; null when none waits.",
    )
    oldest_due_pending_age_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Seconds the oldest due pending job has waited; null when none is due.",
    )
    mail: OperationalStatusCountsResponse
    login: OperationalLoginMetricsResponse
    failed_jobs: list[OperationalFailedJobResponse]
    monitoring: OperationalMonitoringResponse
    site_hosts: list[OperationalSiteHostResponse] = Field(
        default_factory=list,
        description="Campaign hosts with failed checks, lapsed with live "
        "editions, or waiting for their certificate (specs/multi-domain §7.4).",
    )


class PilotDailyDependenciesResponse(TransportModel):
    ready: int = Field(ge=0)
    total: int = Field(ge=1)
    unavailable: list[Literal["twenty", "rustfs", "mail", "worker"]]


class PilotDailyMonitoringResponse(TransportModel):
    status: Literal["inactive", "ready", "attention", "unavailable"]
    backup_status: Literal["ready", "critical", "unavailable"]
    backup_age_seconds: float | None = Field(default=None, ge=0)
    disk_status: Literal["ready", "critical", "unavailable"]
    disk_free_ratio: float | None = Field(default=None, ge=0, le=1)
    tls_status: Literal["ready", "critical", "unavailable"]
    tls_remaining_seconds: float | None = Field(default=None, ge=0)
    active_p0: int = Field(ge=0)
    active_p1: int = Field(ge=0)
    active_p2: int = Field(ge=0)


class PilotDailyReportResponse(TransportModel):
    schema_version: Literal["leonaid.pilot.daily-report/v1"]
    scope: Literal["technical-daily-check"]
    generated_at: datetime
    release: str
    technical_status: Literal["ready", "attention", "blocked"]
    dependencies: PilotDailyDependenciesResponse
    monitoring: PilotDailyMonitoringResponse
    outbox: OperationalStatusCountsResponse
    api: OperationalApiMetricsResponse
    stop_reasons: list[str]
    next_step: str
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SupportRequestDiagnosticResponse(TransportModel):
    support_code: str = Field(min_length=8, max_length=128)
    occurred_at: datetime
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    route: str
    status_code: int = Field(ge=100, le=599)
    error_code: str | None
    outcome: Literal["successful", "rejected", "failed"]
    impact: str
    next_step: str
    release: str


class OperationalJobRetryResponse(TransportModel):
    id: UUID
    status: Literal["pending"]
    manual_retry_count: int = Field(ge=1)
    request_id: str


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


def _conflicts(*codes: str) -> dict[int | str, dict[str, object]]:
    """Authenticated responses whose 409 lists the command's stable codes."""

    return {
        **AUTHENTICATED_ERROR_RESPONSES,
        409: {
            "model": ApiErrorResponse,
            "description": "Änderung kollidiert mit dem aktuellen Zustand. "
            "Stabile Codes: " + ", ".join(f"`{code}`" for code in codes) + ".",
        },
    }


# The admin-access invariants: at least one active system admin and one
# active lead (charity admin) per open action; only active accounts count.
MEMBER_STATUS_CONFLICT_RESPONSES = _conflicts(
    "account_revision_conflict",
    "account_status_unchanged",
    "account_invitation_activation_forbidden",
    "account_self_status_change_forbidden",
    "admin_scope_changed",
    "last_system_admin_suspension_forbidden",
    "last_system_admin_archival_forbidden",
    "last_charity_admin_suspension_forbidden",
    "last_charity_admin_archival_forbidden",
    "idempotency_conflict",
    "idempotency_incomplete",
)
MEMBER_GLOBAL_ROLE_CONFLICT_RESPONSES = _conflicts(
    "account_revision_conflict",
    "role_assignment_unchanged",
    "admin_scope_changed",
    "last_system_admin_role_forbidden",
    "idempotency_conflict",
    "idempotency_incomplete",
)
MEMBER_ACTION_ROLE_CONFLICT_RESPONSES = _conflicts(
    "account_revision_conflict",
    "role_assignment_unchanged",
    "role_action_scope_changed",
    "driver_role_capability_missing",
    "last_charity_admin_role_forbidden",
    "idempotency_conflict",
    "idempotency_incomplete",
)

# Action creation: the creator becomes the action's only lead, so it must
# still be an active account when the action is written.
ACTION_CREATE_CONFLICT_RESPONSES = _conflicts(
    "action_responsible_administrator_unavailable",
    "action_archive_slug_conflict",
)


def _invalid(
    responses: dict[int | str, dict[str, object]], *codes: str
) -> dict[int | str, dict[str, object]]:
    """Responses whose 422 also lists the command's stable domain codes."""

    return {
        **responses,
        422: {
            "model": ApiErrorResponse,
            "description": "Transport- oder Fachvalidierung ist fehlgeschlagen "
            "(`request_invalid`). Stabile Fachcodes: "
            + ", ".join(f"`{code}`" for code in codes)
            + ".",
        },
    }


# Contact attempts; the PWA offline queue maps these (PLAN §9.4, §10.1).
ACTIVITY_RECORD_CONFLICT_RESPONSES = _invalid(
    _conflicts(
        "assignment_revision_conflict",
        "contact_suppressed",
        "idempotency_conflict",
        "idempotency_incomplete",
    ),
    "activity_idempotency_key_invalid",
    "captured_at_out_of_range",
)

# Order capture; the PWA offline queue maps these (PLAN §10.2).
COMMITMENT_CREATE_CONFLICT_RESPONSES = _invalid(
    _conflicts(
        "commitment_price_changed",
        "commitment_ordering_disabled",
        "commitment_action_closed",
        "commitment_concurrent_retry",
        "delivery_window_full",
        "idempotency_conflict",
    ),
    "captured_at_out_of_range",
    "captured_at_source_invalid",
    "commitment_client_quote_required",
    "commitment_idempotency_key_invalid",
    "delivery_window_unavailable",
    "delivery_required",
    "offering_not_available",
)

# Completing an own draft; the PWA offline queue maps these (PLAN §10.2).
COMMITMENT_COMPLETE_CONFLICT_RESPONSES = _invalid(
    _conflicts(
        "commitment_not_draft",
        "commitment_action_closed",
        "commitment_concurrent_retry",
        "delivery_window_full",
        "idempotency_conflict",
    ),
    "captured_at_out_of_range",
    "commitment_idempotency_key_invalid",
    "delivery_window_unavailable",
    "delivery_required",
)

RequestIdHeader = Annotated[
    str | None,
    Field(
        description="Optionaler Korrelationsschlüssel; ungültige Werte werden ersetzt.",
        examples=["poc023:contract:golden-v1"],
    ),
]


# ---------- Delivery day board ----------


class DeliveryDropQuantityResponse(TransportModel):
    unit: Literal["box", "piece", "package", "sponsoring"]
    quantity: int


class DeliveryDropAddressResponse(TransportModel):
    recipient_name: str
    street_line1: str
    postal_code: str
    city: str


class DeliveryDropContactResponse(TransportModel):
    name: str | None
    phone: str | None
    driver_note: str | None


class DeliveryDropResponse(TransportModel):
    """One order on the board. Never amounts, e-mail or the order message."""

    commitment_id: UUID
    window_id: UUID
    buyer_name: str
    quantities: list[DeliveryDropQuantityResponse]
    total_boxes: int
    address: DeliveryDropAddressResponse | None
    contact: DeliveryDropContactResponse | None
    state: Literal["open", "delivered", "missed"]
    state_changed_at: datetime | None
    state_changed_by_name: str | None
    driver_user_id: UUID | None
    driver_name: str | None
    revision: int
    # Marked missed when its window was closed; only such a drop can return
    # to "missed" while the window stays closed.
    missed_at_closure: bool
    # Managers only: the order status (cancelled drops stay struck through).
    order_status: (
        Literal["draft", "review_ready", "confirmed", "invoiced", "cancelled"] | None
    )


class DeliveryWindowClosureResponse(TransportModel):
    closed_at: datetime
    closed_by_name: str
    missed_count: int


class DeliveryBoardWindowResponse(TransportModel):
    id: UUID
    starts_at: datetime
    ends_at: datetime
    retired: bool
    fully_booked: bool
    closure: DeliveryWindowClosureResponse | None
    drops: list[DeliveryDropResponse]


class DeliveryBoardDriverResponse(TransportModel):
    user_id: UUID
    display_name: str


class DeliveryBoardResponse(TransportModel):
    action_id: UUID
    action_name: str
    timezone: str
    day: date | None
    days: list[date]
    manager: bool
    windows: list[DeliveryBoardWindowResponse]
    drivers: list[DeliveryBoardDriverResponse]
    follow_up_tasks: bool


class DeliveryStateRequest(TransportModel):
    """Target state: delivered, missed ("Nicht angetroffen", spec D13) or
    open when neither is set."""

    delivered: bool
    missed: bool = False
    expected_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def one_target(self) -> DeliveryStateRequest:
        if self.delivered and self.missed:
            raise ValueError("delivered and missed exclude each other")
        return self


class DeliveryDriverAssignmentRequest(TransportModel):
    commitment_ids: list[UUID] = Field(min_length=1, max_length=1000)
    driver_user_id: UUID | None


class DeliveryDriverAssignmentResponse(TransportModel):
    changed: int


class DeliveryTourStopResponse(TransportModel):
    drop: DeliveryDropResponse
    base_rank: int
    # None while the driver has no own order.
    driver_rank: int | None
    effective_rank: int
    new_for_driver: bool
    # Coordinates of the current address; null until found or pinned.
    lat: float | None
    lon: float | None


class DeliveryPinRequest(TransportModel):
    lat: Latitude
    lon: Longitude


class MapTilesResponse(TransportModel):
    """Leaflet tile URL template ({z}/{x}/{y}) and the attribution to show."""

    tile_url: str
    attribution: str


class DeliveryTourWindowResponse(TransportModel):
    window_id: UUID
    starts_at: datetime
    ends_at: datetime
    closed: bool
    stops: list[DeliveryTourStopResponse]


class DeliveryTourResponse(TransportModel):
    driver_user_id: UUID
    driver_name: str
    day: date
    revision: str
    driver_ordered_at: datetime | None
    windows: list[DeliveryTourWindowResponse]


class DeliveryDayToursResponse(TransportModel):
    action_id: UUID
    action_name: str
    timezone: str
    day: date | None
    days: list[date]
    unassigned: list[DeliveryTourWindowResponse]
    tours: list[DeliveryTourResponse]
    drivers: list[DeliveryBoardDriverResponse]
    start_point: DeliveryStartPointResponse | None
    map: MapTilesResponse


class MyTourResponse(TransportModel):
    action_id: UUID
    action_name: str
    timezone: str
    days: list[date]
    tour: DeliveryTourResponse | None
    start_point: DeliveryStartPointResponse | None
    map: MapTilesResponse


class MyTourReadRequest(TransportModel):
    window_id: UUID
    read_at: AwareDatetime = Field(
        description="Wann das Gerät die Stopps des Fensters offline zeigte; "
        "höchstens 14 Tage vor und höchstens 5 Minuten nach der Empfangszeit "
        "des Servers (Uhrabweichung des Geräts), sonst "
        "`tour_read_out_of_range` für die ganze Anfrage."
    )


class MyTourReadsRequest(TransportModel):
    """Offline reads of "Meine Tour", sent with the next sync (spec §10).
    Windows without a stop of the driver are ignored."""

    reads: list[MyTourReadRequest] = Field(min_length=1, max_length=50)


# Offline reads of "Meine Tour" (spec §10, D14 d).
MY_TOUR_READS_RESPONSES = _invalid(
    AUTHENTICATED_ERROR_RESPONSES, "tour_read_out_of_range"
)


class DeliveryTourOrderRequest(TransportModel):
    """Stop ids of one tour in the wanted order. A driver may send an empty
    list to go back to the planned order."""

    day: date
    expected_revision: str = Field(min_length=1, max_length=64)
    commitment_ids: list[UUID] = Field(max_length=500)


class DeliveryWindowClosureResultResponse(TransportModel):
    missed_count: int
    follow_up: Literal["tasks", "board"]


class DeliveryWindowReopenResponse(TransportModel):
    reopened_count: int
