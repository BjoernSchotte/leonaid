"""FastAPI route adapter for platform application services."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal, cast
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, Response, status

from fastapi.responses import PlainTextResponse

from leonaid.application.delivery import DeliveryService
from leonaid.application.delivery_board import DeliveryBoardService
from leonaid.application.delivery_tours import DeliveryTourService
from leonaid.domain.delivery_tours import (
    DayTours,
    DriverTour,
    MapTiles,
    MyTour,
    TourRead,
    TourStopView,
    TourWindow,
)
from leonaid.domain.delivery_board import DeliveryBoard, DeliveryDrop
from leonaid.application.delivery_completion import (
    DeliveryCompletionDraft,
    DeliveryCompletionService,
    delivery_completion_version,
)
from leonaid.domain.calendar import local_day
from leonaid.domain.delivery import (
    DeliveryConfiguration,
    DeliveryStartPoint,
    DeliveryWindow,
    DeliveryContactSnapshot,
)
from leonaid.domain.delivery_geo import GeoPoint
from leonaid.entrypoints.fastapi.schemas import (
    DeliveryConfigurationRequest,
    DeliveryPinRequest,
    DeliveryStartPointResponse,
    MapTilesResponse,
    DeliveryWindowFullyBookedRequest,
    DeliveryBoardDriverResponse,
    DeliveryBoardResponse,
    DeliveryBoardWindowResponse,
    DeliveryConfigurationResponse,
    DeliveryDriverAssignmentRequest,
    DeliveryDriverAssignmentResponse,
    DeliveryDropAddressResponse,
    DeliveryDropContactResponse,
    DeliveryDropQuantityResponse,
    DeliveryDropResponse,
    DeliveryDayToursResponse,
    DeliveryStateRequest,
    DeliveryTourOrderRequest,
    DeliveryTourResponse,
    DeliveryTourStopResponse,
    DeliveryTourWindowResponse,
    MyTourResponse,
    MyTourReadsRequest,
    MY_TOUR_READS_RESPONSES,
    DeliveryWindowClosureResponse,
    DeliveryWindowClosureResultResponse,
    DeliveryWindowReopenResponse,
    DeliveryWindowResponse,
    DeliveryContactRequest,
    PublicOrderDeliveryRecipientRequest,
)
from leonaid.application.acquisition import (
    AcquisitionParty,
    AcquisitionPolicyService,
)
from leonaid.application.activity_feed import (
    ActivityFeedItem,
    ActivityFeedService,
    ActivityFeedStatus,
)
from leonaid.application.activities import (
    AcquisitionActivityItem,
    AcquisitionActivityService,
    AcquisitionWorkItem,
)
from leonaid.application.assignments import (
    AssignmentHandoverResult,
    AssignmentManagementService,
)
from leonaid.application.commitments import (
    CommitmentCaptureContext,
    CommitmentDraft,
    CommitmentCompletion,
    CommitmentList,
    CommitmentLineDraft,
    CommitmentRecord,
    CommitmentService,
)
from leonaid.application.documents import (
    GeneratedDocumentList,
    GeneratedDocumentRecord,
    GeneratedDocumentReference,
    GeneratedDocumentReferenceKind,
    GeneratedDocumentService,
)
from leonaid.application.email_changes import EmailChangeService
from leonaid.application.site_hosts import CampaignHostUrls
from leonaid.application.campaign_aliases import (
    CampaignAliasCommand,
    CampaignAliasService,
)
from leonaid.application.campaign_renderer import CampaignRendererCommand
from leonaid.application.dashboard import (
    DashboardService,
    DashboardSnapshot,
    PipelineCounts,
)
from leonaid.application.invoice_deliveries import (
    InvoiceDelivery,
    InvoiceDeliveryKind,
    InvoiceDeliveryService,
)
from leonaid.application.invoice_settlements import InvoiceSettlementService
from leonaid.application.order_cancellation import (
    OrderCancellationRequest,
    OrderCancellationService,
)
from leonaid.domain.order_cancellation import OrderCancellation
from leonaid.application.invoices import (
    InvoiceContext,
    InvoiceList,
    InvoiceRecord,
    InvoiceService,
)
from leonaid.application.actions import (
    BeneficiaryDraft,
    CharityActionService,
    CopyActionDraft,
    CreateActionDraft,
    CreateActionFromTemplateDraft,
    PublicActionRoute,
    PublicActionRouteKind,
    UpdateActionDetailsDraft,
)
from leonaid.application.links import LinkBuilder
from leonaid.application.errors import (
    Conflict,
    DependencyUnavailable,
    ResourceNotFound,
)
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.application.identity import (
    ROLE_LABELS,
    STATUS_LABELS,
    IdentityAdministrationService,
    PreferredSurface,
    IdentityQueryService,
    MemberDirectoryQuery,
    RoleAssignmentChange,
)
from leonaid.application.invitations import InvitationService
from leonaid.application.legal_configuration import LegalConfigurationService
from leonaid.application.operations import OperationsService, RequestDiagnostics
from leonaid.entrypoints.fastapi.prometheus import render_operations_metrics
from leonaid.application.platform import PlatformApplicationService
from leonaid.application.policies import require_system_admin
from leonaid.application.privacy import OPEN_LEGAL_DECISIONS, PrivacyService
from leonaid.application.public_orders import (
    PublicOrderDraft,
    PublicOrderPartyDraft,
    PublicOrderResult,
    PublicOrderService,
    PublicOrderTokenCodec,
    public_order_fingerprint,
)
from leonaid.application.search import (
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    SEARCH_QUERY_MAX_LENGTH,
    SEARCH_QUERY_MIN_LENGTH,
    SearchQuery,
    SearchService,
)
from leonaid.application.sessions import SessionGrant, SessionService
from leonaid.application.crm import CrmPartyKind
from leonaid.application.sponsor_matching import (
    SponsorDraft,
    SponsorMatchingService,
    SponsorMatchResult,
    SponsorMatchStatus,
    SponsorResolution,
)
from leonaid.domain.actions import (
    ALLOWED_ACTION_TRANSITIONS,
    ActionManagementState,
    ActionCapability,
    ActionGoal,
    CharityAction,
    CharityActionStatus,
)
from leonaid.domain.acquisition import (
    AcquisitionAssignment,
    ActivityChannel,
    ActivityOutcome,
    AssignmentHistoryEntry,
    AssignmentPartyKind,
    AssignmentStatus,
)
from leonaid.domain.action_templates import (
    ActionConfiguration,
    ActionTemplate,
    ActionTemplateKey,
    OfferingUnit,
)
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentPartyKind,
    CommitmentSource,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
    UnitQuantity,
)
from leonaid.domain.identity import AccountStatus, ActionRole, GlobalRole
from leonaid.domain.invitations import InvitationStatus
from leonaid.domain.invoices import (
    Invoice,
    InvoiceIssuerSnapshot,
    InvoiceProfile,
    TaxTreatment,
)
from leonaid.domain.invoice_settlements import (
    InvoiceCancellation,
    PaymentRecord,
    PaymentReversal,
)
from leonaid.domain.privacy import ConsentRecord, PrivacySubjectReport
from leonaid.domain.legal_configuration import (
    EInvoiceDecision,
    LegalConfigurationDraft,
    LegalConfigurationState,
    LegalConfigurationVersion,
    LegalForm,
    RetentionSchedule,
)
from leonaid.domain.feature_flags import FeatureFlagKey, FeatureFlagSurface
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.entrypoints.fastapi.schemas import (
    UnitQuantityResponse,
    CampaignAliasListResponse,
    CampaignAliasMutationResponse,
    CreateCampaignAliasRequest,
    UpdateCampaignAliasRequest,
    RemoveCampaignAliasRequest,
    SelectCampaignRendererRequest,
    CampaignRendererResponse,
    AcceptInvitationRequest,
    ActivateLegalConfigurationRequest,
    ActionGoalRequest,
    ActionGoalResponse,
    ActionManagementResponse,
    ActionTemplateListResponse,
    ActionTemplateSnapshotResponse,
    ActionTemplateSummaryResponse,
    ActivityFeedItemResponse,
    ActivityFeedQuery,
    ActivityFeedReadAllResponse,
    ActivityFeedResponse,
    AcquisitionActivityListResponse,
    AcquisitionActivityBoardResponse,
    AcquisitionActivityResponse,
    AcquisitionActivityWorkItemResponse,
    AcquisitionAssignmentDetailsResponse,
    AcquisitionAssignmentHandoverResponse,
    AcquisitionAssignmentHistoryResponse,
    AcquisitionAssignmentMutationResponse,
    AcquisitionAssignmentResponse,
    AcquisitionDocumentResponse,
    AcquisitionPageQuery,
    AcquisitionPartyCountResponse,
    AcquisitionPartyExportResponse,
    AcquisitionPartyListResponse,
    AcquisitionPartyResponse,
    AcquisitionSearchQuery,
    AdministratorOptionResponse,
    ApiErrorResponse,
    AssignedAcquirerResponse,
    ApproveLegalConfigurationRequest,
    AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    ACTION_CREATE_CONFLICT_RESPONSES,
    ACTIVITY_RECORD_CONFLICT_RESPONSES,
    COMMITMENT_COMPLETE_CONFLICT_RESPONSES,
    COMMITMENT_CREATE_CONFLICT_RESPONSES,
    MEMBER_ACTION_ROLE_CONFLICT_RESPONSES,
    MEMBER_GLOBAL_ROLE_CONFLICT_RESPONSES,
    MEMBER_STATUS_CONFLICT_RESPONSES,
    AUTHENTICATED_ERROR_RESPONSES,
    BeneficiaryDraftRequest,
    CompleteFreshLoginRequest,
    CompleteLoginRequest,
    ConfirmEmailChangeRequest,
    CommitmentBuyerResponse,
    CommitmentCaptureContextResponse,
    CommitmentCurrencyTotalResponse,
    CommitmentInvoiceRecipientResponse,
    CommitmentListResponse,
    CommitmentLineResponse,
    CommitmentRecordResponse,
    CancelCommitmentRequest,
    CommitmentCancellationResponse,
    CommitmentCancellationResultResponse,
    CommitmentInvoiceSummaryResponse,
    CommitmentResponse,
    ConfiguredOfferingResponse,
    CopyCharityActionRequest,
    CorrectInvitationAddressRequest,
    CreateEmailChangeRequest,
    CreateCommitmentRequest,
    CompleteCommitmentDeliveryRequest,
    CompleteCommitmentRequest,
    CreatePublicOrderRequest,
    CreateAcquisitionAssignmentRequest,
    CreateActionFromTemplateRequest,
    CreateInvitationRequest,
    CreateCharityActionRequest,
    CurrentIdentityResponse,
    InstallationResponse,
    DashboardCommitmentResponse,
    DashboardGoalResponse,
    DashboardDeliveryResponse,
    DashboardDeliveryWindowResponse,
    DashboardInvoiceResponse,
    DashboardOrderValueWeekResponse,
    DashboardMetricDefinitionResponse,
    DashboardPipelineResponse,
    DashboardReminderResponse,
    DashboardResponse,
    AcquirerDashboardResponse,
    CharityAdminDashboardResponse,
    ERROR_RESPONSES,
    EmailChangeConfirmationResponse,
    EmailChangeDispatchResponse,
    FreshLoginStatusResponse,
    FeatureFlagAdminListResponse,
    FeatureFlagAdminResponse,
    FeatureFlagEvaluationListResponse,
    FeatureFlagEvaluationResponse,
    FeatureFlagSystemStatusResponse,
    GeneratedDocumentListResponse,
    GeneratedDocumentRecordResponse,
    GeneratedDocumentReferenceResponse,
    GeneratedDocumentResponse,
    HandOverAcquisitionAssignmentRequest,
    InvitationAcceptanceResponse,
    InvitationDispatchResponse,
    InvitationListResponse,
    InvitationOptionsResponse,
    InvitationRevocationResponse,
    InvoiceContextResponse,
    InvoiceCancellationResponse,
    InvoiceCurrencyTotalResponse,
    InvoiceDeliveryResponse,
    InvoiceIssuerResponse,
    InvoiceLineResponse,
    InvoiceListResponse,
    InvoicePaymentResponse,
    InvoicePaymentReversalResponse,
    InvoiceProfileResponse,
    InvoicePaymentDetailsResponse,
    InvoiceRecordResponse,
    InvoiceResponse,
    LegalConfigurationApprovalResponse,
    LegalConfigurationStateResponse,
    LegalConfigurationValuesResponse,
    LegalConfigurationVersionResponse,
    LegalIssuerResponse,
    LegalRetentionResponse,
    CancelInvoiceRequest,
    SettleInvoiceRefundRequest,
    ChangeMemberRoleRequest,
    ChangeMemberStatusRequest,
    IssueInvoiceRequest,
    LoginDispatchResponse,
    LogoutResponse,
    MemberDirectoryMemberResponse,
    MemberDirectoryResponse,
    SearchResponse,
    SearchResultResponse,
    MemberRoleChangeResponse,
    MemberStatusChangeResponse,
    OperationalAlertResponse,
    OperationalSiteHostResponse,
    OperationalApiMetricsResponse,
    OperationalCheckResponse,
    OperationalDependencyResponse,
    OperationalFailedJobResponse,
    OperationalJobRetryResponse,
    OperationalLoginMetricsResponse,
    OperationalMonitoringResponse,
    OperationalStatusCountsResponse,
    OperationsOverviewResponse,
    PaginationQuery,
    PilotDailyDependenciesResponse,
    PilotDailyMonitoringResponse,
    PilotDailyReportResponse,
    PlatformInformationResponse,
    PlatformStatusResponse,
    PrivacyConsentResponse,
    PrivacyErasureRequest,
    PrivacyErasureResponse,
    PrivacyReferenceResponse,
    PrivacyRetentionResponse,
    PrivacySubjectReportResponse,
    PrivacyOrderDeliveryResponse,
    PrivacySubjectRequest,
    PrivacySuppressionResponse,
    PublicActionRouteResponse,
    PreferredSurfaceRequest,
    PublicCampaignListItemResponse,
    PublicCampaignListResponse,
    PublicCampaignRouteResponse,
    PublicLegalNoticeResponse,
    PublicLegalProviderResponse,
    PublicPrivacyPolicyContentResponse,
    PublicPrivacyPolicyResponse,
    PublicCharityActionResponse,
    PublicOfferingResponse,
    PublicOrderFormResponse,
    PublicOrderQuantityResponse,
    PublicOrderResultResponse,
    ReadinessResponse,
    RecordAcquisitionActivityRequest,
    RecordInvoicePaymentRequest,
    ReverseInvoicePaymentRequest,
    RecordAcquisitionActivityResponse,
    RecordedAcquisitionActivityResponse,
    RequestLoginRequest,
    SessionAuthenticationResponse,
    SessionRevocationResponse,
    BeneficiaryResponse,
    CharityActionListResponse,
    CharityActionResponse,
    CharityActionSummaryResponse,
    CharityActionConfigurationResponse,
    OrderFormConfigurationResponse,
    SetActionBeneficiariesRequest,
    SetActionCapabilitiesRequest,
    SetActionGoalRequest,
    SetActionPublicationRequest,
    SetResponsibleAdministratorsRequest,
    ResolveSponsorMatchRequest,
    RevokePrivacyConsentRequest,
    SaveLegalConfigurationDraftRequest,
    SponsorDraftRequest,
    SponsorMatchResponse,
    SponsorResolutionResponse,
    SupportRequestDiagnosticResponse,
    TransitionCharityActionRequest,
    UpdateAcquisitionAssignmentRequest,
    UpdateActivityFeedItemRequest,
    UpdateActionDetailsRequest,
    UpdateFeatureFlagRequest,
)
from leonaid.platform.base_paths import ADMIN_BASE, PWA_BASE

router = APIRouter()
# Leave time for cancellation/transaction cleanup before Astro's 12-second
# transport timeout. This includes pool/lock and CRM admission waits, not just
# individual upstream HTTP requests. It is not a body-ingress timeout.
PUBLIC_ORDER_PROCESSING_TIMEOUT_SECONDS = 8.0


def platform_service(request: Request) -> PlatformApplicationService:
    return cast(PlatformApplicationService, request.app.state.platform_service)


def operations_service(request: Request) -> OperationsService:
    return cast(OperationsService, request.app.state.operations_service)


def request_diagnostics(request: Request) -> RequestDiagnostics:
    return cast(RequestDiagnostics, request.app.state.request_diagnostics)


def public_order_tokens(request: Request) -> PublicOrderTokenCodec:
    return cast(PublicOrderTokenCodec, request.app.state.public_order_tokens)


def public_order_service(request: Request) -> PublicOrderService:
    service = cast(
        PublicOrderService | None,
        request.app.state.public_order_service,
    )
    if service is None:
        raise DependencyUnavailable(
            "public_order_crm_unavailable",
            "Das Bestellformular ist vorübergehend nicht verfügbar.",
        )
    return service


def identity_service(request: Request) -> IdentityQueryService:
    return cast(IdentityQueryService, request.app.state.identity_service)


def identity_administration_service(
    request: Request,
) -> IdentityAdministrationService:
    return cast(
        IdentityAdministrationService,
        request.app.state.identity_administration_service,
    )


def invitation_service(request: Request) -> InvitationService:
    return cast(InvitationService, request.app.state.invitation_service)


def email_change_service(request: Request) -> EmailChangeService:
    return cast(EmailChangeService, request.app.state.email_change_service)


def authentication_service(request: Request) -> SessionService:
    return cast(SessionService, request.app.state.session_service)


def acquisition_service(request: Request) -> AcquisitionPolicyService:
    service = request.app.state.acquisition_service
    if not isinstance(service, AcquisitionPolicyService):
        raise DependencyUnavailable(
            "crm_integration_not_configured",
            "Die geschützte CRM-Anbindung ist noch nicht konfiguriert.",
        )
    return service


def sponsor_matching_service(request: Request) -> SponsorMatchingService:
    service = request.app.state.sponsor_matching_service
    if not isinstance(service, SponsorMatchingService):
        raise DependencyUnavailable(
            "crm_integration_not_configured",
            "Die geschützte CRM-Anbindung ist noch nicht konfiguriert.",
        )
    return service


def assignment_management_service(request: Request) -> AssignmentManagementService:
    service = request.app.state.assignment_management_service
    if not isinstance(service, AssignmentManagementService):
        raise DependencyUnavailable(
            "crm_integration_not_configured",
            "Die geschützte CRM-Anbindung ist noch nicht konfiguriert.",
        )
    return service


def activity_management_service(request: Request) -> AcquisitionActivityService:
    service = request.app.state.activity_management_service
    if not isinstance(service, AcquisitionActivityService):
        raise DependencyUnavailable(
            "crm_integration_not_configured",
            "Die geschützte CRM-Anbindung ist noch nicht konfiguriert.",
        )
    return service


def activity_feed_service(request: Request) -> ActivityFeedService:
    return cast(ActivityFeedService, request.app.state.activity_feed_service)


def dashboard_service(request: Request) -> DashboardService:
    return cast(DashboardService, request.app.state.dashboard_service)


def action_service(request: Request) -> CharityActionService:
    return cast(CharityActionService, request.app.state.action_service)


def campaign_alias_service(request: Request) -> CampaignAliasService:
    return cast(CampaignAliasService, request.app.state.campaign_alias_service)


def search_service(request: Request) -> SearchService:
    return cast(SearchService, request.app.state.search_service)


def commitment_service(request: Request) -> CommitmentService:
    return cast(CommitmentService, request.app.state.commitment_service)


def invoice_service(request: Request) -> InvoiceService:
    return cast(InvoiceService, request.app.state.invoice_service)


def invoice_delivery_service(request: Request) -> InvoiceDeliveryService:
    return cast(
        InvoiceDeliveryService,
        request.app.state.invoice_delivery_service,
    )


def order_cancellation_service(request: Request) -> OrderCancellationService:
    return cast(
        OrderCancellationService,
        request.app.state.order_cancellation_service,
    )


def invoice_settlement_service(request: Request) -> InvoiceSettlementService:
    return cast(
        InvoiceSettlementService,
        request.app.state.invoice_settlement_service,
    )


def feature_flag_service(request: Request) -> FeatureFlagService:
    return cast(FeatureFlagService, request.app.state.feature_flag_service)


def privacy_service(request: Request) -> PrivacyService:
    return cast(PrivacyService, request.app.state.privacy_service)


def legal_configuration_service(request: Request) -> LegalConfigurationService:
    return cast(
        LegalConfigurationService,
        request.app.state.legal_configuration_service,
    )


def document_service(request: Request) -> GeneratedDocumentService:
    return cast(GeneratedDocumentService, request.app.state.document_service)


def session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def request_id(request: Request) -> str:
    return cast(str, request.state.request_id)


def device_hint(request: Request) -> str | None:
    return request.headers.get("user-agent")


def set_session_cookie(response: Response, grant: SessionGrant) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=grant.raw_token,
        expires=grant.expires_at,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value="",
        max_age=0,
        expires=datetime(1970, 1, 1, tzinfo=timezone.utc),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def acquisition_party_response(
    party: AcquisitionParty,
) -> AcquisitionPartyResponse:
    return AcquisitionPartyResponse.model_validate(party)


def unit_quantity_responses(
    quantities: Iterable[UnitQuantity],
) -> list[UnitQuantityResponse]:
    return [
        UnitQuantityResponse(unit=item.unit.value, quantity=item.quantity)
        for item in quantities
    ]


def activity_feed_item_response(
    item: ActivityFeedItem,
) -> ActivityFeedItemResponse:
    return ActivityFeedItemResponse(
        id=item.id,
        action_id=item.action_id,
        action_name=item.action_name,
        event_type="public_order_received",
        party_kind=item.party_kind,
        party_id=item.party_id,
        party_display_name=item.party_display_name,
        commitment_id=item.commitment_id,
        public_reference=item.public_reference,
        total_minor=item.total_minor,
        currency=item.currency,
        total_boxes=item.total_boxes,
        total_pieces=item.total_pieces,
        quantities=unit_quantity_responses(item.quantities),
        next_action_label=item.next_action_label,
        next_action_href=item.next_action_href,
        occurred_at=item.occurred_at,
        read_at=item.read_at,
        is_read=item.is_read,
    )


def sponsor_draft(body: SponsorDraftRequest) -> SponsorDraft:
    try:
        return SponsorDraft(
            company_name=body.company_name,
            given_name=body.given_name,
            family_name=body.family_name,
            email=body.email,
            street_line_1=body.street_line_1,
            postal_code=body.postal_code,
            city=body.city,
        )
    except ValueError as error:
        raise DomainInvariantError(
            "sponsor_draft_invalid",
            str(error),
        ) from error


def sponsor_match_response(result: SponsorMatchResult) -> SponsorMatchResponse:
    return SponsorMatchResponse.model_validate(result)


def sponsor_resolution_response(
    resolution: SponsorResolution,
) -> SponsorResolutionResponse:
    return SponsorResolutionResponse.model_validate(resolution)


def acquisition_assignment_response(
    assignment: AcquisitionAssignment,
) -> AcquisitionAssignmentResponse:
    return AcquisitionAssignmentResponse(
        id=assignment.id,
        action_id=assignment.action_id,
        party_kind=assignment.party_kind.value,
        party_id=assignment.party_id,
        acquirer_user_id=assignment.acquirer_user_id,
        acquirer_display_name=assignment.acquirer_display_name,
        status=assignment.state.status.value,
        priority=assignment.state.priority,
        next_action=assignment.state.next_action,
        due_at=assignment.state.due_at,
        revision=assignment.revision,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def acquisition_assignment_history_response(
    entry: AssignmentHistoryEntry,
) -> AcquisitionAssignmentHistoryResponse:
    return AcquisitionAssignmentHistoryResponse.model_validate(entry)


def acquisition_assignment_handover_response(
    result: AssignmentHandoverResult,
) -> AcquisitionAssignmentHandoverResponse:
    return AcquisitionAssignmentHandoverResponse(
        source=acquisition_assignment_response(result.source),
        target=acquisition_assignment_response(result.target),
        target_created=result.target_created,
    )


def acquisition_activity_work_item_response(
    item: AcquisitionWorkItem,
) -> AcquisitionActivityWorkItemResponse:
    return AcquisitionActivityWorkItemResponse(
        assignment_id=item.assignment.id,
        party_kind=item.assignment.party_kind.value,
        party_id=item.assignment.party_id,
        party_display_name=item.party_display_name,
        postal_code=item.postal_code,
        city=item.city,
        contact_name=item.contact_name,
        email=item.email,
        phone=item.phone,
        suppressed_channels=[channel.value for channel in item.suppressed_channels],
        assigned_acquirers=[
            AssignedAcquirerResponse(
                user_id=assignee.user_id,
                display_name=assignee.display_name,
            )
            for assignee in item.assigned_acquirers
        ],
        status=item.assignment.state.status.value,
        priority=item.assignment.state.priority,
        next_action=item.assignment.state.next_action,
        due_at=item.assignment.state.due_at,
        urgency=item.urgency.value,
        revision=item.assignment.revision,
    )


def privacy_consent_response(item: ConsentRecord) -> PrivacyConsentResponse:
    return PrivacyConsentResponse(
        id=item.id,
        action_id=item.action_id,
        commitment_id=item.commitment_id,
        purpose=item.purpose.value,
        channel=item.channel.value,
        text_version=item.text_version,
        source=item.source,
        evidence_kind=item.evidence_kind.value,
        legal_basis_status=item.legal_basis_status.value,
        granted_at=item.granted_at,
        revoked_at=item.revoked_at,
    )


def privacy_report_response(
    report: PrivacySubjectReport,
) -> PrivacySubjectReportResponse:
    references = (
        *report.commitments,
        *report.invoices,
        *report.documents,
        *report.assignments,
        *report.activities,
        *report.module_references,
    )
    return PrivacySubjectReportResponse(
        found=report.found,
        subject_email=report.normalized_recipient,
        crm_deletion_status="pending_manual_review",
        retention=PrivacyRetentionResponse.model_validate(report.retention),
        consents=[privacy_consent_response(item) for item in report.consents],
        suppressions=[
            PrivacySuppressionResponse(
                id=item.id,
                channel=item.channel.value,
                purpose=item.purpose.value,
                reason=item.reason,
                suppressed_at=item.suppressed_at,
            )
            for item in report.suppressions
        ],
        references=[
            PrivacyReferenceResponse.model_validate(item) for item in references
        ],
        order_deliveries=[
            PrivacyOrderDeliveryResponse.model_validate(item)
            for item in report.order_deliveries
        ],
        open_legal_decisions=list(OPEN_LEGAL_DECISIONS),
        generated_at=datetime.now(timezone.utc),
    )


def legal_configuration_version_response(
    item: LegalConfigurationVersion,
    *,
    production: bool,
) -> LegalConfigurationVersionResponse:
    values = item.configuration
    return LegalConfigurationVersionResponse(
        id=item.id,
        version=item.version,
        values=LegalConfigurationValuesResponse(
            issuer=LegalIssuerResponse.model_validate(values.issuer),
            bank_account_holder=values.bank_account_holder,
            iban=values.iban,
            bic=values.bic,
            tax_treatment=values.tax_treatment.value,
            tax_rate_basis_points=values.tax_rate_basis_points,
            tax_note=values.tax_note,
            number_prefix=values.number_prefix,
            number_width=values.number_width,
            payment_terms_days=values.payment_terms_days,
            public_order_legal_basis=values.public_order_legal_basis,
            public_order_notice_text=values.public_order_notice_text,
            consent_text_version=values.consent_text_version,
            privacy_contact_email=values.privacy_contact_email,
            retention=LegalRetentionResponse.model_validate(values.retention),
            e_invoice_decision=values.e_invoice_decision.value,
            tax_evidence_id=values.tax_evidence_id,
            privacy_evidence_id=values.privacy_evidence_id,
            e_invoice_evidence_id=values.e_invoice_evidence_id,
            activation_blockers=list(values.activation_blockers(production=production)),
            legal_form=(
                values.legal_form.value if values.legal_form is not None else None
            ),
            imprint_representatives=values.imprint_representatives,
            imprint_phone=values.imprint_phone,
            imprint_register_court=values.imprint_register_court,
            imprint_register_number=values.imprint_register_number,
            imprint_vat_id=values.imprint_vat_id,
            imprint_content_responsible_name=values.imprint_content_responsible_name,
            imprint_content_responsible_address=(
                values.imprint_content_responsible_address
            ),
            privacy_policy_text=values.privacy_policy_text,
            member_privacy_notice_text=values.member_privacy_notice_text,
        ),
        created_by_user_id=item.created_by_user_id,
        created_by_display_name=item.created_by_display_name,
        created_at=item.created_at,
    )


def legal_configuration_state_response(
    state: LegalConfigurationState,
    *,
    production: bool,
) -> LegalConfigurationStateResponse:
    return LegalConfigurationStateResponse(
        revision=state.revision,
        production=production,
        draft=(
            legal_configuration_version_response(
                state.draft,
                production=production,
            )
            if state.draft is not None
            else None
        ),
        active=(
            legal_configuration_version_response(
                state.active,
                production=production,
            )
            if state.active is not None
            else None
        ),
        draft_approval=(
            LegalConfigurationApprovalResponse(
                approved_by_user_id=state.draft_approval.approved_by_user_id,
                approved_by_display_name=(
                    state.draft_approval.approved_by_display_name
                ),
                evidence_id=state.draft_approval.evidence_id,
                approved_at=state.draft_approval.approved_at,
            )
            if state.draft_approval is not None
            else None
        ),
    )


def recorded_acquisition_activity_response(
    item: AcquisitionActivityItem,
) -> RecordedAcquisitionActivityResponse:
    activity = item.activity
    return RecordedAcquisitionActivityResponse(
        id=activity.id,
        action_id=activity.action_id,
        assignment_id=activity.assignment_id,
        party_kind=activity.party_kind.value,
        party_id=activity.party_id,
        party_display_name=item.party_display_name,
        actor_user_id=activity.actor_user_id,
        actor_display_name=activity.actor_display_name,
        channel=activity.channel.value,
        outcome=activity.outcome.value,
        note=activity.note,
        next_action=activity.next_action,
        due_at=activity.due_at,
        assignment_revision=activity.assignment_revision,
        occurred_at=activity.occurred_at,
    )


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def dashboard_pipeline_response(
    counts: PipelineCounts,
) -> DashboardPipelineResponse:
    return DashboardPipelineResponse(
        open=counts.open,
        contacted=counts.contacted,
        committed=counts.committed,
        declined=counts.declined,
        handed_over=counts.handed_over,
        total=counts.total,
    )


def dashboard_response(snapshot: DashboardSnapshot) -> DashboardResponse:
    action = quote(str(snapshot.action_id), safe="")
    definitions: list[DashboardMetricDefinitionResponse] = []

    acquirer_response: AcquirerDashboardResponse | None = None
    if snapshot.acquirer is not None:
        acquirer = snapshot.acquirer
        definitions.extend(
            (
                DashboardMetricDefinitionResponse(
                    key="acquirer.pipeline",
                    label="Meine Pipeline",
                    description=(
                        "Alle Sponsor-Zuordnungen dieser Aktion, die dem "
                        "eigenen Konto zugeordnet sind."
                    ),
                    href=f"{PWA_BASE}sponsors?action={action}",
                ),
                DashboardMetricDefinitionResponse(
                    key="acquirer.reminders",
                    label="Meine Wiedervorlagen",
                    description=(
                        "Offene nächste Schritte nach lokalem Kalendertag; "
                        "übergebene Zuordnungen zählen nicht mit."
                    ),
                    href=f"{PWA_BASE}activities?view=contacts&action={action}",
                ),
                DashboardMetricDefinitionResponse(
                    key="acquirer.activities",
                    label="Meine Aktivitäten",
                    description=(
                        "Selbst dokumentierte Kontakte in dieser Charity-Aktion."
                    ),
                    href=f"{PWA_BASE}activities?view=contacts&action={action}",
                ),
            )
        )
        acquirer_response = AcquirerDashboardResponse(
            pipeline=dashboard_pipeline_response(acquirer.pipeline),
            reminders=DashboardReminderResponse(
                overdue=acquirer.reminders.overdue,
                today=acquirer.reminders.today,
                upcoming=acquirer.reminders.upcoming,
                unscheduled=acquirer.reminders.unscheduled,
                total=acquirer.reminders.total,
            ),
            activity_count=acquirer.activity_count,
        )

    admin_response: CharityAdminDashboardResponse | None = None
    if snapshot.charity_admin is not None:
        admin = snapshot.charity_admin
        definitions.extend(
            (
                DashboardMetricDefinitionResponse(
                    key="admin.pipeline",
                    label="Aktionsweite Pipeline",
                    description=(
                        "Alle Sponsor-Zuordnungen der Charity-Aktion, auch bei "
                        "mehrfach betreuten Sponsoren."
                    ),
                    href=f"{ADMIN_BASE}acquisition?action={action}",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.commitments",
                    label="Bestellungen",
                    description=(
                        "Alle nicht stornierten Bestellungen; Betrag und Mengen "
                        "verwenden die gespeicherten Bestellpositionen."
                    ),
                    href=f"{ADMIN_BASE}orders?action={action}&status=all",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.invoiced",
                    label="Fakturierter Betrag",
                    description=(
                        "Summe ausgestellter, versendeter und bezahlter "
                        "Rechnungen; Stornos zählen nicht mit."
                    ),
                    href=f"{ADMIN_BASE}invoices?action={action}&status=all",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.open_receivables",
                    label="Offene Posten",
                    description=(
                        "Offener Restbetrag aller Rechnungen: Bruttobetrag "
                        "abzüglich erfasster Zahlungseingänge. Bezahlte, "
                        "überzahlte und stornierte Rechnungen zählen nicht mit."
                    ),
                    href=f"{ADMIN_BASE}invoices?action={action}&status=open",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.overdue",
                    label="Überfällige Rechnungen",
                    description=(
                        "Rechnungen mit Restbetrag, deren Fälligkeitstag nach "
                        "Kalendertag des Clubs vorbei ist; Summe der Restbeträge."
                    ),
                    href=f"{ADMIN_BASE}invoices?action={action}&view=overdue",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.delivery_failed",
                    label="Versand fehlgeschlagen",
                    description=(
                        "Nicht stornierte Rechnungen, deren letzter Versand "
                        "endgültig gescheitert ist."
                    ),
                    href=f"{ADMIN_BASE}invoices?action={action}&view=all&f.sent=failed",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.to_invoice",
                    label="Rechnung erstellen",
                    description="Bestätigte Bestellungen, noch ohne Rechnung.",
                    href=f"{ADMIN_BASE}orders?action={action}&view=all&f.status=confirmed",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.order_value_weeks",
                    label="Bestellwert pro Woche",
                    description=(
                        "Summe der nicht stornierten Bestellungen nach "
                        "Eingangswoche (Montag bis Sonntag, Zeit des Clubs)."
                    ),
                    href=f"{ADMIN_BASE}orders?action={action}&view=all",
                ),
                DashboardMetricDefinitionResponse(
                    key="admin.delivery",
                    label="Lieferfenster",
                    description=(
                        "Lieferfenster ab heute und die verbindlichen "
                        "Bestellungen darin (ohne Entwürfe und Stornos)."
                    ),
                    href=f"{ADMIN_BASE}delivery?action={action}",
                ),
            )
        )
        admin_response = CharityAdminDashboardResponse(
            pipeline=dashboard_pipeline_response(admin.pipeline),
            commitments=DashboardCommitmentResponse(
                draft=admin.commitments.draft,
                review_ready=admin.commitments.review_ready,
                confirmed=admin.commitments.confirmed,
                invoiced=admin.commitments.invoiced,
                cancelled=admin.commitments.cancelled,
                total=admin.commitments.total,
                active_total=admin.commitments.active_total,
                active_total_minor=admin.commitments.active_total_minor,
                total_boxes=admin.commitments.total_boxes,
                total_pieces=admin.commitments.total_pieces,
                quantities=unit_quantity_responses(admin.commitments.quantities),
                currency=snapshot.currency,
            ),
            invoices=DashboardInvoiceResponse(
                issued=admin.invoices.issued,
                sent=admin.invoices.sent,
                open=admin.invoices.open,
                paid=admin.invoices.paid,
                cancelled=admin.invoices.cancelled,
                total=admin.invoices.total,
                invoiced_amount_minor=admin.invoices.invoiced_amount_minor,
                open_amount_minor=admin.invoices.open_amount_minor,
                overdue=admin.invoices.overdue,
                overdue_amount_minor=admin.invoices.overdue_amount_minor,
                delivery_failed=admin.invoices.delivery_failed,
                currency=snapshot.currency,
            ),
            order_value_weeks=[
                DashboardOrderValueWeekResponse(
                    week_start=week.week_start,
                    iso_week=week.iso_week,
                    total_minor=week.total_minor,
                )
                for week in admin.order_value_weeks
            ],
            delivery=DashboardDeliveryResponse(
                enabled=admin.delivery.enabled,
                windows=[
                    DashboardDeliveryWindowResponse(
                        id=window.id,
                        starts_at=window.starts_at,
                        ends_at=window.ends_at,
                        commitments=window.commitments,
                        quantities=unit_quantity_responses(window.quantities),
                        fully_booked=window.fully_booked,
                    )
                    for window in admin.delivery.windows
                ],
            ),
        )

    return DashboardResponse(
        action_id=snapshot.action_id,
        action_name=snapshot.action_name,
        beneficiaries=list(snapshot.beneficiaries),
        goal=DashboardGoalResponse(
            configured=snapshot.goal.configured,
            actual_value=decimal_text(snapshot.goal.actual_value),
            target_value=(
                decimal_text(snapshot.goal.target_value)
                if snapshot.goal.target_value is not None
                else None
            ),
            unit=snapshot.goal.unit,
            currency=snapshot.goal.currency,
            progress_basis_points=snapshot.goal.progress_basis_points,
        ),
        acquirer=acquirer_response,
        charity_admin=admin_response,
        metric_definitions=definitions,
        generated_at=snapshot.generated_at,
    )


def charity_action_response(action: CharityAction) -> CharityActionResponse:
    return CharityActionResponse(
        is_published=action.is_published_at(datetime.now(timezone.utc)),
        id=action.id,
        carrier_name=action.carrier_name,
        name=action.name,
        purpose=action.purpose,
        status=action.status.value,
        starts_on=action.starts_on,
        ends_on=action.ends_on,
        publication_starts_at=(
            action.publication_window.starts_at
            if action.publication_window is not None
            else None
        ),
        publication_ends_at=(
            action.publication_window.ends_at
            if action.publication_window is not None
            else None
        ),
        archive_slug=action.archive_slug,
        revision=action.revision,
        capabilities=sorted(
            (item.value for item in action.capabilities),
        ),
        beneficiaries=[
            BeneficiaryResponse(
                id=item.id,
                organization_name=item.organization_name,
                public_description=item.public_description,
                sort_order=item.sort_order,
            )
            for item in action.beneficiaries
        ],
        goal=ActionGoalResponse(
            goal_value=(
                decimal_text(action.goal.goal_value)
                if action.goal.goal_value is not None
                else None
            ),
            actual_value=decimal_text(action.goal.actual_value),
            unit=action.goal.unit,
            currency=action.goal.currency,
        ),
        presentation_theme=action.presentation_theme,
    )


def action_management_response(
    state: ActionManagementState,
) -> ActionManagementResponse:
    return ActionManagementResponse(
        action=charity_action_response(state.action),
        public_alias=(
            state.public_alias.value if state.public_alias is not None else None
        ),
        administrator_options=[
            AdministratorOptionResponse(
                user_id=item.user_id,
                display_name=item.display_name,
                email=item.email,
                is_available=item.is_available,
                is_responsible=item.is_responsible,
            )
            for item in state.administrator_options
        ],
        allowed_transitions=[
            item.value
            for item in sorted(
                ALLOWED_ACTION_TRANSITIONS[state.action.status],
                key=lambda value: value.value,
            )
        ],
    )


async def campaign_host_url(
    request: Request, action: CharityAction | None, archive_slug: str | None
) -> str | None:
    """The action's canonical URL on a campaign host, or None (§7.7.3)."""
    directory = cast(CampaignHostUrls, request.app.state.site_directory)
    if action is not None:
        return (await directory.campaign_host_urls([action.id])).get(action.id)
    if archive_slug:
        return await directory.campaign_host_url_for_slug(archive_slug)
    return None


def public_action_route_response(
    route: PublicActionRoute,
    *,
    access_token: str | None = None,
    legal_configuration: LegalConfigurationVersion | None = None,
    delivery: DeliveryConfiguration | None = None,
) -> PublicActionRouteResponse:
    if route.route_kind.value not in {"alias", "archive"}:
        raise ValueError(
            "Dieser öffentliche Routentyp benötigt einen eigenen Transportvertrag."
        )
    action = route.action
    submissions_allowed = route.submissions_allowed and legal_configuration is not None
    return PublicActionRouteResponse(
        route_kind="alias" if route.route_kind.value == "alias" else "archive",
        route_value=route.route_value,
        route_path=route.route_path,
        canonical_path=route.canonical_path,
        redirect_path=route.redirect_path,
        availability=route.availability.value,
        submissions_allowed=submissions_allowed,
        action=(
            PublicCharityActionResponse(
                id=action.id,
                carrier_name=action.carrier_name,
                name=action.name,
                purpose=action.purpose,
                starts_on=action.starts_on,
                ends_on=action.ends_on,
                archive_slug=action.archive_slug,
                beneficiaries=[
                    BeneficiaryResponse(
                        id=item.id,
                        organization_name=item.organization_name,
                        public_description=item.public_description,
                        sort_order=item.sort_order,
                    )
                    for item in action.beneficiaries
                ],
                goal=ActionGoalResponse(
                    goal_value=(
                        decimal_text(action.goal.goal_value)
                        if action.goal.goal_value is not None
                        else None
                    ),
                    actual_value=decimal_text(action.goal.actual_value),
                    unit=action.goal.unit,
                    currency=action.goal.currency,
                ),
                offerings=[
                    PublicOfferingResponse(
                        id=item.id,
                        code=item.definition.code,
                        name=item.definition.name,
                        unit=item.definition.unit.value,
                        pieces_per_unit=item.definition.pieces_per_unit,
                        unit_price_minor=item.definition.unit_price_minor,
                        currency=item.definition.currency,
                    )
                    for item in route.offerings
                ],
                order_form=(
                    PublicOrderFormResponse(
                        delivery_configuration=delivery_configuration_response(
                            delivery, available_only=True
                        )
                        if delivery
                        else None,
                        form_key=route.order_form.configuration.form_key,
                        title=route.order_form.configuration.title,
                        introduction=route.order_form.configuration.introduction,
                        submit_label=route.order_form.configuration.submit_label,
                        require_company_name=(
                            route.order_form.configuration.require_company_name
                        ),
                        require_contact_name=(
                            route.order_form.configuration.require_contact_name
                        ),
                        require_email=route.order_form.configuration.require_email,
                        require_phone=route.order_form.configuration.require_phone,
                        # Delivery data is only collected for delivery actions.
                        require_delivery_address=(
                            route.order_form.configuration.require_delivery_address
                            and ActionCapability.DELIVERY in action.capabilities
                        ),
                        require_billing_address=(
                            route.order_form.configuration.require_billing_address
                        ),
                        allow_message=route.order_form.configuration.allow_message,
                        access_token=access_token,
                        privacy_notice_version=(
                            legal_configuration.configuration.consent_text_version
                        ),
                        privacy_notice_text=(
                            legal_configuration.configuration.public_order_notice_text
                        ),
                        legal_basis=(
                            legal_configuration.configuration.public_order_legal_basis
                        ),
                        privacy_contact_email=(
                            legal_configuration.configuration.privacy_contact_email
                        ),
                    )
                    if (
                        route.order_form is not None
                        and access_token is not None
                        and legal_configuration is not None
                    )
                    else None
                ),
                capabilities=sorted(item.value for item in action.capabilities),
                presentation_theme=action.presentation_theme,
            )
            if action is not None
            else None
        ),
    )


def action_template_summary_response(
    template: ActionTemplate,
) -> ActionTemplateSummaryResponse:
    return ActionTemplateSummaryResponse(
        key=template.key.value,
        version=template.version,
        display_name=template.display_name,
        description=template.description,
        capabilities=sorted(item.value for item in template.capabilities),
        offering_count=len(template.offerings),
        has_order_form=template.order_form is not None,
        presentation_theme=template.presentation_theme,
    )


def charity_action_configuration_response(
    action: CharityAction,
    configuration: ActionConfiguration,
) -> CharityActionConfigurationResponse:
    snapshot = configuration.snapshot
    return CharityActionConfigurationResponse(
        action=charity_action_response(action),
        template=ActionTemplateSnapshotResponse(
            key=snapshot.template_key.value,
            version=snapshot.template_version,
            display_name=snapshot.display_name,
            copied_from_action_id=snapshot.copied_from_action_id,
        ),
        offerings=[
            ConfiguredOfferingResponse(
                id=item.id,
                code=item.definition.code,
                name=item.definition.name,
                status=item.definition.status.value,
                unit=item.definition.unit.value,
                allowed_quantity_units=sorted(
                    value.value for value in item.allowed_quantity_units
                ),
                pieces_per_unit=item.definition.pieces_per_unit,
                unit_price_minor=item.definition.unit_price_minor,
                currency=item.definition.currency,
                available_from=item.available_from,
                available_until=item.available_until,
            )
            for item in configuration.offerings
        ],
        order_form=(
            OrderFormConfigurationResponse(
                id=configuration.order_form.id,
                form_key=configuration.order_form.configuration.form_key,
                title=configuration.order_form.configuration.title,
                introduction=(configuration.order_form.configuration.introduction),
                submit_label=configuration.order_form.configuration.submit_label,
                require_company_name=(
                    configuration.order_form.configuration.require_company_name
                ),
                require_contact_name=(
                    configuration.order_form.configuration.require_contact_name
                ),
                require_email=(configuration.order_form.configuration.require_email),
                require_phone=(configuration.order_form.configuration.require_phone),
                require_delivery_address=(
                    configuration.order_form.configuration.require_delivery_address
                ),
                require_billing_address=(
                    configuration.order_form.configuration.require_billing_address
                ),
                allow_message=(configuration.order_form.configuration.allow_message),
            )
            if configuration.order_form is not None
            else None
        ),
    )


def commitment_response(commitment: Commitment) -> CommitmentResponse:
    recipient = commitment.invoice_recipient
    return CommitmentResponse(
        delivery_completion_version=delivery_completion_version(commitment),
        delivery_recipient=PublicOrderDeliveryRecipientRequest.model_validate(
            commitment.delivery_recipient
        )
        if commitment.delivery_recipient
        else None,
        delivery_window_id=commitment.delivery_window_id,
        delivery_window_snapshot=commitment.delivery_window_snapshot,
        delivery_contact=DeliveryContactRequest.model_validate(
            commitment.delivery_contact
        )
        if commitment.delivery_contact
        else None,
        id=commitment.id,
        action_id=commitment.action_id,
        source=commitment.source.value,
        status=commitment.status.value,
        buyer=CommitmentBuyerResponse(
            party_kind=commitment.buyer.party_kind.value,
            twenty_id=commitment.buyer.twenty_id,
            display_name=commitment.buyer.display_name,
            email=commitment.buyer.email,
        ),
        invoice_recipient=(
            CommitmentInvoiceRecipientResponse(
                recipient_name=recipient.recipient_name,
                street_line_1=recipient.street_line_1,
                postal_code=recipient.postal_code,
                city=recipient.city,
                country_code=recipient.country_code,
                email=recipient.email,
            )
            if recipient is not None
            else None
        ),
        lines=[
            CommitmentLineResponse(
                id=line.id,
                offering_id=line.offering_id,
                description=line.description_snapshot,
                quantity=line.quantity,
                unit=line.unit_snapshot.value,
                pieces_per_unit=line.pieces_per_unit_snapshot,
                piece_count=line.piece_count,
                box_count=line.box_count,
                unit_price_minor=line.unit_price.amount_minor,
                line_total_minor=line.line_total.amount_minor,
                currency=line.line_total.currency,
            )
            for line in commitment.lines
        ],
        total_minor=commitment.total.amount_minor,
        currency=commitment.total.currency,
        total_pieces=commitment.total_pieces,
        total_boxes=commitment.total_boxes,
        quantities=unit_quantity_responses(commitment.quantities),
        replayed=commitment.replayed,
        captured_at=commitment.captured_at,
    )


def commitment_capture_context_response(
    context: CommitmentCaptureContext,
) -> CommitmentCaptureContextResponse:
    return CommitmentCaptureContextResponse(
        delivery_configuration=delivery_configuration_response(
            context.delivery_configuration, available_only=True
        )
        if context.delivery_configuration
        else None,
        action_id=context.action_id,
        action_name=context.action_name,
        offerings=[
            ConfiguredOfferingResponse(
                id=offering.id,
                code=offering.code,
                name=offering.name,
                status=offering.status.value,
                unit=offering.pricing_unit.value,
                allowed_quantity_units=sorted(
                    unit.value for unit in offering.allowed_quantity_units
                ),
                pieces_per_unit=offering.pieces_per_unit,
                unit_price_minor=offering.unit_price.amount_minor,
                currency=offering.unit_price.currency,
                available_from=offering.available_from,
                available_until=offering.available_until,
            )
            for offering in context.offerings
        ],
    )


def commitment_record_response(
    record: CommitmentRecord,
) -> CommitmentRecordResponse:
    invoice = record.invoice
    return CommitmentRecordResponse(
        commitment=commitment_response(record.commitment),
        created_at=record.created_at,
        captured_by_display_name=record.captured_by_display_name,
        cancellation=(
            commitment_cancellation_response(record.cancellation)
            if record.cancellation is not None
            else None
        ),
        invoice=(
            CommitmentInvoiceSummaryResponse(
                id=invoice.id,
                number=invoice.number,
                status=invoice.status.value,
                payment_recorded=invoice.payment_recorded,
                paid_minor=invoice.paid_minor,
            )
            if invoice is not None
            else None
        ),
        delivered=record.delivered,
    )


def commitment_cancellation_response(
    cancellation: OrderCancellation,
) -> CommitmentCancellationResponse:
    return CommitmentCancellationResponse(
        id=cancellation.id,
        previous_status=cast(
            Literal["draft", "review_ready", "confirmed", "invoiced"],
            cancellation.previous_status.value,
        ),
        reason=cancellation.reason,
        note=cancellation.note,
        requested_by_display_name=cancellation.requested_by_display_name,
        requested_at=cancellation.requested_at,
        invoice_cancellation_id=cancellation.invoice_cancellation_id,
        invoice_number=cancellation.invoice_number,
        invoice_cancellation_number=cancellation.invoice_cancellation_number,
    )


def commitment_list_response(value: CommitmentList) -> CommitmentListResponse:
    return CommitmentListResponse(
        action_id=value.action_id,
        items=[commitment_record_response(record) for record in value.records],
        currency_totals=[
            CommitmentCurrencyTotalResponse(
                currency=item.currency,
                total_minor=item.total.amount_minor,
            )
            for item in value.currency_totals
        ],
        total_pieces=value.total_pieces,
        total_boxes=value.total_boxes,
        quantities=unit_quantity_responses(value.quantities),
    )


def invoice_issuer_response(profile: InvoiceProfile) -> InvoiceIssuerResponse:
    issuer = profile.issuer
    return InvoiceIssuerResponse(
        legal_name=issuer.legal_name,
        street_line_1=issuer.street_line_1,
        postal_code=issuer.postal_code,
        city=issuer.city,
        country_code=issuer.country_code,
        tax_identifier=issuer.tax_identifier,
        email=issuer.email,
    )


def invoice_profile_response(profile: InvoiceProfile) -> InvoiceProfileResponse:
    return InvoiceProfileResponse(
        legal_configuration_version_id=profile.legal_configuration_version_id,
        issuer=invoice_issuer_response(profile),
        payment_details=(
            InvoicePaymentDetailsResponse(
                account_holder=profile.payment_details.account_holder,
                iban=profile.payment_details.iban,
                bic=profile.payment_details.bic,
            )
            if profile.payment_details is not None
            else None
        ),
        tax_treatment=profile.tax_treatment.value,
        tax_rate_basis_points=profile.tax_rate_basis_points,
        tax_note=profile.tax_note,
        next_invoice_number=profile.next_invoice_number,
        payment_terms_days=profile.payment_terms_days,
        confirmed_at=profile.confirmed_at,
        ready_to_issue=profile.ready_to_issue,
    )


def invoice_response(invoice: Invoice) -> InvoiceResponse:
    recipient = invoice.recipient
    issuer = invoice.issuer
    return InvoiceResponse(
        id=invoice.id,
        action_id=invoice.action_id,
        commitment_id=invoice.commitment_id,
        number=invoice.number,
        status=invoice.status.value,
        issued_at=invoice.issued_at,
        service_on=invoice.service_on,
        due_on=invoice.due_on,
        issuer=InvoiceIssuerResponse(
            legal_name=issuer.legal_name,
            street_line_1=issuer.street_line_1,
            postal_code=issuer.postal_code,
            city=issuer.city,
            country_code=issuer.country_code,
            tax_identifier=issuer.tax_identifier,
            email=issuer.email,
        ),
        payment_details=InvoicePaymentDetailsResponse(
            account_holder=invoice.payment_details.account_holder,
            iban=invoice.payment_details.iban,
            bic=invoice.payment_details.bic,
        ),
        recipient=CommitmentInvoiceRecipientResponse(
            recipient_name=recipient.recipient_name,
            street_line_1=recipient.street_line_1,
            postal_code=recipient.postal_code,
            city=recipient.city,
            country_code=recipient.country_code,
            email=recipient.email,
        ),
        lines=[
            InvoiceLineResponse(
                description=line.description,
                quantity=line.quantity,
                unit=line.unit.value,
                unit_price_gross_minor=line.unit_price_gross.amount_minor,
                tax_rate_basis_points=line.tax_rate_basis_points,
                net_minor=line.net.amount_minor,
                tax_minor=line.tax.amount_minor,
                gross_minor=line.gross.amount_minor,
                currency=line.gross.currency,
            )
            for line in invoice.lines
        ],
        tax_treatment=invoice.tax_treatment.value,
        tax_note=invoice.tax_note,
        net_minor=invoice.net.amount_minor,
        tax_minor=invoice.tax.amount_minor,
        gross_minor=invoice.gross.amount_minor,
        currency=invoice.gross.currency,
        payment_reference=invoice.payment_reference,
        approved_by_user_id=invoice.approved_by_user_id,
        replayed=invoice.replayed,
    )


def invoice_context_response(context: InvoiceContext) -> InvoiceContextResponse:
    return InvoiceContextResponse(
        action_id=context.action_id,
        action_name=context.action_name,
        starts_on=context.starts_on,
        ends_on=context.ends_on,
        profile=(
            invoice_profile_response(context.profile)
            if context.profile is not None
            else None
        ),
        may_issue=context.may_issue,
        may_manage_settlements=context.may_manage_settlements,
    )


def invoice_record_response(record: InvoiceRecord) -> InvoiceRecordResponse:
    balance = record.balance
    return InvoiceRecordResponse(
        invoice=invoice_response(record.invoice),
        buyer_display_name=record.buyer_display_name,
        open_minor=record.open_amount.amount_minor,
        payments=[invoice_payment_response(item) for item in record.payments],
        paid_minor=balance.paid.amount_minor,
        overpaid_minor=balance.overpaid_amount.amount_minor,
        settlement_status=balance.status.value,
        settlement_version=record.settlement_version,
        payment=(
            invoice_payment_response(record.payment)
            if record.payment is not None
            else None
        ),
        cancellation=(
            invoice_cancellation_response(record.cancellation)
            if record.cancellation is not None
            else None
        ),
        deliveries=[
            invoice_delivery_response(delivery) for delivery in record.deliveries
        ],
        cancellation_deliveries=[
            invoice_delivery_response(delivery)
            for delivery in record.cancellation_deliveries
        ],
    )


def invoice_delivery_response(
    delivery: InvoiceDelivery,
) -> InvoiceDeliveryResponse:
    return InvoiceDeliveryResponse(
        id=delivery.id,
        action_id=delivery.action_id,
        invoice_id=delivery.invoice_id,
        generated_document_id=delivery.generated_document_id,
        recipient_email=delivery.recipient_email,
        subject=delivery.subject,
        status=delivery.status.value,
        message_id=delivery.message_id,
        attempts=delivery.attempts,
        last_error_code=delivery.last_error_code,
        last_error_detail=delivery.last_error_detail,
        requested_at=delivery.requested_at,
        sent_at=delivery.sent_at,
        can_retry=delivery.can_retry,
        kind=delivery.kind.value,
    )


def invoice_payment_response(payment: PaymentRecord) -> InvoicePaymentResponse:
    return InvoicePaymentResponse(
        id=payment.id,
        action_id=payment.action_id,
        invoice_id=payment.invoice_id,
        amount_minor=payment.amount.amount_minor,
        currency=payment.amount.currency,
        received_on=payment.received_on,
        reference=payment.reference,
        recorded_by_user_id=payment.recorded_by_user_id,
        recorded_by_display_name=payment.recorded_by_display_name,
        recorded_at=payment.recorded_at,
        replayed=payment.replayed,
        note=payment.note,
        reversal=(
            invoice_payment_reversal_response(payment.reversal)
            if payment.reversal is not None
            else None
        ),
    )


def invoice_payment_reversal_response(
    reversal: PaymentReversal,
) -> InvoicePaymentReversalResponse:
    return InvoicePaymentReversalResponse(
        id=reversal.id,
        action_id=reversal.action_id,
        invoice_id=reversal.invoice_id,
        payment_id=reversal.payment_id,
        reason=reversal.reason,
        reversed_by_user_id=reversal.reversed_by_user_id,
        reversed_by_display_name=reversal.reversed_by_display_name,
        reversed_at=reversal.reversed_at,
        replayed=reversal.replayed,
    )


def invoice_cancellation_response(
    cancellation: InvoiceCancellation,
) -> InvoiceCancellationResponse:
    refund = cancellation.refund
    return InvoiceCancellationResponse(
        id=cancellation.id,
        action_id=cancellation.action_id,
        invoice_id=cancellation.invoice_id,
        original_status=cast(
            Literal["issued", "sent", "paid"],
            cancellation.original_status.value,
        ),
        reason=cancellation.reason,
        requested_by_user_id=cancellation.requested_by_user_id,
        requested_by_display_name=cancellation.requested_by_display_name,
        requested_at=cancellation.requested_at,
        replayed=cancellation.replayed,
        number=cancellation.number,
        issued_on=cancellation.issued_on,
        received_minor=(
            cancellation.received.amount_minor
            if cancellation.received is not None
            else 0
        ),
        refund_open=cancellation.refund_open,
        refund_settled_on=refund.settled_on if refund is not None else None,
        refund_note=refund.note if refund is not None else None,
        refund_settled_by_display_name=(
            refund.settled_by_display_name if refund is not None else None
        ),
        refund_settled_at=refund.settled_at if refund is not None else None,
    )


def invoice_list_response(value: InvoiceList) -> InvoiceListResponse:
    return InvoiceListResponse(
        action_id=value.action_id,
        items=[invoice_record_response(record) for record in value.records],
        currency_totals=[
            InvoiceCurrencyTotalResponse(
                currency=item.currency,
                gross_minor=item.gross_total.amount_minor,
                open_minor=item.open_total.amount_minor,
            )
            for item in value.currency_totals
        ],
    )


def generated_document_record_response(
    record: GeneratedDocumentRecord,
) -> GeneratedDocumentRecordResponse:
    document = record.document
    return GeneratedDocumentRecordResponse(
        document=GeneratedDocumentResponse(
            id=document.id,
            action_id=document.action_id,
            commitment_id=document.commitment_id,
            invoice_id=document.invoice_id,
            twenty_company_id=document.twenty_company_id,
            twenty_person_id=document.twenty_person_id,
            document_type=document.document_type.value,
            media_type=document.media_type,
            filename=document.filename,
            size_bytes=document.size_bytes,
            render_version=document.render_version,
            version=document.version,
            status=document.status.value,
            created_at=document.created_at,
            available_at=document.available_at,
            sent_at=document.sent_at,
        ),
        invoice_number=record.invoice_number,
        document_number=record.document_number,
        buyer_display_name=record.buyer_display_name,
    )


def generated_document_list_response(
    value: GeneratedDocumentList,
) -> GeneratedDocumentListResponse:
    return GeneratedDocumentListResponse(
        action_id=value.action_id,
        reference=GeneratedDocumentReferenceResponse(
            kind=value.reference.kind.value,
            id=value.reference.id,
        ),
        items=[generated_document_record_response(record) for record in value.records],
    )


def commitment_draft(body: CreateCommitmentRequest) -> CommitmentDraft:
    recipient = body.invoice_recipient
    return CommitmentDraft(
        allow_full_window=body.allow_full_window,
        captured_at=body.captured_at,
        delivery_window_id=body.delivery_window_id,
        delivery_contact=DeliveryContactSnapshot(**body.delivery_contact.model_dump())
        if body.delivery_contact
        else None,
        delivery_recipient=DeliveryRecipientSnapshot(
            **body.delivery_recipient.model_dump()
        )
        if body.delivery_recipient
        else None,
        buyer=BuyerSnapshot(
            party_kind=CommitmentPartyKind(body.buyer.party_kind),
            twenty_id=body.buyer.twenty_id,
            display_name=body.buyer.display_name,
            email=body.buyer.email,
        ),
        invoice_recipient=(
            InvoiceRecipientSnapshot(
                recipient_name=recipient.recipient_name,
                street_line_1=recipient.street_line_1,
                postal_code=recipient.postal_code,
                city=recipient.city,
                country_code=recipient.country_code,
                email=recipient.email,
            )
            if recipient is not None
            else None
        ),
        lines=tuple(
            CommitmentLineDraft(
                offering_id=line.offering_id,
                quantity=line.quantity,
                unit=OfferingUnit(line.unit),
                quoted_unit_price_minor=line.quoted_unit_price_minor,
            )
            for line in body.lines
        ),
    )


def goal_from_request(body: ActionGoalRequest) -> ActionGoal:
    return ActionGoal(
        goal_value=Decimal(body.goal_value) if body.goal_value is not None else None,
        actual_value=Decimal(body.actual_value),
        unit=body.unit.strip() if body.unit is not None else None,
        currency=body.currency,
    )


def beneficiary_drafts(
    values: list[BeneficiaryDraftRequest],
) -> tuple[BeneficiaryDraft, ...]:
    return tuple(
        BeneficiaryDraft(
            organization_name=item.organization_name,
            public_description=item.public_description,
        )
        for item in values
    )


@router.get(
    "/health/live",
    operation_id="getHealthLive",
    response_model=PlatformStatusResponse,
    responses=ERROR_RESPONSES,
    tags=["platform"],
)
async def live(request: Request) -> PlatformStatusResponse:
    return PlatformStatusResponse.model_validate(platform_service(request).live())


@router.get(
    "/health/ready",
    operation_id="getHealthReady",
    response_model=ReadinessResponse,
    responses={**ERROR_RESPONSES, 503: {"model": ReadinessResponse}},
    tags=["platform"],
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    result = await platform_service(request).readiness()
    if result.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse.model_validate(result)


@router.get(
    "/api/v1/platform",
    operation_id="getPlatformInformation",
    response_model=PlatformInformationResponse,
    responses=ERROR_RESPONSES,
    tags=["platform"],
)
async def information(request: Request) -> PlatformInformationResponse:
    return PlatformInformationResponse.model_validate(
        platform_service(request).information()
    )


def public_legal_provider(
    configuration: LegalConfigurationDraft,
) -> PublicLegalProviderResponse:
    """The Impressum facts of a configuration; nothing tax-, bank- or audit-related."""
    issuer = configuration.issuer
    return PublicLegalProviderResponse(
        legal_name=issuer.legal_name,
        street_line_1=issuer.street_line_1,
        postal_code=issuer.postal_code,
        city=issuer.city,
        country_code=issuer.country_code,
        email=issuer.email,
        phone=configuration.imprint_phone,
        representatives=configuration.imprint_representatives,
        register_court=configuration.imprint_register_court,
        register_number=configuration.imprint_register_number,
        register_label=configuration.register_label(),
        vat_id=configuration.imprint_vat_id,
        content_responsible_name=configuration.imprint_content_responsible_name,
        content_responsible_address=(configuration.imprint_content_responsible_address),
    )


@router.get(
    "/api/v1/public/legal-notice",
    operation_id="getPublicLegalNotice",
    response_model=PublicLegalNoticeResponse,
    responses=ERROR_RESPONSES,
    tags=["public-actions"],
)
async def get_public_legal_notice(
    request: Request,
    response: Response,
) -> PublicLegalNoticeResponse:
    """Impressum provider of the installation (one per club, all hosts).

    Only the Impressum facts (§ 5 DDG, § 18 Abs. 2 MStV) leave the active
    legal configuration; the invoice tax identifier, bank and evidence data
    stay internal.
    """
    configuration = await legal_configuration_service(request).active_configuration()
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    if configuration is None:
        return PublicLegalNoticeResponse(provider=None)
    return PublicLegalNoticeResponse(
        provider=public_legal_provider(configuration.configuration)
    )


@router.get(
    "/api/v1/public/privacy-policy",
    operation_id="getPublicPrivacyPolicy",
    response_model=PublicPrivacyPolicyResponse,
    responses=ERROR_RESPONSES,
    tags=["public-actions"],
)
async def get_public_privacy_policy(
    request: Request,
    response: Response,
) -> PublicPrivacyPolicyResponse:
    """Privacy page of the installation (/datenschutz, one per club, all hosts)."""
    configuration = await legal_configuration_service(request).active_configuration()
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    if configuration is None:
        return PublicPrivacyPolicyResponse(policy=None)
    values = configuration.configuration
    return PublicPrivacyPolicyResponse(
        policy=PublicPrivacyPolicyContentResponse(
            version=configuration.version,
            controller=public_legal_provider(values),
            privacy_contact_email=values.privacy_contact_email,
            policy_text=values.privacy_policy_text,
            member_notice_text=values.member_privacy_notice_text,
            order_notice_text=values.public_order_notice_text,
            order_legal_basis=values.public_order_legal_basis,
        )
    )


@router.get(
    "/api/v1/public/actions/alias/{public_alias}",
    operation_id="resolvePublicActionAlias",
    response_model=PublicActionRouteResponse,
    responses=ERROR_RESPONSES,
    tags=["public-actions"],
)
async def resolve_public_action_alias(
    public_alias: str,
    request: Request,
    response: Response,
) -> PublicActionRouteResponse:
    route = await action_service(request).resolve_public_alias(public_alias)
    legal_configuration = (
        await legal_configuration_service(request).active_configuration()
        if route.submissions_allowed
        else None
    )
    submissions_allowed = route.submissions_allowed and legal_configuration is not None
    response.headers["Cache-Control"] = (
        "private, no-store"
        if submissions_allowed
        else "public, max-age=15, stale-while-revalidate=30"
    )
    access_token = (
        public_order_tokens(request).issue(route.action.id, route.route_value)
        if submissions_allowed and route.action is not None
        else None
    )
    payload = public_action_route_response(
        route,
        access_token=access_token,
        legal_configuration=legal_configuration,
        delivery=await cast(
            DeliveryService, request.app.state.delivery_service
        ).for_published_order_form(route.action.id)
        if submissions_allowed and route.action is not None
        else None,
    )
    payload.campaign_host_url = await campaign_host_url(request, route.action, None)
    return payload


@router.get(
    "/api/v1/public/actions/archive/{archive_slug}",
    operation_id="resolvePublicActionArchive",
    response_model=PublicActionRouteResponse,
    responses=ERROR_RESPONSES,
    tags=["public-actions"],
)
async def resolve_public_action_archive(
    archive_slug: str,
    request: Request,
    response: Response,
) -> PublicActionRouteResponse:
    route = await action_service(request).resolve_public_archive(archive_slug)
    response.headers["Cache-Control"] = (
        "public, max-age=300, stale-while-revalidate=3600"
    )
    payload = public_action_route_response(route)
    payload.campaign_host_url = await campaign_host_url(request, route.action, None)
    return payload


@router.get(
    "/api/v1/public/campaigns",
    operation_id="listPublicCampaigns",
    response_model=PublicCampaignListResponse,
    responses=ERROR_RESPONSES,
    tags=["public-actions"],
)
async def list_public_campaigns(
    request: Request,
    response: Response,
    availability: Literal["active"] = "active",
) -> PublicCampaignListResponse:
    """Active campaigns for the home page of the public host (§6.5)."""
    listings = await action_service(request).list_active_public_campaigns()
    links = cast(LinkBuilder, request.app.state.links)
    hosted = await cast(
        CampaignHostUrls, request.app.state.site_directory
    ).campaign_host_urls(listing.action.id for listing in listings)
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    return PublicCampaignListResponse(
        items=[
            PublicCampaignListItemResponse(
                archive_slug=listing.action.archive_slug,
                name=listing.action.name,
                purpose=listing.action.purpose,
                carrier_name=listing.action.carrier_name,
                presentation_theme=listing.action.presentation_theme,
                starts_on=listing.action.starts_on,
                ends_on=listing.action.ends_on,
                canonical_path=listing.canonical_path,
                canonical_url=hosted.get(listing.action.id)
                or links.site_url(listing.canonical_path),
            )
            for listing in listings
        ]
    )


@router.get(
    "/api/v1/public/actions/campaign/{archive_slug}",
    operation_id="resolvePublicCampaign",
    response_model=PublicCampaignRouteResponse,
    responses=ERROR_RESPONSES,
    tags=["public-actions"],
)
async def resolve_public_campaign(
    archive_slug: str,
    request: Request,
    response: Response,
) -> PublicCampaignRouteResponse:
    route = await action_service(request).resolve_public_campaign(archive_slug)
    legal = (
        await legal_configuration_service(request).active_configuration()
        if route.submissions_allowed
        else None
    )
    response.headers["Cache-Control"] = "no-store"
    token = (
        public_order_tokens(request).issue(route.action.id, route.order_alias)
        if legal is not None
        and route.action is not None
        and route.order_alias is not None
        else None
    )
    # Reuse only the established field/legal serialization, not alias lookup
    # or its cache policy. The dedicated transport keeps slug and order alias
    # separate so the stable URL cannot silently retarget an order to a new year.
    payload = public_action_route_response(
        replace(route, route_kind=PublicActionRouteKind.ALIAS),
        access_token=token,
        legal_configuration=legal,
        delivery=await cast(
            DeliveryService, request.app.state.delivery_service
        ).for_published_order_form(route.action.id)
        if token is not None and route.action is not None
        else None,
    )
    return PublicCampaignRouteResponse(
        **payload.model_dump(
            exclude={"route_kind", "redirect_path", "campaign_host_url"}
        ),
        order_alias=route.order_alias if payload.submissions_allowed else None,
        campaign_host_url=await campaign_host_url(
            request, route.action, archive_slug.strip()
        ),
    )


def public_order_draft(body: CreatePublicOrderRequest) -> PublicOrderDraft:
    return PublicOrderDraft(
        delivery_window_id=body.delivery_window_id,
        delivery_contact=DeliveryContactSnapshot(**body.delivery_contact.model_dump())
        if body.delivery_contact
        else None,
        party=PublicOrderPartyDraft(
            company_name=body.party.company_name,
            given_name=body.party.given_name,
            family_name=body.party.family_name,
            email=body.party.email,
            phone=body.party.phone,
        ),
        delivery_recipient=(
            DeliveryRecipientSnapshot(
                recipient_name=body.delivery_recipient.recipient_name,
                street_line_1=body.delivery_recipient.street_line_1,
                postal_code=body.delivery_recipient.postal_code,
                city=body.delivery_recipient.city,
                country_code=body.delivery_recipient.country_code,
            )
            if body.delivery_recipient is not None
            else None
        ),
        invoice_recipient=InvoiceRecipientSnapshot(
            recipient_name=body.invoice_recipient.recipient_name,
            street_line_1=body.invoice_recipient.street_line_1,
            postal_code=body.invoice_recipient.postal_code,
            city=body.invoice_recipient.city,
            country_code=body.invoice_recipient.country_code,
            email=body.invoice_recipient.email.casefold(),
        ),
        lines=tuple(
            CommitmentLineDraft(
                offering_id=line.offering_id,
                quantity=line.quantity,
                unit=OfferingUnit(line.unit),
                quoted_unit_price_minor=line.quoted_unit_price_minor,
            )
            for line in body.lines
        ),
        message=body.message,
        privacy_acknowledged=body.privacy_acknowledged,
        binding_order_confirmed=body.binding_order_confirmed,
        privacy_notice_version=body.privacy_notice_version,
        website=body.website,
    )


def public_order_result_response(
    result: PublicOrderResult,
) -> PublicOrderResultResponse:
    reference = result.commitment.public_reference
    if reference is None:
        raise RuntimeError("Public order has no reference.")
    return PublicOrderResultResponse(
        commitment_id=result.commitment.id,
        public_reference=reference,
        status="review_ready",
        total_minor=result.commitment.total.amount_minor,
        currency=result.commitment.total.currency,
        total_boxes=result.commitment.total_boxes,
        total_pieces=result.commitment.total_pieces,
        quantities=[
            PublicOrderQuantityResponse(
                unit=line.unit_snapshot.value,
                quantity=line.quantity,
                pieces_per_unit=line.pieces_per_unit_snapshot,
            )
            for line in sorted(
                result.commitment.lines,
                key=lambda line: (
                    line.unit_snapshot.value,
                    line.pieces_per_unit_snapshot or 0,
                    str(line.offering_id),
                ),
            )
        ],
        crm_outcome=result.crm_outcome.value,
        replayed=result.replayed,
    )


@router.post(
    "/api/v1/public/actions/{public_alias}/orders",
    operation_id="createPublicOrder",
    response_model=PublicOrderResultResponse,
    responses={
        **ERROR_RESPONSES,
        403: {
            "model": ApiErrorResponse,
            "description": "Das signierte Formular ist ungültig oder abgelaufen.",
        },
        409: {
            "model": ApiErrorResponse,
            "description": "Aktionsstand, Preis oder Idempotenz kollidieren.",
        },
        429: {
            "model": ApiErrorResponse,
            "description": "Zu viele öffentliche Übermittlungsversuche.",
        },
    },
    status_code=status.HTTP_201_CREATED,
    tags=["public-actions"],
)
async def create_public_order(
    public_alias: str,
    body: CreatePublicOrderRequest,
    request: Request,
    response: Response,
) -> PublicOrderResultResponse:
    secret = cast(str, request.app.state.public_order_fingerprint_secret)
    try:
        async with asyncio.timeout(PUBLIC_ORDER_PROCESSING_TIMEOUT_SECONDS):
            result = await public_order_service(request).submit(
                public_alias,
                access_token=body.access_token,
                command_id=body.command_id,
                draft=public_order_draft(body),
                fingerprint_hash=public_order_fingerprint(
                    secret,
                    forwarded_for=request.headers.get("x-forwarded-for"),
                    client_host=request.client.host
                    if request.client is not None
                    else None,
                    user_agent=request.headers.get("user-agent"),
                ),
                request_id=request_id(request),
            )
    except TimeoutError:
        # CRM writes may already have completed. Do not claim that nothing was
        # saved: keep the same command identity for deterministic recovery.
        raise DependencyUnavailable(
            "public_order_processing_timeout",
            "Die Verarbeitung dauert gerade zu lange. Bitte senden Sie dieselbe "
            "Bestellung erneut, ohne die Seite neu zu laden.",
        ) from None
    response.headers["Cache-Control"] = "no-store"
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return public_order_result_response(result)


@router.get(
    "/api/v1/identity/me",
    operation_id="getCurrentIdentity",
    response_model=CurrentIdentityResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def current_identity(
    request: Request,
    response: Response,
) -> CurrentIdentityResponse:
    result = await identity_service(request).current_identity(session_token(request))
    response.headers["Cache-Control"] = "no-store"
    return CurrentIdentityResponse.model_validate(
        {
            **{field.name: getattr(result, field.name) for field in fields(result)},
            "installation": InstallationResponse(club_name=request.app.state.club_name),
        }
    )


@router.put(
    "/api/v1/identity/me/preferred-surface",
    operation_id="setPreferredSurface",
    response_model=CurrentIdentityResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def set_preferred_surface(
    body: PreferredSurfaceRequest,
    request: Request,
    response: Response,
) -> CurrentIdentityResponse:
    result = await identity_service(request).set_preferred_surface(
        session_token(request),
        PreferredSurface(body.surface) if body.surface is not None else None,
    )
    response.headers["Cache-Control"] = "no-store"
    return CurrentIdentityResponse.model_validate(
        {
            **{field.name: getattr(result, field.name) for field in fields(result)},
            "installation": InstallationResponse(club_name=request.app.state.club_name),
        }
    )


@router.get(
    "/api/v1/admin/members",
    operation_id="listMembers",
    response_model=MemberDirectoryResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def list_members(
    request: Request,
    response: Response,
    search: Annotated[str, Query(max_length=160)] = "",
    account_status: Annotated[
        Literal["invited", "active", "suspended", "archived"] | None,
        Query(alias="status"),
    ] = None,
    action_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 6,
) -> MemberDirectoryResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    page = await identity_service(request).list_members(
        actor,
        MemberDirectoryQuery(
            search=search,
            status=AccountStatus(account_status) if account_status else None,
            action_id=action_id,
            cursor=cursor,
            limit=limit,
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return MemberDirectoryResponse.model_validate(page)


@router.get(
    "/api/v1/search",
    operation_id="searchCore",
    response_model=SearchResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["search"],
)
async def search_core(
    request: Request,
    response: Response,
    q: Annotated[
        str,
        Query(
            min_length=SEARCH_QUERY_MIN_LENGTH,
            max_length=SEARCH_QUERY_MAX_LENGTH,
            description=(
                "Search text; actions, orders, invoices and members the "
                "account may read."
            ),
        ),
    ],
    limit: Annotated[int, Query(ge=1, le=SEARCH_LIMIT_MAX)] = SEARCH_LIMIT_DEFAULT,
) -> SearchResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    results = await search_service(request).search(actor, SearchQuery(q, limit))
    response.headers["Cache-Control"] = "no-store"
    return SearchResponse(
        results=[SearchResultResponse.model_validate(item) for item in results]
    )


@router.get(
    "/api/v1/admin/members/{user_id}",
    operation_id="getMember",
    response_model=MemberDirectoryMemberResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def get_member(
    user_id: UUID,
    request: Request,
    response: Response,
) -> MemberDirectoryMemberResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    member = await identity_service(request).get_member(actor, user_id)
    response.headers["Cache-Control"] = "no-store"
    return MemberDirectoryMemberResponse.model_validate(member)


@router.patch(
    "/api/v1/admin/members/{user_id}/status",
    operation_id="changeMemberStatus",
    response_model=MemberStatusChangeResponse,
    responses=MEMBER_STATUS_CONFLICT_RESPONSES,
    tags=["identity"],
)
async def change_member_status(
    user_id: UUID,
    body: ChangeMemberStatusRequest,
    request: Request,
    response: Response,
) -> MemberStatusChangeResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await identity_administration_service(request).change_status(
        actor,
        user_id,
        AccountStatus(body.status),
        expected_revision=body.expected_revision,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return MemberStatusChangeResponse(
        user_id=result.account.id,
        display_name=result.account.display_name,
        status=cast(
            Literal["active", "suspended", "archived"],
            result.account.status.value,
        ),
        status_label=STATUS_LABELS[result.account.status],
        previous_status=cast(
            Literal["active", "suspended"],
            result.previous_status.value,
        ),
        previous_status_label=STATUS_LABELS[result.previous_status],
        revision=result.account.revision,
        revoked_session_count=result.revoked_session_count,
        replayed=result.replayed,
    )


def member_role_change_response(
    result: RoleAssignmentChange,
) -> MemberRoleChangeResponse:
    return MemberRoleChangeResponse(
        user_id=result.user_id,
        revision=result.revision,
        scope="global" if isinstance(result.role, GlobalRole) else "action",
        role=cast(
            Literal[
                "system_admin",
                "finance_reader",
                "finance_manager",
                "charity_admin",
                "acquirer",
                "driver",
            ],
            result.role.value,
        ),
        role_label=ROLE_LABELS[result.role],
        enabled=result.enabled,
        action_id=result.action_id,
        action_name=result.action_name,
        replayed=result.replayed,
    )


@router.patch(
    "/api/v1/admin/members/{user_id}/global-roles/{role}",
    operation_id="changeMemberGlobalRole",
    response_model=MemberRoleChangeResponse,
    responses=MEMBER_GLOBAL_ROLE_CONFLICT_RESPONSES,
    tags=["identity"],
)
async def change_member_global_role(
    user_id: UUID,
    role: Literal["system_admin", "finance_reader", "finance_manager"],
    body: ChangeMemberRoleRequest,
    request: Request,
    response: Response,
) -> MemberRoleChangeResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await identity_administration_service(request).add_global_role(
        actor,
        user_id,
        GlobalRole(role),
        enabled=body.enabled,
        expected_revision=body.expected_revision,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return member_role_change_response(result)


@router.patch(
    "/api/v1/admin/members/{user_id}/actions/{action_id}/roles/{role}",
    operation_id="changeMemberActionRole",
    response_model=MemberRoleChangeResponse,
    responses=MEMBER_ACTION_ROLE_CONFLICT_RESPONSES,
    tags=["identity"],
)
async def change_member_action_role(
    user_id: UUID,
    action_id: UUID,
    role: Literal["charity_admin", "acquirer", "finance_reader", "driver"],
    body: ChangeMemberRoleRequest,
    request: Request,
    response: Response,
) -> MemberRoleChangeResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await identity_administration_service(request).add_action_membership(
        actor,
        user_id,
        action_id,
        ActionRole(role),
        enabled=body.enabled,
        expected_revision=body.expected_revision,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return member_role_change_response(result)


@router.get(
    "/api/v1/feature-flags/evaluations",
    operation_id="getFeatureFlagEvaluations",
    response_model=FeatureFlagEvaluationListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["feature-flags"],
)
async def feature_flag_evaluations(
    request: Request,
    response: Response,
    surface: Literal["web", "pwa"] = Query(default="web"),
) -> FeatureFlagEvaluationListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    evaluations = await feature_flag_service(request).evaluations(
        actor,
        FeatureFlagSurface(surface),
    )
    response.headers["Cache-Control"] = "no-store"
    return FeatureFlagEvaluationListResponse(
        surface=surface,
        flags=[
            FeatureFlagEvaluationResponse.model_validate(evaluation)
            for evaluation in evaluations
        ],
    )


@router.get(
    "/api/v1/admin/feature-flags",
    operation_id="listFeatureFlags",
    response_model=FeatureFlagAdminListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["feature-flags"],
)
async def list_feature_flags(
    request: Request,
    response: Response,
) -> FeatureFlagAdminListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    items = await feature_flag_service(request).list_admin(actor)
    response.headers["Cache-Control"] = "no-store"
    return FeatureFlagAdminListResponse(
        flags=[
            FeatureFlagAdminResponse(
                key=definition.key.value,
                title=definition.title,
                description=definition.description,
                effect=definition.effect,
                enabled=state.enabled,
                default_enabled=definition.default_enabled,
                client_safe=definition.client_safe,
                revision=state.revision,
                updated_by_user_id=state.updated_by_user_id,
                updated_at=state.updated_at,
            )
            for definition, state in items
        ]
    )


@router.put(
    "/api/v1/admin/feature-flags/{key}",
    operation_id="updateFeatureFlag",
    response_model=FeatureFlagAdminResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["feature-flags"],
)
async def update_feature_flag(
    key: str,
    body: UpdateFeatureFlagRequest,
    request: Request,
    response: Response,
) -> FeatureFlagAdminResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    definition, state = await feature_flag_service(request).update(
        actor,
        key=key,
        enabled=body.enabled,
        expected_revision=body.expected_revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return FeatureFlagAdminResponse(
        key=definition.key.value,
        title=definition.title,
        description=definition.description,
        effect=definition.effect,
        enabled=state.enabled,
        default_enabled=definition.default_enabled,
        client_safe=definition.client_safe,
        revision=state.revision,
        updated_by_user_id=state.updated_by_user_id,
        updated_at=state.updated_at,
    )


@router.get(
    "/api/v1/admin/system-status",
    operation_id="getFeatureFlagSystemStatus",
    response_model=FeatureFlagSystemStatusResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["feature-flags"],
)
async def feature_flag_system_status(
    request: Request,
    response: Response,
) -> FeatureFlagSystemStatusResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    require_system_admin(actor)
    await feature_flag_service(request).require_enabled(
        actor,
        FeatureFlagKey.SYSTEM_STATUS_PANEL,
        surface=FeatureFlagSurface.WEB,
    )
    response.headers["Cache-Control"] = "no-store"
    return FeatureFlagSystemStatusResponse(
        status="operational",
        evaluated_by="openfeature",
        provider="leonaid-postgres-snapshot",
        checked_at=datetime.now(timezone.utc),
    )


@router.get(
    "/api/v1/admin/operations",
    operation_id="getOperationsOverview",
    response_model=OperationsOverviewResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["operations"],
)
async def operations_overview(
    request: Request,
    response: Response,
) -> OperationsOverviewResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    require_system_admin(actor)
    snapshot = await operations_service(request).snapshot(
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return OperationsOverviewResponse(
        generated_at=snapshot.generated_at,
        request_id=snapshot.request_id,
        api=OperationalApiMetricsResponse.model_validate(snapshot.api),
        dependencies=[
            OperationalDependencyResponse.model_validate(item)
            for item in snapshot.dependencies
        ],
        outbox=OperationalStatusCountsResponse.model_validate(snapshot.outbox),
        next_pending_attempt_at=snapshot.next_pending_attempt_at,
        oldest_due_pending_age_seconds=snapshot.oldest_due_pending_age_seconds,
        mail=OperationalStatusCountsResponse.model_validate(snapshot.mail),
        login=OperationalLoginMetricsResponse.model_validate(snapshot.login),
        failed_jobs=[
            OperationalFailedJobResponse.model_validate(item)
            for item in snapshot.failed_jobs
        ],
        monitoring=OperationalMonitoringResponse(
            status=snapshot.monitoring.status,
            checks=[
                OperationalCheckResponse.model_validate(item)
                for item in snapshot.monitoring.checks
            ],
            active_alerts=[
                OperationalAlertResponse.model_validate(item)
                for item in snapshot.monitoring.active_alerts
            ],
        ),
        site_hosts=[
            OperationalSiteHostResponse(
                hostname=issue.hostname,
                status=issue.status.value,
                failed_checks=issue.failed_checks,
                last_check_result=issue.last_check_result,
                last_checked_at=issue.last_checked_at,
                live_bindings=issue.live_bindings,
            )
            for issue in await request.app.state.site_host_verification.issues()
        ],
    )


@router.get(
    "/api/v1/admin/pilot/reports/daily",
    operation_id="getPilotDailyReport",
    response_model=PilotDailyReportResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["operations"],
)
async def pilot_daily_report(
    request: Request,
    response: Response,
) -> PilotDailyReportResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    require_system_admin(actor)
    report = await operations_service(request).daily_report(
        request_id=request_id(request),
    )
    transport = PilotDailyReportResponse(
        schema_version="leonaid.pilot.daily-report/v1",
        scope="technical-daily-check",
        generated_at=report.generated_at,
        release=report.release,
        technical_status=report.technical_status,
        dependencies=PilotDailyDependenciesResponse.model_validate(report.dependencies),
        monitoring=PilotDailyMonitoringResponse.model_validate(report.monitoring),
        outbox=OperationalStatusCountsResponse.model_validate(report.outbox),
        api=OperationalApiMetricsResponse.model_validate(report.api),
        stop_reasons=list(report.stop_reasons),
        next_step=report.next_step,
        checksum_sha256="0" * 64,
    )
    canonical_content = json.dumps(
        transport.model_dump(
            by_alias=True,
            exclude={"checksum_sha256"},
            mode="json",
        ),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    checksum = hashlib.sha256(canonical_content).hexdigest()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        f'inline; filename="leonaid-pilot-daily-'
        f'{local_day(report.generated_at).isoformat()}.json"'
    )
    response.headers["X-Content-SHA256"] = checksum
    return transport.model_copy(update={"checksum_sha256": checksum})


@router.post(
    "/api/v1/admin/support/probe",
    operation_id="runSupportProbe",
    response_model=ApiErrorResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["operations"],
)
async def run_support_probe(request: Request) -> ApiErrorResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    require_system_admin(actor)
    raise DependencyUnavailable(
        "support_probe_failed",
        (
            "Der kontrollierte Diagnosetest wurde wie vorgesehen abgebrochen. "
            "Den Support-Code kopieren und direkt darunter prüfen."
        ),
    )


@router.get(
    "/api/v1/admin/support/requests/{support_code}",
    operation_id="getSupportRequestDiagnostic",
    response_model=SupportRequestDiagnosticResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["operations"],
)
async def support_request_diagnostic(
    support_code: str,
    request: Request,
    response: Response,
) -> SupportRequestDiagnosticResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    require_system_admin(actor)
    diagnostic = request_diagnostics(request).find(support_code)
    if diagnostic is None:
        raise ResourceNotFound(
            "support_request_not_found",
            (
                "Zu diesem Support-Code gibt es im aktuellen Diagnosefenster "
                "keinen Eintrag. Den Code prüfen oder den Vorgang wiederholen."
            ),
        )
    outcome: Literal["successful", "rejected", "failed"]
    if diagnostic.status_code >= 500:
        outcome = "failed"
        impact = "Die Anfrage konnte nicht abgeschlossen werden."
        next_step = (
            "Betriebsstatus und Runbook zum genannten Fehlercode prüfen. "
            "Erst danach die betroffene Aktion wiederholen."
        )
    elif diagnostic.status_code >= 400:
        outcome = "rejected"
        impact = "Die Anfrage wurde kontrolliert abgelehnt."
        next_step = (
            "Berechtigung, Eingaben und Anmeldung prüfen. Es wurden keine "
            "fachlichen Daten aus dieser Anfrage angezeigt."
        )
    else:
        outcome = "successful"
        impact = "Die Anfrage wurde erfolgreich verarbeitet."
        next_step = "Es ist keine technische Maßnahme erforderlich."
    response.headers["Cache-Control"] = "no-store"
    return SupportRequestDiagnosticResponse(
        support_code=diagnostic.request_id,
        occurred_at=diagnostic.occurred_at,
        method=cast(
            Literal["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
            diagnostic.method,
        ),
        route=diagnostic.route,
        status_code=diagnostic.status_code,
        error_code=diagnostic.error_code,
        outcome=outcome,
        impact=impact,
        next_step=next_step,
        release=diagnostic.release,
    )


@router.get(
    "/metrics",
    include_in_schema=False,
    response_class=PlainTextResponse,
)
async def prometheus_metrics(request: Request) -> PlainTextResponse:
    snapshot = await operations_service(request).snapshot(
        request_id=request_id(request),
    )
    body = render_operations_metrics(
        snapshot,
        maintenance_mode=request.app.state.maintenance_flag_path.is_file(),
    )
    return PlainTextResponse(
        body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/api/v1/admin/operations/jobs/{event_id}/retry",
    operation_id="retryOperationalJob",
    response_model=OperationalJobRetryResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["operations"],
)
async def retry_operational_job(
    event_id: UUID,
    request: Request,
    response: Response,
) -> OperationalJobRetryResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    require_system_admin(actor)
    try:
        retried = await operations_service(request).retry(
            event_id=event_id,
            operator_user_id=actor.account.id,
            request_id=request_id(request),
        )
    except ValueError as error:
        raise Conflict(
            "outbox_job_not_retryable",
            str(error),
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return OperationalJobRetryResponse(
        id=retried.id,
        status="pending",
        manual_retry_count=retried.manual_retry_count,
        request_id=request_id(request),
    )


@router.get(
    "/api/v1/admin/legal/configuration",
    operation_id="getLegalConfiguration",
    response_model=LegalConfigurationStateResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["legal-configuration"],
)
async def get_legal_configuration(
    request: Request,
    response: Response,
) -> LegalConfigurationStateResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    service = legal_configuration_service(request)
    state = await service.state(actor)
    response.headers["Cache-Control"] = "no-store"
    return legal_configuration_state_response(
        state,
        production=service.production,
    )


@router.put(
    "/api/v1/admin/legal/configuration/draft",
    operation_id="saveLegalConfigurationDraft",
    response_model=LegalConfigurationStateResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["legal-configuration"],
)
async def save_legal_configuration_draft(
    body: SaveLegalConfigurationDraftRequest,
    request: Request,
    response: Response,
) -> LegalConfigurationStateResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    issuer = body.issuer
    service = legal_configuration_service(request)
    state = await service.save_draft(
        actor,
        configuration=LegalConfigurationDraft(
            issuer=InvoiceIssuerSnapshot(
                legal_name=issuer.legal_name,
                street_line_1=issuer.street_line_1,
                postal_code=issuer.postal_code,
                city=issuer.city,
                country_code=issuer.country_code,
                tax_identifier=issuer.tax_identifier,
                email=issuer.email,
            ),
            bank_account_holder=body.bank_account_holder,
            iban=body.iban,
            bic=body.bic,
            tax_treatment=TaxTreatment(body.tax_treatment),
            tax_rate_basis_points=body.tax_rate_basis_points,
            tax_note=body.tax_note,
            number_prefix=body.number_prefix,
            number_width=body.number_width,
            payment_terms_days=body.payment_terms_days,
            public_order_legal_basis=body.public_order_legal_basis,
            public_order_notice_text=body.public_order_notice_text,
            consent_text_version=body.consent_text_version,
            privacy_contact_email=body.privacy_contact_email,
            retention=RetentionSchedule(
                invoice_days=body.retention.invoice_days,
                commitment_days=body.retention.commitment_days,
                contact_days=body.retention.contact_days,
                consent_evidence_days=body.retention.consent_evidence_days,
                audit_days=body.retention.audit_days,
            ),
            e_invoice_decision=EInvoiceDecision(body.e_invoice_decision),
            tax_evidence_id=body.tax_evidence_id,
            privacy_evidence_id=body.privacy_evidence_id,
            e_invoice_evidence_id=body.e_invoice_evidence_id,
            legal_form=(
                LegalForm(body.legal_form) if body.legal_form is not None else None
            ),
            imprint_representatives=body.imprint_representatives,
            imprint_phone=body.imprint_phone,
            imprint_register_court=body.imprint_register_court,
            imprint_register_number=body.imprint_register_number,
            imprint_vat_id=body.imprint_vat_id,
            imprint_content_responsible_name=body.imprint_content_responsible_name,
            imprint_content_responsible_address=(
                body.imprint_content_responsible_address
            ),
            privacy_policy_text=body.privacy_policy_text,
            member_privacy_notice_text=body.member_privacy_notice_text,
        ),
        expected_revision=body.expected_revision,
        request_id=request_id(request),
        omitted_fields=frozenset(
            type(body).model_fields.keys() - body.model_fields_set
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return legal_configuration_state_response(
        state,
        production=service.production,
    )


@router.post(
    "/api/v1/admin/legal/configuration/draft/{version_id}/approval",
    operation_id="approveLegalConfigurationDraft",
    response_model=LegalConfigurationStateResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["legal-configuration"],
)
async def approve_legal_configuration_draft(
    version_id: UUID,
    body: ApproveLegalConfigurationRequest,
    request: Request,
    response: Response,
) -> LegalConfigurationStateResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    service = legal_configuration_service(request)
    state = await service.approve(
        actor,
        version_id=version_id,
        evidence_id=body.evidence_id,
        expected_revision=body.expected_revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return legal_configuration_state_response(
        state,
        production=service.production,
    )


@router.post(
    "/api/v1/admin/legal/configuration/draft/{version_id}/activation",
    operation_id="activateLegalConfigurationDraft",
    response_model=LegalConfigurationStateResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["legal-configuration"],
)
async def activate_legal_configuration_draft(
    version_id: UUID,
    body: ActivateLegalConfigurationRequest,
    request: Request,
    response: Response,
) -> LegalConfigurationStateResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    service = legal_configuration_service(request)
    state = await service.activate(
        actor,
        version_id=version_id,
        expected_revision=body.expected_revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return legal_configuration_state_response(
        state,
        production=service.production,
    )


@router.post(
    "/api/v1/admin/privacy/lookup",
    operation_id="lookupPrivacySubject",
    response_model=PrivacySubjectReportResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["privacy"],
)
async def lookup_privacy_subject(
    body: PrivacySubjectRequest,
    request: Request,
    response: Response,
) -> PrivacySubjectReportResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    report = await privacy_service(request).lookup(actor, email=body.email)
    response.headers["Cache-Control"] = "no-store"
    return privacy_report_response(report)


@router.post(
    "/api/v1/admin/privacy/exports",
    operation_id="exportPrivacySubject",
    response_model=PrivacySubjectReportResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["privacy"],
)
async def export_privacy_subject(
    body: PrivacySubjectRequest,
    request: Request,
    response: Response,
) -> PrivacySubjectReportResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    report = await privacy_service(request).export(actor, email=body.email)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        'attachment; filename="leonaid-datenauskunft.json"'
    )
    return privacy_report_response(report)


@router.post(
    "/api/v1/admin/privacy/consents/{consent_id}/revoke",
    operation_id="revokePrivacyConsent",
    response_model=PrivacyConsentResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["privacy"],
)
async def revoke_privacy_consent(
    consent_id: UUID,
    body: RevokePrivacyConsentRequest,
    request: Request,
    response: Response,
) -> PrivacyConsentResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    item = await privacy_service(request).revoke(
        actor,
        consent_id=consent_id,
        reason=body.reason,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return privacy_consent_response(item)


@router.post(
    "/api/v1/admin/privacy/erasures",
    operation_id="erasePrivacySubject",
    response_model=PrivacyErasureResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["privacy"],
)
async def erase_privacy_subject(
    body: PrivacyErasureRequest,
    request: Request,
    response: Response,
) -> PrivacyErasureResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await privacy_service(request).erase(
        actor,
        email=body.email,
        confirmation=body.confirmation,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return PrivacyErasureResponse(
        case_id=result.case_id,
        subject_hash=result.subject_hash,
        status=result.status.value,
        retention=PrivacyRetentionResponse.model_validate(result.retention),
        anonymized_commitments=result.anonymized_commitments,
        cleared_activity_notes=result.cleared_activity_notes,
        cleared_reminders=result.cleared_reminders,
        revoked_consents=result.revoked_consents,
        retained_invoice_ids=list(result.retained_invoice_ids),
        retained_document_ids=list(result.retained_document_ids),
        retention_reasons=list(result.retention_reasons),
        open_decisions=list(result.open_decisions),
        completed_at=result.completed_at,
    )


@router.post(
    "/api/v1/auth/login",
    operation_id="requestLogin",
    response_model=LoginDispatchResponse,
    responses=ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["identity"],
)
async def request_login(
    request: Request,
    body: RequestLoginRequest,
    response: Response,
) -> LoginDispatchResponse:
    await authentication_service(request).request_login(
        body.email,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return LoginDispatchResponse(status="queued")


@router.post(
    "/api/v1/auth/login/complete",
    operation_id="completeLogin",
    response_model=SessionAuthenticationResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def complete_login(
    request: Request,
    body: CompleteLoginRequest,
    response: Response,
) -> SessionAuthenticationResponse:
    if body.magic_token is not None:
        grant = await authentication_service(request).complete_login_magic(
            body.magic_token,
            device_hint=device_hint(request),
            request_id=request_id(request),
        )
    else:
        grant = await authentication_service(request).complete_login_code(
            cast(str, body.email),
            cast(str, body.code),
            device_hint=device_hint(request),
            request_id=request_id(request),
        )
    set_session_cookie(response, grant)
    return SessionAuthenticationResponse(
        status="authenticated",
        user_id=grant.user_id,
        display_name=grant.display_name,
        expires_at=grant.expires_at,
        fresh_login_at=grant.fresh_login_at,
    )


@router.post(
    "/api/v1/auth/fresh",
    operation_id="requestFreshLogin",
    response_model=LoginDispatchResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["identity"],
)
async def request_fresh_login(
    request: Request,
    response: Response,
) -> LoginDispatchResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    await authentication_service(request).request_fresh_login(
        actor,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return LoginDispatchResponse(status="queued")


@router.get(
    "/api/v1/auth/fresh/status",
    operation_id="getFreshLoginStatus",
    response_model=FreshLoginStatusResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def fresh_login_status(
    request: Request,
    response: Response,
) -> FreshLoginStatusResponse:
    fresh_until = await identity_service(request).fresh_until(session_token(request))
    response.headers["Cache-Control"] = "no-store"
    return FreshLoginStatusResponse(
        status="fresh",
        fresh_until=fresh_until,
    )


@router.post(
    "/api/v1/auth/fresh/complete",
    operation_id="completeFreshLogin",
    response_model=SessionAuthenticationResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def complete_fresh_login(
    request: Request,
    body: CompleteFreshLoginRequest,
    response: Response,
) -> SessionAuthenticationResponse:
    raw_session = session_token(request)
    actor = await identity_service(request).authenticate(raw_session)
    if body.magic_token is not None:
        grant = await authentication_service(request).complete_fresh_magic(
            raw_session,
            body.magic_token,
            device_hint=device_hint(request),
            request_id=request_id(request),
        )
    else:
        grant = await authentication_service(request).complete_fresh_code(
            actor,
            raw_session,
            cast(str, body.code),
            device_hint=device_hint(request),
            request_id=request_id(request),
        )
    set_session_cookie(response, grant)
    return SessionAuthenticationResponse(
        status="authenticated",
        user_id=grant.user_id,
        display_name=grant.display_name,
        expires_at=grant.expires_at,
        fresh_login_at=grant.fresh_login_at,
    )


@router.post(
    "/api/v1/auth/logout",
    operation_id="logout",
    response_model=LogoutResponse,
    responses=ERROR_RESPONSES,
    tags=["identity"],
)
async def logout(
    request: Request,
    response: Response,
) -> LogoutResponse:
    await authentication_service(request).logout(
        session_token(request),
        request_id=request_id(request),
    )
    clear_session_cookie(response)
    return LogoutResponse(status="signed_out")


@router.delete(
    "/api/v1/admin/users/{user_id}/sessions",
    operation_id="revokeUserSessions",
    response_model=SessionRevocationResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def revoke_user_sessions(
    user_id: UUID,
    request: Request,
    response: Response,
) -> SessionRevocationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    revoked_count = await authentication_service(request).revoke_all_for_user(
        actor,
        user_id,
        request_id=request_id(request),
    )
    if actor.account.id == user_id:
        clear_session_cookie(response)
    else:
        response.headers["Cache-Control"] = "no-store"
    return SessionRevocationResponse(
        status="revoked",
        revoked_count=revoked_count,
    )


@router.get(
    "/api/v1/action-templates",
    operation_id="listActionTemplates",
    response_model=ActionTemplateListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def list_action_templates(
    request: Request,
    response: Response,
) -> ActionTemplateListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    templates = await action_service(request).list_templates(actor)
    response.headers["Cache-Control"] = "no-store"
    return ActionTemplateListResponse(
        items=[action_template_summary_response(item) for item in templates]
    )


@router.post(
    "/api/v1/actions/from-template",
    operation_id="createCharityActionFromTemplate",
    response_model=CharityActionConfigurationResponse,
    responses=ACTION_CREATE_CONFLICT_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["actions"],
)
async def create_charity_action_from_template(
    request: Request,
    body: CreateActionFromTemplateRequest,
    response: Response,
) -> CharityActionConfigurationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action, configuration = await action_service(request).create_from_template(
        actor,
        CreateActionFromTemplateDraft(
            template_key=ActionTemplateKey(body.template_key),
            template_version=body.template_version,
            carrier_name=body.carrier_name,
            name=body.name,
            purpose=body.purpose,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
            archive_slug=body.archive_slug,
            beneficiaries=beneficiary_drafts(body.beneficiaries),
            goal=goal_from_request(body.goal),
        ),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/actions/{action.id}/configuration"
    return charity_action_configuration_response(action, configuration)


@router.get(
    "/api/v1/actions",
    operation_id="listCharityActions",
    response_model=CharityActionListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def list_charity_actions(
    request: Request,
    response: Response,
) -> CharityActionListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    summaries = await action_service(request).list_managed(actor)
    response.headers["Cache-Control"] = "no-store"
    return CharityActionListResponse(
        items=[
            CharityActionSummaryResponse(
                id=item.id,
                name=item.name,
                status=item.status.value,
                starts_on=item.starts_on,
                ends_on=item.ends_on,
                template_name=item.template_name,
                lead_names=list(item.lead_names),
                goal=ActionGoalResponse(
                    goal_value=(
                        decimal_text(item.goal.goal_value)
                        if item.goal.goal_value is not None
                        else None
                    ),
                    actual_value=decimal_text(item.goal.actual_value),
                    unit=item.goal.unit,
                    currency=item.goal.currency,
                ),
            )
            for item in summaries
        ]
    )


@router.post(
    "/api/v1/actions",
    operation_id="createCharityAction",
    response_model=CharityActionResponse,
    responses=ACTION_CREATE_CONFLICT_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["actions"],
)
async def create_charity_action(
    request: Request,
    body: CreateCharityActionRequest,
    response: Response,
) -> CharityActionResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action = await action_service(request).create(
        actor,
        CreateActionDraft(
            carrier_name=body.carrier_name,
            name=body.name,
            purpose=body.purpose,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
            archive_slug=body.archive_slug,
            capabilities=tuple(ActionCapability(item) for item in body.capabilities),
            beneficiaries=beneficiary_drafts(body.beneficiaries),
            goal=goal_from_request(body.goal),
        ),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/actions/{action.id}"
    return charity_action_response(action)


@router.get(
    "/api/v1/actions/{action_id}",
    operation_id="getCharityAction",
    response_model=CharityActionResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def get_charity_action(
    action_id: UUID,
    request: Request,
    response: Response,
) -> CharityActionResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    action = await action_service(request).get(actor, action_id)
    response.headers["Cache-Control"] = "no-store"
    return charity_action_response(action)


@router.get(
    "/api/v1/actions/{action_id}/management",
    operation_id="getCharityActionManagement",
    response_model=ActionManagementResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def get_charity_action_management(
    action_id: UUID,
    request: Request,
    response: Response,
) -> ActionManagementResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    state = await action_service(request).get_management(actor, action_id)
    response.headers["Cache-Control"] = "no-store"
    return action_management_response(state)


@router.put(
    "/api/v1/actions/{action_id}/details",
    operation_id="setCharityActionDetails",
    response_model=CharityActionResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_charity_action_details(
    action_id: UUID,
    request: Request,
    body: UpdateActionDetailsRequest,
    response: Response,
) -> CharityActionResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action = await action_service(request).set_details(
        actor,
        action_id,
        UpdateActionDetailsDraft(
            carrier_name=body.carrier_name,
            name=body.name,
            purpose=body.purpose,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
        ),
        expected_revision=body.revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return charity_action_response(action)


@router.get(
    "/api/v1/actions/{action_id}/redirect-aliases",
    operation_id="listCampaignAliases",
    response_model=CampaignAliasListResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def list_campaign_aliases(
    action_id: UUID, request: Request, response: Response
) -> CampaignAliasListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    result = await campaign_alias_service(request).list_for_action(actor, action_id)
    response.headers["Cache-Control"] = "no-store"
    return CampaignAliasListResponse.model_validate(result)


@router.post(
    "/api/v1/actions/{action_id}/redirect-aliases",
    operation_id="createCampaignAlias",
    response_model=CampaignAliasMutationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def create_campaign_alias(
    action_id: UUID,
    request: Request,
    body: CreateCampaignAliasRequest,
    response: Response,
) -> CampaignAliasMutationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await campaign_alias_service(request).mutate(
        actor,
        CampaignAliasCommand(
            body.command_id,
            body.alias_id,
            action_id,
            action_id,
            "create",
            0,
            body.alias,
            body.enabled,
        ),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return CampaignAliasMutationResponse.model_validate(result)


@router.put(
    "/api/v1/actions/{action_id}/redirect-aliases/{alias_id}",
    operation_id="updateCampaignAlias",
    response_model=CampaignAliasMutationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def update_campaign_alias(
    action_id: UUID,
    alias_id: UUID,
    request: Request,
    body: UpdateCampaignAliasRequest,
    response: Response,
) -> CampaignAliasMutationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await campaign_alias_service(request).mutate(
        actor,
        CampaignAliasCommand(
            body.command_id,
            alias_id,
            action_id,
            body.target_action_id,
            "update",
            body.revision,
            body.alias,
            body.enabled,
        ),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return CampaignAliasMutationResponse.model_validate(result)


@router.delete(
    "/api/v1/actions/{action_id}/redirect-aliases/{alias_id}",
    operation_id="removeCampaignAlias",
    response_model=CampaignAliasMutationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def remove_campaign_alias(
    action_id: UUID,
    alias_id: UUID,
    request: Request,
    body: RemoveCampaignAliasRequest,
    response: Response,
) -> CampaignAliasMutationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await campaign_alias_service(request).mutate(
        actor,
        CampaignAliasCommand(
            body.command_id,
            alias_id,
            action_id,
            action_id,
            "remove",
            body.revision,
        ),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return CampaignAliasMutationResponse.model_validate(result)


@router.put(
    "/api/v1/actions/{action_id}/redirect-aliases/{alias_id}/renderer",
    operation_id="selectCampaignRenderer",
    response_model=CampaignRendererResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def select_campaign_renderer(
    action_id: UUID,
    alias_id: UUID,
    request: Request,
    body: SelectCampaignRendererRequest,
    response: Response,
) -> CampaignRendererResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await campaign_alias_service(request).select_renderer(
        actor,
        CampaignRendererCommand(
            body.command_id, alias_id, action_id, body.revision, body.renderer
        ),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return CampaignRendererResponse.model_validate(result)


@router.put(
    "/api/v1/actions/{action_id}/publication",
    operation_id="setCharityActionPublication",
    response_model=ActionManagementResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_charity_action_publication(
    action_id: UUID,
    request: Request,
    body: SetActionPublicationRequest,
    response: Response,
) -> ActionManagementResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    state = await action_service(request).set_publication(
        actor,
        action_id,
        publication_starts_at=body.publication_starts_at,
        publication_ends_at=body.publication_ends_at,
        public_alias=body.public_alias,
        expected_revision=body.revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return action_management_response(state)


@router.put(
    "/api/v1/actions/{action_id}/responsible-administrators",
    operation_id="setCharityActionResponsibleAdministrators",
    response_model=ActionManagementResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_charity_action_responsible_administrators(
    action_id: UUID,
    request: Request,
    body: SetResponsibleAdministratorsRequest,
    response: Response,
) -> ActionManagementResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    state = await action_service(request).set_responsible_administrators(
        actor,
        action_id,
        body.user_ids,
        expected_revision=body.revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return action_management_response(state)


@router.get(
    "/api/v1/actions/{action_id}/configuration",
    operation_id="getCharityActionConfiguration",
    response_model=CharityActionConfigurationResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def get_charity_action_configuration(
    action_id: UUID,
    request: Request,
    response: Response,
) -> CharityActionConfigurationResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    action, configuration = await action_service(request).get_configuration(
        actor,
        action_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return charity_action_configuration_response(action, configuration)


@router.get(
    "/api/v1/actions/{action_id}/dashboard",
    operation_id="getActionDashboard",
    response_model=DashboardResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["dashboard"],
)
async def get_action_dashboard(
    action_id: UUID,
    request: Request,
    response: Response,
) -> DashboardResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    snapshot = await dashboard_service(request).get(actor, action_id)
    response.headers["Cache-Control"] = "private, no-store"
    return dashboard_response(snapshot)


@router.get(
    "/api/v1/actions/{action_id}/commitment-capture",
    operation_id="getCommitmentCaptureContext",
    response_model=CommitmentCaptureContextResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["commitments"],
)
async def get_commitment_capture_context(
    action_id: UUID,
    request: Request,
    response: Response,
) -> CommitmentCaptureContextResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    context = await commitment_service(request).capture_context(actor, action_id)
    response.headers["Cache-Control"] = "no-store"
    return commitment_capture_context_response(context)


@router.get(
    "/api/v1/actions/{action_id}/commitments",
    operation_id="listCommitments",
    response_model=CommitmentListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["commitments"],
)
async def list_commitments(
    action_id: UUID,
    request: Request,
    response: Response,
) -> CommitmentListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    commitments = await commitment_service(request).list_for_action(actor, action_id)
    response.headers["Cache-Control"] = "no-store"
    return commitment_list_response(commitments)


@router.post(
    "/api/v1/actions/{action_id}/commitments",
    operation_id="createCommitment",
    response_model=CommitmentResponse,
    responses=COMMITMENT_CREATE_CONFLICT_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["commitments"],
)
async def create_commitment(
    action_id: UUID,
    request: Request,
    body: CreateCommitmentRequest,
    response: Response,
) -> CommitmentResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    commitment = await commitment_service(request).create_internal(
        actor,
        action_id,
        source=CommitmentSource(body.source),
        ready_for_review=body.ready_for_review,
        draft=commitment_draft(body),
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/commitments/{commitment.id}"
    )
    return commitment_response(commitment)


@router.get(
    "/api/v1/actions/{action_id}/commitments/{commitment_id}",
    operation_id="getCommitment",
    response_model=CommitmentResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["commitments"],
)
async def get_commitment(
    action_id: UUID,
    commitment_id: UUID,
    request: Request,
    response: Response,
) -> CommitmentResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    commitment = await commitment_service(request).get_internal(
        actor, action_id, commitment_id
    )
    response.headers["Cache-Control"] = "private, no-store"
    return commitment_response(commitment)


@router.post(
    "/api/v1/actions/{action_id}/commitments/{commitment_id}/complete",
    operation_id="completeCommitment",
    response_model=CommitmentResponse,
    responses=COMMITMENT_COMPLETE_CONFLICT_RESPONSES,
    tags=["commitments"],
)
async def complete_commitment(
    action_id: UUID,
    commitment_id: UUID,
    request: Request,
    body: CompleteCommitmentRequest,
    response: Response,
) -> CommitmentResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    address = body.delivery_recipient
    contact = body.delivery_contact
    completion = CommitmentCompletion(
        allow_full_window=body.allow_full_window,
        captured_at=body.captured_at,
        delivery_recipient=DeliveryRecipientSnapshot(
            address.recipient_name,
            address.street_line_1,
            address.postal_code,
            address.city,
            address.country_code,
        )
        if address is not None
        else None,
        delivery_window_id=body.delivery_window_id,
        delivery_contact=DeliveryContactSnapshot(
            contact.name, contact.phone, contact.driver_note
        )
        if contact is not None
        else None,
    )
    commitment = await commitment_service(request).complete_draft(
        actor,
        action_id,
        commitment_id,
        completion=completion,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return commitment_response(commitment)


@router.post(
    "/api/v1/actions/{action_id}/commitments/{commitment_id}/delivery-completion",
    operation_id="completeCommitmentDelivery",
    response_model=CommitmentResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["commitments"],
)
async def complete_commitment_delivery(
    action_id: UUID,
    commitment_id: UUID,
    request: Request,
    body: CompleteCommitmentDeliveryRequest,
    response: Response,
) -> CommitmentResponse:
    """Manager completion of delivery and billing details before invoicing."""
    actor = await identity_service(request).authenticate(session_token(request))
    address = body.delivery_recipient
    contact = body.delivery_contact
    recipient = body.invoice_recipient
    draft = DeliveryCompletionDraft(
        expected_version=body.expected_version,
        allow_full_window=body.allow_full_window,
        invoice_recipient=InvoiceRecipientSnapshot(
            recipient_name=recipient.recipient_name,
            street_line_1=recipient.street_line_1,
            postal_code=recipient.postal_code,
            city=recipient.city,
            country_code=recipient.country_code,
            email=recipient.email,
        ),
        delivery_recipient=DeliveryRecipientSnapshot(
            address.recipient_name,
            address.street_line_1,
            address.postal_code,
            address.city,
            address.country_code,
        )
        if address is not None
        else None,
        delivery_window_id=body.delivery_window_id,
        delivery_contact=DeliveryContactSnapshot(
            contact.name, contact.phone, contact.driver_note
        )
        if contact is not None
        else None,
    )
    commitment = await cast(
        DeliveryCompletionService, request.app.state.delivery_completion_service
    ).complete(
        actor,
        action_id,
        commitment_id,
        draft=draft,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return commitment_response(commitment)


@router.post(
    "/api/v1/actions/{action_id}/commitments/{commitment_id}/cancellation",
    operation_id="cancelCommitment",
    response_model=CommitmentCancellationResultResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["commitments"],
)
async def cancel_commitment(
    action_id: UUID,
    commitment_id: UUID,
    request: Request,
    body: CancelCommitmentRequest,
    response: Response,
) -> CommitmentCancellationResultResponse:
    """Cancel an order that is not delivered yet, with a required reason.

    Answers 409 for a stale ``expectedVersion``, a delivered order, a booked
    payment or an order that is already cancelled. An issued, unpaid invoice
    is cancelled with the order (ADR-0009); that needs a fresh login (401
    ``fresh_login_required``).
    """
    actor, fresh = await identity_service(request).authenticate_with_freshness(
        session_token(request)
    )
    result = await order_cancellation_service(request).cancel(
        actor,
        action_id,
        commitment_id,
        request=OrderCancellationRequest(
            expected_version=body.expected_version,
            reason=body.reason,
            note=body.note,
        ),
        fresh_login=fresh,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/commitments/{commitment_id}/cancellation"
    )
    return CommitmentCancellationResultResponse(
        commitment=commitment_response(result.commitment),
        cancellation=commitment_cancellation_response(result.cancellation),
        replayed=result.replayed,
    )


@router.get(
    "/api/v1/actions/{action_id}/invoice-context",
    operation_id="getInvoiceContext",
    response_model=InvoiceContextResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["invoices"],
)
async def get_invoice_context(
    action_id: UUID,
    request: Request,
    response: Response,
) -> InvoiceContextResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    context = await invoice_service(request).context(actor, action_id)
    response.headers["Cache-Control"] = "no-store"
    return invoice_context_response(context)


@router.get(
    "/api/v1/actions/{action_id}/invoices",
    operation_id="listInvoices",
    response_model=InvoiceListResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["invoices"],
)
async def list_invoices(
    action_id: UUID,
    request: Request,
    response: Response,
) -> InvoiceListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    invoices = await invoice_service(request).list_for_action(actor, action_id)
    response.headers["Cache-Control"] = "no-store"
    return invoice_list_response(invoices)


@router.post(
    "/api/v1/actions/{action_id}/commitments/{commitment_id}/invoice",
    operation_id="issueInvoice",
    response_model=InvoiceResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def issue_invoice(
    action_id: UUID,
    commitment_id: UUID,
    request: Request,
    body: IssueInvoiceRequest,
    response: Response,
) -> InvoiceResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    invoice = await invoice_service(request).issue(
        actor,
        action_id,
        commitment_id,
        service_on=body.service_on,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/actions/{action_id}/invoices/{invoice.id}"
    return invoice_response(invoice)


@router.post(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/payments",
    operation_id="recordInvoicePayment",
    response_model=InvoicePaymentResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def record_invoice_payment(
    action_id: UUID,
    invoice_id: UUID,
    request: Request,
    body: RecordInvoicePaymentRequest,
    response: Response,
) -> InvoicePaymentResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    payment = await invoice_settlement_service(request).record_payment(
        actor,
        action_id,
        invoice_id,
        amount_minor=body.amount_minor,
        currency=body.currency,
        received_on=body.received_on,
        reference=body.reference,
        note=body.note,
        expected_version=body.expected_settlement_version,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/invoices/{invoice_id}/payments/{payment.id}"
    )
    return invoice_payment_response(payment)


@router.post(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/payments/{payment_id}/reversal",
    operation_id="reverseInvoicePayment",
    response_model=InvoicePaymentReversalResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def reverse_invoice_payment(
    action_id: UUID,
    invoice_id: UUID,
    payment_id: UUID,
    request: Request,
    body: ReverseInvoicePaymentRequest,
    response: Response,
) -> InvoicePaymentReversalResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    reversal = await invoice_settlement_service(request).reverse_payment(
        actor,
        action_id,
        invoice_id,
        payment_id,
        reason=body.reason,
        expected_version=body.expected_settlement_version,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/invoices/{invoice_id}/payments/"
        f"{payment_id}/reversal"
    )
    return invoice_payment_reversal_response(reversal)


@router.post(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation",
    operation_id="cancelInvoice",
    response_model=InvoiceCancellationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def cancel_invoice(
    action_id: UUID,
    invoice_id: UUID,
    request: Request,
    body: CancelInvoiceRequest,
    response: Response,
) -> InvoiceCancellationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    cancellation = await invoice_settlement_service(request).cancel(
        actor,
        action_id,
        invoice_id,
        reason=body.reason,
        send_document=body.send_cancellation,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation"
    )
    return invoice_cancellation_response(cancellation)


@router.post(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation/document",
    operation_id="issueInvoiceCancellationDocument",
    response_model=InvoiceCancellationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def issue_invoice_cancellation_document(
    action_id: UUID,
    invoice_id: UUID,
    request: Request,
    response: Response,
) -> InvoiceCancellationResponse:
    """Issue the cancellation invoice of an invoice cancelled before it existed.

    Cancelling an invoice issues its cancellation invoice in the same step.
    This is for older cancellations only; it answers 409
    ``invoice_cancellation_document_exists`` when the document exists.
    """
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    cancellation = await invoice_settlement_service(
        request
    ).issue_cancellation_document(
        actor,
        action_id,
        invoice_id,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation"
    )
    return invoice_cancellation_response(cancellation)


@router.post(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation/refund",
    operation_id="settleInvoiceCancellationRefund",
    response_model=InvoiceCancellationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def settle_invoice_cancellation_refund(
    action_id: UUID,
    invoice_id: UUID,
    request: Request,
    body: SettleInvoiceRefundRequest,
    response: Response,
) -> InvoiceCancellationResponse:
    """Record that the money received for a cancelled invoice went back.

    LeonAid books no refund; this closes the reminder "Erstattung offen".
    A finance record like a payment reversal, with the same gate: fresh login
    and ``Idempotency-Key``. The same key again returns the stored marker
    (``replayed``); another command on a settled refund answers 409
    ``invoice_refund_already_settled``.
    """
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    cancellation = await invoice_settlement_service(request).settle_refund(
        actor,
        action_id,
        invoice_id,
        settled_on=body.settled_on,
        note=body.note,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return invoice_cancellation_response(cancellation)


@router.post(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation/deliveries",
    operation_id="sendInvoiceCancellation",
    response_model=InvoiceDeliveryResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def send_invoice_cancellation(
    action_id: UUID,
    invoice_id: UUID,
    request: Request,
    response: Response,
) -> InvoiceDeliveryResponse:
    """Send the cancellation invoice to the invoice's recipient by mail."""
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    delivery = await invoice_delivery_service(request).send_cancellation(
        actor,
        action_id,
        invoice_id,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation/"
        f"deliveries/{delivery.id}"
    )
    return invoice_delivery_response(delivery)


@router.post(
    (
        "/api/v1/actions/{action_id}/invoices/{invoice_id}/cancellation/"
        "deliveries/{delivery_id}/retry"
    ),
    operation_id="retryInvoiceCancellationDelivery",
    response_model=InvoiceDeliveryResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["invoices"],
)
async def retry_invoice_cancellation_delivery(
    action_id: UUID,
    invoice_id: UUID,
    delivery_id: UUID,
    request: Request,
    response: Response,
) -> InvoiceDeliveryResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    delivery = await invoice_delivery_service(request).retry(
        actor,
        action_id,
        invoice_id,
        delivery_id,
        request_id=request_id(request),
        kind=InvoiceDeliveryKind.INVOICE_CANCELLATION,
    )
    response.headers["Cache-Control"] = "no-store"
    return invoice_delivery_response(delivery)


@router.post(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/deliveries",
    operation_id="sendInvoice",
    response_model=InvoiceDeliveryResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["invoices"],
)
async def send_invoice(
    action_id: UUID,
    invoice_id: UUID,
    request: Request,
    response: Response,
) -> InvoiceDeliveryResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    delivery = await invoice_delivery_service(request).send(
        actor,
        action_id,
        invoice_id,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/invoices/{invoice_id}/deliveries/{delivery.id}"
    )
    return invoice_delivery_response(delivery)


@router.post(
    (
        "/api/v1/actions/{action_id}/invoices/{invoice_id}/deliveries/"
        "{delivery_id}/retry"
    ),
    operation_id="retryInvoiceDelivery",
    response_model=InvoiceDeliveryResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["invoices"],
)
async def retry_invoice_delivery(
    action_id: UUID,
    invoice_id: UUID,
    delivery_id: UUID,
    request: Request,
    response: Response,
) -> InvoiceDeliveryResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    delivery = await invoice_delivery_service(request).retry(
        actor,
        action_id,
        invoice_id,
        delivery_id,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return invoice_delivery_response(delivery)


async def _list_generated_documents(
    *,
    action_id: UUID,
    reference: GeneratedDocumentReference,
    request: Request,
    response: Response,
) -> GeneratedDocumentListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    documents = await document_service(request).list_for_reference(
        actor,
        action_id,
        reference,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return generated_document_list_response(documents)


@router.get(
    "/api/v1/actions/{action_id}/documents",
    operation_id="listActionDocuments",
    response_model=GeneratedDocumentListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["documents"],
)
async def list_action_documents(
    action_id: UUID,
    request: Request,
    response: Response,
) -> GeneratedDocumentListResponse:
    return await _list_generated_documents(
        action_id=action_id,
        reference=GeneratedDocumentReference(
            kind=GeneratedDocumentReferenceKind.ACTION,
            id=action_id,
        ),
        request=request,
        response=response,
    )


@router.get(
    "/api/v1/actions/{action_id}/commitments/{commitment_id}/documents",
    operation_id="listCommitmentDocuments",
    response_model=GeneratedDocumentListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["documents"],
)
async def list_commitment_documents(
    action_id: UUID,
    commitment_id: UUID,
    request: Request,
    response: Response,
) -> GeneratedDocumentListResponse:
    return await _list_generated_documents(
        action_id=action_id,
        reference=GeneratedDocumentReference(
            kind=GeneratedDocumentReferenceKind.COMMITMENT,
            id=commitment_id,
        ),
        request=request,
        response=response,
    )


@router.get(
    "/api/v1/actions/{action_id}/invoices/{invoice_id}/documents",
    operation_id="listInvoiceDocuments",
    response_model=GeneratedDocumentListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["documents"],
)
async def list_invoice_documents(
    action_id: UUID,
    invoice_id: UUID,
    request: Request,
    response: Response,
) -> GeneratedDocumentListResponse:
    return await _list_generated_documents(
        action_id=action_id,
        reference=GeneratedDocumentReference(
            kind=GeneratedDocumentReferenceKind.INVOICE,
            id=invoice_id,
        ),
        request=request,
        response=response,
    )


@router.get(
    "/api/v1/actions/{action_id}/crm/companies/{company_id}/documents",
    operation_id="listCompanyDocuments",
    response_model=GeneratedDocumentListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["documents"],
)
async def list_company_documents(
    action_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
) -> GeneratedDocumentListResponse:
    return await _list_generated_documents(
        action_id=action_id,
        reference=GeneratedDocumentReference(
            kind=GeneratedDocumentReferenceKind.TWENTY_COMPANY,
            id=company_id,
        ),
        request=request,
        response=response,
    )


@router.get(
    "/api/v1/actions/{action_id}/crm/people/{person_id}/documents",
    operation_id="listPersonDocuments",
    response_model=GeneratedDocumentListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["documents"],
)
async def list_person_documents(
    action_id: UUID,
    person_id: UUID,
    request: Request,
    response: Response,
) -> GeneratedDocumentListResponse:
    return await _list_generated_documents(
        action_id=action_id,
        reference=GeneratedDocumentReference(
            kind=GeneratedDocumentReferenceKind.TWENTY_PERSON,
            id=person_id,
        ),
        request=request,
        response=response,
    )


@router.get(
    "/api/v1/actions/{action_id}/documents/{document_id}/download",
    operation_id="downloadGeneratedDocument",
    response_class=Response,
    responses={
        **AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}}
            },
            "description": "Autorisierte unveränderliche PDF-Version",
        },
    },
    tags=["documents"],
)
async def download_generated_document(
    action_id: UUID,
    document_id: UUID,
    request: Request,
    inline: bool = False,
) -> Response:
    actor = await identity_service(request).authenticate(session_token(request))
    download = await document_service(request).download(
        actor,
        action_id,
        document_id,
    )
    filename = download.document.filename or f"Dokument-{document_id}.pdf"
    disposition = "inline" if inline else "attachment"
    return Response(
        content=download.content,
        media_type=download.document.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "X-Content-Type-Options": "nosniff",
            "X-Document-SHA256": download.document.sha256 or "",
            "X-Document-Version": str(download.document.version),
        },
    )


@router.post(
    "/api/v1/actions/{action_id}/copies",
    operation_id="copyCharityAction",
    response_model=CharityActionConfigurationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["actions"],
)
async def copy_charity_action(
    action_id: UUID,
    request: Request,
    body: CopyCharityActionRequest,
    response: Response,
) -> CharityActionConfigurationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action, configuration = await action_service(request).copy(
        actor,
        action_id,
        CopyActionDraft(
            name=body.name,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
            archive_slug=body.archive_slug,
        ),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/actions/{action.id}/configuration"
    return charity_action_configuration_response(action, configuration)


@router.put(
    "/api/v1/actions/{action_id}/goal",
    operation_id="setCharityActionGoal",
    response_model=CharityActionResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_charity_action_goal(
    action_id: UUID,
    request: Request,
    body: SetActionGoalRequest,
    response: Response,
) -> CharityActionResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action = await action_service(request).set_goal(
        actor,
        action_id,
        goal_from_request(body),
        expected_revision=body.revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return charity_action_response(action)


@router.put(
    "/api/v1/actions/{action_id}/capabilities",
    operation_id="setCharityActionCapabilities",
    response_model=CharityActionResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_charity_action_capabilities(
    action_id: UUID,
    request: Request,
    body: SetActionCapabilitiesRequest,
    response: Response,
) -> CharityActionResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action = await action_service(request).set_capabilities(
        actor,
        action_id,
        tuple(ActionCapability(item) for item in body.capabilities),
        expected_revision=body.revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return charity_action_response(action)


@router.put(
    "/api/v1/actions/{action_id}/beneficiaries",
    operation_id="setCharityActionBeneficiaries",
    response_model=CharityActionResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_charity_action_beneficiaries(
    action_id: UUID,
    request: Request,
    body: SetActionBeneficiariesRequest,
    response: Response,
) -> CharityActionResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action = await action_service(request).set_beneficiaries(
        actor,
        action_id,
        beneficiary_drafts(body.beneficiaries),
        expected_revision=body.revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return charity_action_response(action)


@router.post(
    "/api/v1/actions/{action_id}/transitions",
    operation_id="transitionCharityAction",
    response_model=CharityActionResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def transition_charity_action(
    action_id: UUID,
    request: Request,
    body: TransitionCharityActionRequest,
    response: Response,
) -> CharityActionResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    action = await action_service(request).transition(
        actor,
        action_id,
        CharityActionStatus(body.target_status),
        expected_revision=body.revision,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return charity_action_response(action)


@router.get(
    "/api/v1/actions/{action_id}/acquisition/parties",
    operation_id="listAcquisitionParties",
    response_model=AcquisitionPartyListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def list_acquisition_parties(
    action_id: UUID,
    request: Request,
    response: Response,
    filters: Annotated[AcquisitionPageQuery, Query()],
) -> AcquisitionPartyListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    page = await acquisition_service(request).list_parties(
        actor,
        action_id,
        query=filters.q,
        offset=filters.offset,
        limit=filters.limit,
    )
    response.headers["Cache-Control"] = "no-store"
    return AcquisitionPartyListResponse(
        items=[acquisition_party_response(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.post(
    "/api/v1/actions/{action_id}/acquisition/assignments",
    operation_id="createAcquisitionAssignment",
    response_model=AcquisitionAssignmentMutationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    tags=["acquisition"],
)
async def create_acquisition_assignment(
    action_id: UUID,
    request: Request,
    body: CreateAcquisitionAssignmentRequest,
    response: Response,
) -> AcquisitionAssignmentMutationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await assignment_management_service(request).create_proactive(
        actor,
        action_id,
        party_kind=AssignmentPartyKind(body.party_kind),
        party_id=body.party_id,
        acquirer_user_id=body.acquirer_user_id,
        request_id=request_id(request),
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/acquisition/assignments/{result.assignment.id}"
    )
    return AcquisitionAssignmentMutationResponse(
        assignment=acquisition_assignment_response(result.assignment),
        created=result.created,
    )


@router.get(
    "/api/v1/actions/{action_id}/acquisition/assignments/{assignment_id}",
    operation_id="getAcquisitionAssignment",
    response_model=AcquisitionAssignmentDetailsResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def get_acquisition_assignment(
    action_id: UUID,
    assignment_id: UUID,
    request: Request,
    response: Response,
) -> AcquisitionAssignmentDetailsResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    details = await assignment_management_service(request).details(
        actor,
        action_id,
        assignment_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return AcquisitionAssignmentDetailsResponse(
        assignment=acquisition_assignment_response(details.assignment),
        history=[
            acquisition_assignment_history_response(item) for item in details.history
        ],
    )


@router.patch(
    "/api/v1/actions/{action_id}/acquisition/assignments/{assignment_id}",
    operation_id="updateAcquisitionAssignment",
    response_model=AcquisitionAssignmentResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def update_acquisition_assignment(
    action_id: UUID,
    assignment_id: UUID,
    request: Request,
    body: UpdateAcquisitionAssignmentRequest,
    response: Response,
) -> AcquisitionAssignmentResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    assignment = await assignment_management_service(request).update(
        actor,
        action_id,
        assignment_id,
        expected_revision=body.revision,
        status=AssignmentStatus(body.status),
        priority=body.priority,
        next_action=body.next_action,
        due_at=body.due_at,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return acquisition_assignment_response(assignment)


@router.post(
    "/api/v1/actions/{action_id}/acquisition/assignments/{assignment_id}/handover",
    operation_id="handOverAcquisitionAssignment",
    response_model=AcquisitionAssignmentHandoverResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def hand_over_acquisition_assignment(
    action_id: UUID,
    assignment_id: UUID,
    request: Request,
    body: HandOverAcquisitionAssignmentRequest,
    response: Response,
) -> AcquisitionAssignmentHandoverResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    result = await assignment_management_service(request).hand_over(
        actor,
        action_id,
        assignment_id,
        expected_revision=body.revision,
        target_acquirer_user_id=body.target_acquirer_user_id,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/actions/{action_id}/acquisition/assignments/{result.target.id}"
    )
    return acquisition_assignment_handover_response(result)


@router.post(
    "/api/v1/actions/{action_id}/acquisition/sponsor-match",
    operation_id="previewSponsorMatch",
    response_model=SponsorMatchResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def preview_sponsor_match(
    action_id: UUID,
    request: Request,
    body: SponsorDraftRequest,
    response: Response,
) -> SponsorMatchResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    result = await sponsor_matching_service(request).preview(
        actor,
        action_id,
        sponsor_draft(body),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return sponsor_match_response(result)


@router.post(
    "/api/v1/actions/{action_id}/acquisition/sponsor-match/resolve",
    operation_id="resolveSponsorMatch",
    response_model=SponsorResolutionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def resolve_sponsor_match(
    action_id: UUID,
    request: Request,
    body: ResolveSponsorMatchRequest,
    response: Response,
) -> SponsorResolutionResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    resolution = await sponsor_matching_service(request).resolve(
        actor,
        action_id,
        sponsor_draft(body.sponsor),
        expected_status=SponsorMatchStatus(body.expected_status),
        selected_twenty_id=body.selected_twenty_id,
        confirm_existing_assignments=body.confirm_existing_assignments,
        command_id=body.command_id,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return sponsor_resolution_response(resolution)


@router.get(
    "/api/v1/actions/{action_id}/acquisition/parties/count",
    operation_id="countAcquisitionParties",
    response_model=AcquisitionPartyCountResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def count_acquisition_parties(
    action_id: UUID,
    request: Request,
    response: Response,
    filters: Annotated[AcquisitionSearchQuery, Query()],
) -> AcquisitionPartyCountResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    total = await acquisition_service(request).count_parties(
        actor,
        action_id,
        query=filters.q,
    )
    response.headers["Cache-Control"] = "no-store"
    return AcquisitionPartyCountResponse(total=total)


@router.get(
    "/api/v1/actions/{action_id}/acquisition/parties/export",
    operation_id="exportAcquisitionParties",
    response_model=AcquisitionPartyExportResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def export_acquisition_parties(
    action_id: UUID,
    request: Request,
    response: Response,
    filters: Annotated[AcquisitionSearchQuery, Query()],
) -> AcquisitionPartyExportResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    parties = await acquisition_service(request).export_parties(
        actor,
        action_id,
        query=filters.q,
    )
    response.headers["Cache-Control"] = "no-store"
    return AcquisitionPartyExportResponse(
        action_id=action_id,
        items=[acquisition_party_response(item) for item in parties],
    )


@router.get(
    "/api/v1/actions/{action_id}/acquisition/parties/{party_kind}/{party_id}",
    operation_id="getAcquisitionParty",
    response_model=AcquisitionPartyResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def get_acquisition_party(
    action_id: UUID,
    party_kind: CrmPartyKind,
    party_id: UUID,
    request: Request,
    response: Response,
) -> AcquisitionPartyResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    party = await acquisition_service(request).party(
        actor,
        action_id,
        party_kind,
        party_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return acquisition_party_response(party)


@router.get(
    "/api/v1/activity-feed",
    operation_id="getActivityFeed",
    response_model=ActivityFeedResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["activity-feed"],
)
async def get_activity_feed(
    request: Request,
    response: Response,
    filters: Annotated[ActivityFeedQuery, Query()],
) -> ActivityFeedResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    page = await activity_feed_service(request).list(
        actor,
        status=ActivityFeedStatus(filters.status),
        offset=filters.offset,
        limit=filters.limit,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ActivityFeedResponse(
        items=[activity_feed_item_response(item) for item in page.items],
        total=page.total,
        unread_count=page.unread_count,
        offset=page.offset,
        limit=page.limit,
    )


@router.post(
    "/api/v1/activity-feed/read",
    operation_id="markActivityFeedRead",
    response_model=ActivityFeedReadAllResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["activity-feed"],
)
async def mark_activity_feed_read(
    request: Request,
    response: Response,
) -> ActivityFeedReadAllResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    updated = await activity_feed_service(request).mark_all_read(actor)
    response.headers["Cache-Control"] = "private, no-store"
    return ActivityFeedReadAllResponse(updated=updated)


@router.patch(
    "/api/v1/activity-feed/{event_id}",
    operation_id="updateActivityFeedItem",
    response_model=ActivityFeedItemResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["activity-feed"],
)
async def update_activity_feed_item(
    event_id: UUID,
    request: Request,
    body: UpdateActivityFeedItemRequest,
    response: Response,
) -> ActivityFeedItemResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    item = await activity_feed_service(request).set_read_state(
        actor,
        event_id,
        read=body.read,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return activity_feed_item_response(item)


@router.get(
    "/api/v1/actions/{action_id}/acquisition/activity-board",
    operation_id="getAcquisitionActivityBoard",
    response_model=AcquisitionActivityBoardResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def get_acquisition_activity_board(
    action_id: UUID,
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    scope: Literal["personal", "action"] = "personal",
) -> AcquisitionActivityBoardResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    board = await activity_management_service(request).board(
        actor,
        action_id,
        action_wide=scope == "action",
        limit=limit,
    )
    response.headers["Cache-Control"] = "no-store"
    return AcquisitionActivityBoardResponse(
        action_id=board.action_id,
        generated_at=board.generated_at,
        work_items=[
            acquisition_activity_work_item_response(item) for item in board.work_items
        ],
        activities=[
            recorded_acquisition_activity_response(item) for item in board.activities
        ],
    )


@router.post(
    "/api/v1/actions/{action_id}/acquisition/activities",
    operation_id="recordAcquisitionActivity",
    response_model=RecordAcquisitionActivityResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ACTIVITY_RECORD_CONFLICT_RESPONSES,
    tags=["acquisition"],
)
async def record_acquisition_activity(
    action_id: UUID,
    request: Request,
    body: RecordAcquisitionActivityRequest,
    response: Response,
) -> RecordAcquisitionActivityResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    result, item = await activity_management_service(request).record(
        actor,
        action_id,
        party_kind=AssignmentPartyKind(body.party_kind),
        party_id=body.party_id,
        expected_revision=body.revision,
        channel=ActivityChannel(body.channel),
        outcome=ActivityOutcome(body.outcome),
        note=body.note,
        next_action=body.next_action,
        due_on=body.due_on,
        request_id=request_id(request),
        captured_at=body.captured_at,
        # Optional for one release (PLAN §11.1); the PWA queue always sends it.
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    response.headers["Cache-Control"] = "no-store"
    return RecordAcquisitionActivityResponse(
        assignment=acquisition_assignment_response(result.assignment),
        activity=recorded_acquisition_activity_response(item),
        assignment_updated=result.assignment_updated,
        replayed=result.replayed,
    )


@router.get(
    "/api/v1/actions/{action_id}/acquisition/activities",
    operation_id="listAcquisitionActivities",
    response_model=AcquisitionActivityListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def list_acquisition_activities(
    action_id: UUID,
    request: Request,
    response: Response,
    filters: Annotated[PaginationQuery, Query()],
) -> AcquisitionActivityListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    page = await acquisition_service(request).activities(
        actor,
        action_id,
        offset=filters.offset,
        limit=filters.limit,
    )
    response.headers["Cache-Control"] = "no-store"
    return AcquisitionActivityListResponse(
        items=[AcquisitionActivityResponse.model_validate(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.get(
    "/api/v1/actions/{action_id}/acquisition/documents/{document_id}",
    operation_id="getAcquisitionDocument",
    response_model=AcquisitionDocumentResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["acquisition"],
)
async def get_acquisition_document(
    action_id: UUID,
    document_id: UUID,
    request: Request,
    response: Response,
) -> AcquisitionDocumentResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    document = await acquisition_service(request).document(
        actor,
        action_id,
        document_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return AcquisitionDocumentResponse.model_validate(document)


@router.get(
    "/api/v1/invitations/options",
    operation_id="getInvitationOptions",
    response_model=InvitationOptionsResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def invitation_options(
    request: Request,
    response: Response,
) -> InvitationOptionsResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    actions = await invitation_service(request).options(actor)
    response.headers["Cache-Control"] = "no-store"
    return InvitationOptionsResponse.model_validate(
        {
            "actions": actions,
            "roles": [
                {"value": role.value, "label": ROLE_LABELS[role]} for role in ActionRole
            ],
        }
    )


@router.post(
    "/api/v1/invitations",
    operation_id="createInvitation",
    response_model=InvitationDispatchResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["identity"],
)
async def create_invitation(
    request: Request,
    body: CreateInvitationRequest,
    response: Response,
) -> InvitationDispatchResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    dispatched = await invitation_service(request).create(
        actor,
        action_id=body.action_id,
        email=str(body.email),
        display_name=body.display_name,
        role=ActionRole(body.role),
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return InvitationDispatchResponse.model_validate(dispatched)


@router.get(
    "/api/v1/invitations",
    operation_id="listInvitations",
    response_model=InvitationListResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def list_invitations(
    request: Request,
    response: Response,
    action_id: Annotated[UUID | None, Query(alias="actionId")] = None,
    invitation_status: Annotated[
        Literal["pending", "accepted", "expired", "revoked"] | None,
        Query(alias="status"),
    ] = None,
) -> InvitationListResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    invitations = await invitation_service(request).list(
        actor,
        action_id=action_id,
        status=(
            InvitationStatus(invitation_status)
            if invitation_status is not None
            else None
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return InvitationListResponse.model_validate({"items": invitations})


@router.post(
    "/api/v1/invitations/{invitation_id}/resend",
    operation_id="resendInvitation",
    response_model=InvitationDispatchResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["identity"],
)
async def resend_invitation(
    invitation_id: UUID,
    request: Request,
    response: Response,
) -> InvitationDispatchResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    dispatched = await invitation_service(request).resend(
        actor,
        invitation_id,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return InvitationDispatchResponse.model_validate(dispatched)


@router.post(
    "/api/v1/invitations/{invitation_id}/correct-address",
    operation_id="correctInvitationAddress",
    response_model=InvitationDispatchResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["identity"],
)
async def correct_invitation_address(
    invitation_id: UUID,
    body: CorrectInvitationAddressRequest,
    request: Request,
    response: Response,
) -> InvitationDispatchResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    dispatched = await invitation_service(request).correct_address(
        actor,
        invitation_id,
        email=body.email,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return InvitationDispatchResponse.model_validate(dispatched)


@router.post(
    "/api/v1/invitations/accept",
    operation_id="acceptInvitation",
    response_model=InvitationAcceptanceResponse,
    responses=ERROR_RESPONSES,
    tags=["identity"],
)
async def accept_invitation(
    request: Request,
    body: AcceptInvitationRequest,
    response: Response,
) -> InvitationAcceptanceResponse:
    if body.magic_token is not None:
        accepted = await invitation_service(request).accept_magic_link(
            body.magic_token,
            request_id=request_id(request),
        )
    else:
        accepted = await invitation_service(request).accept_code(
            str(body.email),
            cast(str, body.code),
            request_id=request_id(request),
        )
    grant = await authentication_service(request).issue_for_user(
        accepted.user_id,
        device_hint=device_hint(request),
        request_id=request_id(request),
    )
    set_session_cookie(response, grant)
    return InvitationAcceptanceResponse(
        status="accepted",
        action_id=accepted.action_id,
        action_name=accepted.action_name,
        role=accepted.role.value,
    )


@router.delete(
    "/api/v1/invitations/{invitation_id}",
    operation_id="revokeInvitation",
    response_model=InvitationRevocationResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["identity"],
)
async def revoke_invitation(
    invitation_id: UUID,
    request: Request,
    response: Response,
) -> InvitationRevocationResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    await invitation_service(request).revoke(
        actor,
        invitation_id,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return InvitationRevocationResponse(status="revoked")


@router.post(
    "/api/v1/identity/members/{user_id}/email-change",
    operation_id="createMemberEmailChange",
    response_model=EmailChangeDispatchResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["identity"],
)
async def create_member_email_change(
    user_id: UUID,
    body: CreateEmailChangeRequest,
    request: Request,
    response: Response,
) -> EmailChangeDispatchResponse:
    actor = await identity_service(request).authenticate_fresh(session_token(request))
    dispatched = await email_change_service(request).request(
        actor,
        user_id,
        new_email=body.new_email,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return EmailChangeDispatchResponse.model_validate(dispatched)


@router.post(
    "/api/v1/email-changes/confirm",
    operation_id="confirmEmailChange",
    response_model=EmailChangeConfirmationResponse,
    responses=ERROR_RESPONSES,
    tags=["identity"],
)
async def confirm_email_change(
    body: ConfirmEmailChangeRequest,
    request: Request,
    response: Response,
) -> EmailChangeConfirmationResponse:
    if body.magic_token is not None:
        confirmed = await email_change_service(request).confirm_magic(
            body.magic_token,
            request_id=request_id(request),
        )
    else:
        confirmed = await email_change_service(request).confirm_code(
            str(body.email),
            cast(str, body.code),
            request_id=request_id(request),
        )
    response.headers["Cache-Control"] = "no-store"
    return EmailChangeConfirmationResponse.model_validate(confirmed)


def delivery_start_point_response(
    start: DeliveryStartPoint | None,
) -> DeliveryStartPointResponse | None:
    if start is None:
        return None
    return DeliveryStartPointResponse(
        label=start.label,
        address=start.address,
        lat=None if start.point is None else float(start.point.lat),
        lon=None if start.point is None else float(start.point.lon),
        locating=start.locating,
    )


def requested_start_point(
    body: DeliveryConfigurationRequest, current: DeliveryConfiguration
) -> DeliveryStartPoint | None:
    """Absent keeps the stored start point; null removes it."""

    if "start_point" not in body.model_fields_set:
        return current.start
    start = body.start_point
    if start is None:
        return None
    return DeliveryStartPoint(
        label=start.label,
        address=start.address,
        point=(
            None
            if start.lat is None or start.lon is None
            else GeoPoint.parse(start.lat, start.lon)
        ),
    )


def delivery_configuration_response(
    configuration: DeliveryConfiguration,
    *,
    available_only: bool = False,
) -> DeliveryConfigurationResponse:
    return DeliveryConfigurationResponse(
        action_id=configuration.action_id,
        enabled=configuration.enabled,
        timezone=configuration.timezone,
        revision=configuration.revision,
        # The start point is for managers and drivers, not the order form.
        start_point=(
            None
            if available_only
            else delivery_start_point_response(configuration.start)
        ),
        windows=[
            DeliveryWindowResponse.model_validate(window)
            for window in configuration.windows
            if not available_only
            or (
                configuration.enabled
                and not window.retired
                and window.bounds(configuration.timezone)[0]
                > datetime.now(timezone.utc)
            )
        ],
    )


@router.get(
    "/api/v1/actions/{action_id}/delivery-configuration",
    operation_id="getDeliveryConfiguration",
    response_model=DeliveryConfigurationResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def get_delivery_configuration(
    action_id: UUID, request: Request, response: Response
) -> DeliveryConfigurationResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    service = cast(DeliveryService, request.app.state.delivery_service)
    result = await service.get(actor, action_id)
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_configuration_response(result)


@router.put(
    "/api/v1/actions/{action_id}/delivery-configuration",
    operation_id="saveDeliveryConfiguration",
    response_model=DeliveryConfigurationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def save_delivery_configuration(
    action_id: UUID,
    body: DeliveryConfigurationRequest,
    request: Request,
    response: Response,
) -> DeliveryConfigurationResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    service = cast(DeliveryService, request.app.state.delivery_service)
    current = await service.get(actor, action_id)
    current_ids = {window.id for window in current.windows}
    if any(
        window.id is not None and window.id not in current_ids
        for window in body.windows
    ):
        raise DomainInvariantError(
            "delivery_window_action_mismatch",
            "Bitte nur bestehende Fenster dieser Aktion auswählen. Neue Fenster erhalten ihre ID beim Speichern.",
        )
    # Existing windows may echo the stored switch (ignored); a new window
    # cannot start full, so the client must not believe it created one.
    if any(window.id is None and window.fully_booked for window in body.windows):
        raise DomainInvariantError(
            "delivery_window_full_new",
            "Neue Fenster sind zunächst buchbar; „Ausgebucht“ danach im Tab setzen.",
        )
    configuration = DeliveryConfiguration(
        action_id=action_id,
        enabled=body.enabled,
        timezone=body.timezone,
        revision=body.expected_revision,
        start=requested_start_point(body, current),
        windows=tuple(
            DeliveryWindow(
                id=window.id or uuid4(),
                action_id=action_id,
                delivery_on=window.delivery_on,
                starts_at=window.starts_at,
                ends_at=window.ends_at,
                retired=window.retired,
            )
            for window in body.windows
        ),
    )
    result = await service.save(actor, configuration, request_id=request_id(request))
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_configuration_response(result)


@router.put(
    "/api/v1/actions/{action_id}/delivery-windows/{window_id}/fully-booked",
    operation_id="setDeliveryWindowFullyBooked",
    response_model=DeliveryConfigurationResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_delivery_window_fully_booked(
    action_id: UUID,
    window_id: UUID,
    body: DeliveryWindowFullyBookedRequest,
    request: Request,
    response: Response,
) -> DeliveryConfigurationResponse:
    """Mark a delivery window as "ausgebucht" or open it again."""
    actor = await identity_service(request).authenticate(session_token(request))
    service = cast(DeliveryService, request.app.state.delivery_service)
    result = await service.set_fully_booked(
        actor,
        action_id,
        window_id,
        fully_booked=body.fully_booked,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_configuration_response(result)


# ---------- Delivery day board ----------


def delivery_board_service(request: Request) -> DeliveryBoardService:
    return cast(DeliveryBoardService, request.app.state.delivery_board_service)


def delivery_drop_response(drop: DeliveryDrop) -> DeliveryDropResponse:
    return DeliveryDropResponse(
        commitment_id=drop.commitment_id,
        window_id=drop.window_id,
        buyer_name=drop.buyer_name,
        quantities=[
            DeliveryDropQuantityResponse(unit=item.unit, quantity=item.quantity)  # type: ignore[arg-type]
            for item in drop.quantities
        ],
        total_boxes=drop.total_boxes,
        address=(
            DeliveryDropAddressResponse(
                recipient_name=drop.address.recipient_name,
                street_line1=drop.address.street_line_1,
                postal_code=drop.address.postal_code,
                city=drop.address.city,
            )
            if drop.address
            else None
        ),
        contact=(
            DeliveryDropContactResponse(
                name=drop.contact.name,
                phone=drop.contact.phone,
                driver_note=drop.contact.driver_note,
            )
            if drop.contact
            else None
        ),
        state=drop.state.value,
        state_changed_at=drop.state_changed_at,
        state_changed_by_name=drop.state_changed_by_name,
        driver_user_id=drop.driver_user_id,
        driver_name=drop.driver_name,
        revision=drop.revision,
        missed_at_closure=drop.missed_at_closure,
        order_status=drop.order_status,  # type: ignore[arg-type]
    )


def delivery_board_response(board: DeliveryBoard) -> DeliveryBoardResponse:
    return DeliveryBoardResponse(
        action_id=board.action_id,
        action_name=board.action_name,
        timezone=board.timezone,
        day=board.day,
        days=list(board.days),
        manager=board.manager,
        windows=[
            DeliveryBoardWindowResponse(
                id=window.id,
                starts_at=window.starts_at,
                ends_at=window.ends_at,
                retired=window.retired,
                fully_booked=window.fully_booked,
                closure=(
                    DeliveryWindowClosureResponse(
                        closed_at=window.closure.closed_at,
                        closed_by_name=window.closure.closed_by_name,
                        missed_count=window.closure.missed_count,
                    )
                    if window.closure
                    else None
                ),
                drops=[delivery_drop_response(drop) for drop in window.drops],
            )
            for window in board.windows
        ],
        drivers=[
            DeliveryBoardDriverResponse(
                user_id=driver.user_id, display_name=driver.display_name
            )
            for driver in board.drivers
        ],
        follow_up_tasks=board.follow_up_tasks,
    )


@router.get(
    "/api/v1/actions/{action_id}/delivery-board",
    operation_id="getDeliveryBoard",
    response_model=DeliveryBoardResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def get_delivery_board(
    action_id: UUID,
    request: Request,
    response: Response,
    day: date | None = None,
) -> DeliveryBoardResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    board = await delivery_board_service(request).board(
        actor, action_id, day=day, viewed_at=datetime.now(timezone.utc)
    )
    # Drivers' addresses and phones never land in any cache.
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_board_response(board)


@router.put(
    "/api/v1/actions/{action_id}/commitments/{commitment_id}/delivery-state",
    operation_id="setDeliveryState",
    response_model=DeliveryDropResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_delivery_state(
    action_id: UUID,
    commitment_id: UUID,
    body: DeliveryStateRequest,
    request: Request,
    response: Response,
) -> DeliveryDropResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    drop = await delivery_board_service(request).set_state(
        actor,
        action_id,
        commitment_id,
        delivered=body.delivered,
        missed=body.missed,
        expected_revision=body.expected_revision,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_drop_response(drop)


@router.put(
    "/api/v1/actions/{action_id}/delivery-board/drivers",
    operation_id="assignDeliveryDriver",
    response_model=DeliveryDriverAssignmentResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def assign_delivery_driver(
    action_id: UUID,
    body: DeliveryDriverAssignmentRequest,
    request: Request,
) -> DeliveryDriverAssignmentResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    changed = await delivery_board_service(request).assign_driver(
        actor,
        action_id,
        commitment_ids=tuple(body.commitment_ids),
        driver_user_id=body.driver_user_id,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    return DeliveryDriverAssignmentResponse(changed=changed)


@router.post(
    "/api/v1/actions/{action_id}/delivery-windows/{window_id}/closure",
    operation_id="closeDeliveryWindow",
    response_model=DeliveryWindowClosureResultResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def close_delivery_window(
    action_id: UUID, window_id: UUID, request: Request
) -> DeliveryWindowClosureResultResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    service = delivery_board_service(request)
    missed = await service.close_window(
        actor,
        action_id,
        window_id,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    return DeliveryWindowClosureResultResponse(
        missed_count=missed,
        follow_up="tasks" if service.follow_up_tasks else "board",
    )


@router.delete(
    "/api/v1/actions/{action_id}/delivery-windows/{window_id}/closure",
    operation_id="reopenDeliveryWindow",
    response_model=DeliveryWindowReopenResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def reopen_delivery_window(
    action_id: UUID, window_id: UUID, request: Request
) -> DeliveryWindowReopenResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    reopened = await delivery_board_service(request).reopen_window(
        actor,
        action_id,
        window_id,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    return DeliveryWindowReopenResponse(reopened_count=reopened)


# ---------- Delivery tours ----------


def delivery_tour_service(request: Request) -> DeliveryTourService:
    return cast(DeliveryTourService, request.app.state.delivery_tour_service)


def delivery_tour_window_response(window: TourWindow) -> DeliveryTourWindowResponse:
    return DeliveryTourWindowResponse(
        window_id=window.window_id,
        starts_at=window.starts_at,
        ends_at=window.ends_at,
        closed=window.closed,
        stops=[delivery_tour_stop_response(stop) for stop in window.stops],
    )


def delivery_tour_stop_response(stop: TourStopView) -> DeliveryTourStopResponse:
    return DeliveryTourStopResponse(
        drop=delivery_drop_response(stop.drop),
        base_rank=stop.base_rank,
        driver_rank=stop.driver_rank,
        effective_rank=stop.effective_rank,
        new_for_driver=stop.new_for_driver,
        lat=None if stop.point is None else float(stop.point.lat),
        lon=None if stop.point is None else float(stop.point.lon),
    )


def map_tiles_response(tiles: MapTiles) -> MapTilesResponse:
    return MapTilesResponse(tile_url=tiles.tile_url, attribution=tiles.attribution)


def delivery_tour_response(tour: DriverTour) -> DeliveryTourResponse:
    return DeliveryTourResponse(
        driver_user_id=tour.driver_user_id,
        driver_name=tour.driver_name,
        day=tour.day,
        revision=tour.revision,
        driver_ordered_at=tour.driver_ordered_at,
        windows=[delivery_tour_window_response(window) for window in tour.windows],
    )


def day_tours_response(tours: DayTours, tiles: MapTiles) -> DeliveryDayToursResponse:
    return DeliveryDayToursResponse(
        action_id=tours.action_id,
        action_name=tours.action_name,
        timezone=tours.timezone,
        day=tours.day,
        days=list(tours.days),
        unassigned=[delivery_tour_window_response(w) for w in tours.unassigned],
        tours=[delivery_tour_response(tour) for tour in tours.tours],
        drivers=[
            DeliveryBoardDriverResponse(
                user_id=driver.user_id, display_name=driver.display_name
            )
            for driver in tours.drivers
        ],
        start_point=delivery_start_point_response(tours.start),
        map=map_tiles_response(tiles),
    )


def my_tour_response(mine: MyTour, tiles: MapTiles) -> MyTourResponse:
    return MyTourResponse(
        action_id=mine.action_id,
        action_name=mine.action_name,
        timezone=mine.timezone,
        days=list(mine.days),
        tour=delivery_tour_response(mine.tour) if mine.tour else None,
        start_point=delivery_start_point_response(mine.start),
        map=map_tiles_response(tiles),
    )


@router.get(
    "/api/v1/actions/{action_id}/delivery-board/tours",
    operation_id="getDeliveryTours",
    response_model=DeliveryDayToursResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def get_delivery_tours(
    action_id: UUID,
    request: Request,
    response: Response,
    day: date | None = None,
) -> DeliveryDayToursResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    service = delivery_tour_service(request)
    tours = await service.day_tours(
        actor, action_id, day=day, viewed_at=datetime.now(timezone.utc)
    )
    response.headers["Cache-Control"] = "private, no-store"
    return day_tours_response(tours, service.tiles)


@router.put(
    "/api/v1/actions/{action_id}/delivery-board/tours/{driver_user_id}/order",
    operation_id="saveDeliveryTourOrder",
    response_model=DeliveryTourResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def save_delivery_tour_order(
    action_id: UUID,
    driver_user_id: UUID,
    body: DeliveryTourOrderRequest,
    request: Request,
    response: Response,
) -> DeliveryTourResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    tour = await delivery_tour_service(request).save_base_order(
        actor,
        action_id,
        driver_user_id,
        day=body.day,
        ordered_ids=body.commitment_ids,
        expected_revision=body.expected_revision,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_tour_response(tour)


@router.delete(
    "/api/v1/actions/{action_id}/delivery-board/tours/{driver_user_id}/driver-order",
    operation_id="discardDeliveryDriverOrder",
    response_model=DeliveryTourResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def discard_delivery_driver_order(
    action_id: UUID,
    driver_user_id: UUID,
    day: date,
    request: Request,
    response: Response,
) -> DeliveryTourResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    tour = await delivery_tour_service(request).discard_driver_order(
        actor,
        action_id,
        driver_user_id,
        day=day,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_tour_response(tour)


@router.get(
    "/api/v1/actions/{action_id}/my-tour",
    operation_id="getMyTour",
    response_model=MyTourResponse,
    responses=AUTHENTICATED_ERROR_RESPONSES,
    tags=["actions"],
)
async def get_my_tour(
    action_id: UUID,
    request: Request,
    response: Response,
    day: date | None = None,
) -> MyTourResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    service = delivery_tour_service(request)
    mine = await service.my_tour(
        actor, action_id, day=day, viewed_at=datetime.now(timezone.utc)
    )
    response.headers["Cache-Control"] = "private, no-store"
    return my_tour_response(mine, service.tiles)


@router.post(
    "/api/v1/actions/{action_id}/my-tour/reads",
    operation_id="recordMyTourReads",
    status_code=204,
    response_class=Response,
    responses=MY_TOUR_READS_RESPONSES,
    tags=["actions"],
)
async def record_my_tour_reads(
    action_id: UUID, body: MyTourReadsRequest, request: Request
) -> Response:
    """Reads of "Meine Tour" the device showed offline (spec §10): each is
    audited at its read time; windows without an own stop are ignored."""
    actor = await identity_service(request).authenticate(session_token(request))
    await delivery_tour_service(request).record_reads(
        actor,
        action_id,
        [TourRead(read.window_id, read.read_at) for read in body.reads],
        received_at=datetime.now(timezone.utc),
    )
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.put(
    "/api/v1/actions/{action_id}/my-tour/order",
    operation_id="saveMyTourOrder",
    response_model=DeliveryTourResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def save_my_tour_order(
    action_id: UUID,
    body: DeliveryTourOrderRequest,
    request: Request,
    response: Response,
) -> DeliveryTourResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    tour = await delivery_tour_service(request).save_driver_order(
        actor,
        action_id,
        day=body.day,
        ordered_ids=body.commitment_ids,
        expected_revision=body.expected_revision,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_tour_response(tour)


@router.put(
    "/api/v1/actions/{action_id}/delivery-geo/{commitment_id}",
    operation_id="setDeliveryPin",
    response_model=DeliveryTourStopResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    tags=["actions"],
)
async def set_delivery_pin(
    action_id: UUID,
    commitment_id: UUID,
    body: DeliveryPinRequest,
    request: Request,
    response: Response,
) -> DeliveryTourStopResponse:
    """The manager's pin for a stop whose address was not found (spec §6.4).

    409 only when concurrent tour writes exhaust the serialization retries.
    """
    actor = await identity_service(request).authenticate(session_token(request))
    stop = await delivery_tour_service(request).set_pin(
        actor,
        action_id,
        commitment_id,
        lat=body.lat,
        lon=body.lon,
        request_id=request_id(request),
        occurred_at=datetime.now(timezone.utc),
    )
    response.headers["Cache-Control"] = "private, no-store"
    return delivery_tour_stop_response(stop)
