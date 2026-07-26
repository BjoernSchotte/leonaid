"""FastAPI route adapter for platform application services."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from leonaid.application.acquisition import (
    AcquisitionParty,
    AcquisitionPolicyService,
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
from leonaid.application.actions import (
    BeneficiaryDraft,
    CharityActionService,
    CopyActionDraft,
    CreateActionDraft,
    CreateActionFromTemplateDraft,
    PublicActionRoute,
    UpdateActionDetailsDraft,
)
from leonaid.application.errors import DependencyUnavailable
from leonaid.application.identity import ROLE_LABELS, IdentityQueryService
from leonaid.application.invitations import InvitationService
from leonaid.application.platform import PlatformApplicationService
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
)
from leonaid.domain.identity import ActionRole
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.entrypoints.fastapi.schemas import (
    AcceptInvitationRequest,
    ActionGoalRequest,
    ActionGoalResponse,
    ActionManagementResponse,
    ActionTemplateListResponse,
    ActionTemplateSnapshotResponse,
    ActionTemplateSummaryResponse,
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
    AssignedAcquirerResponse,
    AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    AUTHENTICATED_ERROR_RESPONSES,
    BeneficiaryDraftRequest,
    CompleteFreshLoginRequest,
    CompleteLoginRequest,
    ConfiguredOfferingResponse,
    CopyCharityActionRequest,
    CreateAcquisitionAssignmentRequest,
    CreateActionFromTemplateRequest,
    CreateInvitationRequest,
    CreateCharityActionRequest,
    CurrentIdentityResponse,
    ERROR_RESPONSES,
    FreshLoginStatusResponse,
    HandOverAcquisitionAssignmentRequest,
    InvitationAcceptanceResponse,
    InvitationDispatchResponse,
    InvitationOptionsResponse,
    InvitationRevocationResponse,
    LoginDispatchResponse,
    LogoutResponse,
    PaginationQuery,
    PlatformInformationResponse,
    PlatformStatusResponse,
    PublicActionRouteResponse,
    PublicCharityActionResponse,
    ReadinessResponse,
    RecordAcquisitionActivityRequest,
    RecordAcquisitionActivityResponse,
    RecordedAcquisitionActivityResponse,
    RequestLoginRequest,
    SessionAuthenticationResponse,
    SessionRevocationResponse,
    BeneficiaryResponse,
    CharityActionResponse,
    CharityActionConfigurationResponse,
    OrderFormConfigurationResponse,
    SetActionBeneficiariesRequest,
    SetActionCapabilitiesRequest,
    SetActionGoalRequest,
    SetActionPublicationRequest,
    SetResponsibleAdministratorsRequest,
    ResolveSponsorMatchRequest,
    SponsorDraftRequest,
    SponsorMatchResponse,
    SponsorResolutionResponse,
    TransitionCharityActionRequest,
    UpdateAcquisitionAssignmentRequest,
    UpdateActionDetailsRequest,
)

router = APIRouter()


def platform_service(request: Request) -> PlatformApplicationService:
    return cast(PlatformApplicationService, request.app.state.platform_service)


def identity_service(request: Request) -> IdentityQueryService:
    return cast(IdentityQueryService, request.app.state.identity_service)


def invitation_service(request: Request) -> InvitationService:
    return cast(InvitationService, request.app.state.invitation_service)


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


def action_service(request: Request) -> CharityActionService:
    return cast(CharityActionService, request.app.state.action_service)


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


def charity_action_response(action: CharityAction) -> CharityActionResponse:
    return CharityActionResponse(
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


def public_action_route_response(
    route: PublicActionRoute,
) -> PublicActionRouteResponse:
    action = route.action
    return PublicActionRouteResponse(
        route_kind=route.route_kind.value,
        route_value=route.route_value,
        route_path=route.route_path,
        canonical_path=route.canonical_path,
        availability=route.availability.value,
        submissions_allowed=route.submissions_allowed,
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
                pieces_per_unit=item.definition.pieces_per_unit,
                unit_price_minor=item.definition.unit_price_minor,
                currency=item.definition.currency,
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
    response.headers["Cache-Control"] = "public, max-age=15, stale-while-revalidate=30"
    return public_action_route_response(route)


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
    return public_action_route_response(route)


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
    return CurrentIdentityResponse.model_validate(result)


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
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
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


@router.post(
    "/api/v1/actions",
    operation_id="createCharityAction",
    response_model=CharityActionResponse,
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
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
) -> AcquisitionActivityBoardResponse:
    actor = await identity_service(request).authenticate(session_token(request))
    board = await activity_management_service(request).board(
        actor,
        action_id,
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
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
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
    )
    response.headers["Cache-Control"] = "no-store"
    return RecordAcquisitionActivityResponse(
        assignment=acquisition_assignment_response(result.assignment),
        activity=recorded_acquisition_activity_response(item),
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
