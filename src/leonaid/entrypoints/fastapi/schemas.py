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
ActionTemplateKeyValue = Literal["blank", "krapfentaxi"]
OfferingStatusValue = Literal["draft", "active", "inactive"]
OfferingUnitValue = Literal["box", "piece", "package", "sponsoring"]


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
    publication_starts_at: datetime | None
    publication_ends_at: datetime | None
    archive_slug: str
    revision: int = Field(ge=1)
    capabilities: list[ActionCapabilityValue]
    beneficiaries: list[BeneficiaryResponse]
    goal: ActionGoalResponse


class PublicOfferingResponse(TransportModel):
    id: UUID
    code: str
    name: str
    unit: Literal["box", "piece", "package", "sponsoring"]
    pieces_per_unit: int | None
    unit_price_minor: int = Field(ge=0)
    currency: str


class PublicOrderFormResponse(TransportModel):
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


class PublicActionRouteResponse(TransportModel):
    route_kind: Literal["alias", "archive"]
    route_value: str
    route_path: str
    canonical_path: str
    availability: Literal["published", "inactive", "archive"]
    submissions_allowed: bool
    action: PublicCharityActionResponse | None


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


class CreatePublicOrderRequest(TransportModel):
    access_token: str = Field(min_length=40, max_length=2_000)
    command_id: UUID
    party: PublicOrderPartyRequest
    delivery_recipient: PublicOrderDeliveryRecipientRequest
    invoice_recipient: PublicOrderInvoiceRecipientRequest
    lines: list[PublicOrderLineRequest] = Field(min_length=1, max_length=100)
    message: str | None = Field(default=None, max_length=1_000)
    privacy_acknowledged: bool
    binding_order_confirmed: bool
    privacy_notice_version: Literal["public-order-poc-2026-07"]
    website: str | None = Field(default=None, max_length=300)


class PublicOrderResultResponse(TransportModel):
    commitment_id: UUID
    public_reference: str
    status: Literal["review_ready"]
    total_minor: int = Field(ge=0)
    currency: str
    total_boxes: int = Field(ge=0)
    total_pieces: int = Field(ge=0)
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
    buyer: CommitmentBuyerRequest
    invoice_recipient: CommitmentInvoiceRecipientRequest | None = None
    lines: list[CommitmentLineRequest] = Field(min_length=1, max_length=100)


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
    box_count: int = Field(ge=0)
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
    buyer: CommitmentBuyerResponse
    invoice_recipient: CommitmentInvoiceRecipientResponse | None
    lines: list[CommitmentLineResponse]
    total_minor: int = Field(ge=0)
    currency: str
    total_pieces: int = Field(ge=0)
    total_boxes: int = Field(ge=0)
    replayed: bool


class CommitmentCaptureContextResponse(TransportModel):
    action_id: UUID
    action_name: str
    offerings: list[ConfiguredOfferingResponse]


class CommitmentRecordResponse(TransportModel):
    commitment: CommitmentResponse
    created_at: datetime
    captured_by_display_name: str | None


class CommitmentCurrencyTotalResponse(TransportModel):
    currency: str
    total_minor: int = Field(ge=0)


class CommitmentListResponse(TransportModel):
    action_id: UUID
    items: list[CommitmentRecordResponse]
    currency_totals: list[CommitmentCurrencyTotalResponse]
    total_pieces: int = Field(ge=0)
    total_boxes: int = Field(ge=0)


class IssueInvoiceRequest(TransportModel):
    service_on: date


class InvoiceIssuerResponse(TransportModel):
    legal_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    tax_identifier: str
    email: str


class InvoiceProfileResponse(TransportModel):
    issuer: InvoiceIssuerResponse
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


class InvoiceRecordResponse(TransportModel):
    invoice: InvoiceResponse
    buyer_display_name: str


class InvoiceCurrencyTotalResponse(TransportModel):
    currency: str
    gross_minor: int = Field(ge=0)


class InvoiceListResponse(TransportModel):
    action_id: UUID
    items: list[InvoiceRecordResponse]
    currency_totals: list[InvoiceCurrencyTotalResponse]


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
            raise ValueError("Gib einen Firmennamen oder Vorname und Nachname an.")
        if (
            company_name
            and (given_name or family_name or email)
            and (not given_name or not family_name)
        ):
            raise ValueError(
                "Gib für einen Firmenkontakt Vorname und Nachname gemeinsam an."
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
    assignment_revision: int = Field(ge=1)
    occurred_at: datetime


class AcquisitionActivityBoardResponse(TransportModel):
    action_id: UUID
    generated_at: datetime
    work_items: list[AcquisitionActivityWorkItemResponse]
    activities: list[RecordedAcquisitionActivityResponse]


class RecordAcquisitionActivityResponse(TransportModel):
    assignment: AcquisitionAssignmentResponse
    activity: RecordedAcquisitionActivityResponse


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
    total_boxes: int = Field(ge=0)
    total_pieces: int = Field(ge=0)
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
