"""FastAPI route adapter for platform application services."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from leonaid.application.identity import ROLE_LABELS, IdentityQueryService
from leonaid.application.invitations import InvitationService
from leonaid.application.platform import PlatformApplicationService
from leonaid.domain.identity import ActionRole
from leonaid.entrypoints.fastapi.schemas import (
    AcceptInvitationRequest,
    AUTHENTICATED_ERROR_RESPONSES,
    CreateInvitationRequest,
    CurrentIdentityResponse,
    ERROR_RESPONSES,
    InvitationAcceptanceResponse,
    InvitationDispatchResponse,
    InvitationOptionsResponse,
    InvitationRevocationResponse,
    PlatformInformationResponse,
    PlatformStatusResponse,
    ReadinessResponse,
)

router = APIRouter()


def platform_service(request: Request) -> PlatformApplicationService:
    return cast(PlatformApplicationService, request.app.state.platform_service)


def identity_service(request: Request) -> IdentityQueryService:
    return cast(IdentityQueryService, request.app.state.identity_service)


def invitation_service(request: Request) -> InvitationService:
    return cast(InvitationService, request.app.state.invitation_service)


def session_token(request: Request) -> str | None:
    return request.cookies.get("leonaid_session")


def request_id(request: Request) -> str:
    return cast(str, request.state.request_id)


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
    actor = await identity_service(request).authenticate(session_token(request))
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
    response.headers["Cache-Control"] = "no-store"
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
    actor = await identity_service(request).authenticate(session_token(request))
    await invitation_service(request).revoke(
        actor,
        invitation_id,
        request_id=request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return InvitationRevocationResponse(status="revoked")
