"""HTTP adapter for push notifications of the PWA (spec §10, ADR-0017).

Every member manages only their own devices and switches. While the flag
``pwa.push`` is off the calls answer 404, except removing a device.
"""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import Field

from leonaid.application.identity import AuthenticatedIdentity, IdentityQueryService
from leonaid.application.push import PushConfiguration, PushService
from leonaid.domain.push import PushKind
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.entrypoints.fastapi.schemas import AUTHENTICATED_CONFLICT_ERROR_RESPONSES
from leonaid.platform.http import TransportModel

router = APIRouter(
    prefix="/api/v1/push",
    tags=["push"],
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
)

PushKindValue = Literal["follow_ups", "feed", "tasks", "delivery"]


class PushKindResponse(TransportModel):
    kind: PushKindValue
    enabled: bool


class PushConfigurationResponse(TransportModel):
    # False: the operator has set no VAPID key.
    configured: bool
    # Application server key for PushManager.subscribe, base64url.
    public_key: str | None
    # The kinds this member can switch on.
    kinds: list[PushKindResponse]


class PushSubscriptionKeys(TransportModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SavePushSubscriptionRequest(TransportModel):
    """A browser's PushSubscription, as its toJSON() gives it."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushSubscriptionKeys


class PushSubscriptionResponse(TransportModel):
    id: UUID


class PushPreferenceRequest(TransportModel):
    kind: PushKindValue
    enabled: bool = Field(strict=True)


class UpdatePushPreferencesRequest(TransportModel):
    preferences: list[PushPreferenceRequest] = Field(min_length=1, max_length=4)


class SendTestPushRequest(TransportModel):
    subscription_id: UUID


class PushTestResponse(TransportModel):
    status: Literal["queued"]


def _service(request: Request) -> PushService:
    return cast(PushService, request.app.state.push_service)


async def _member(request: Request, response: Response) -> AuthenticatedIdentity:
    response.headers["Cache-Control"] = "no-store"
    identity = cast(IdentityQueryService, request.app.state.identity_service)
    return await identity.authenticate_session(request.cookies.get(SESSION_COOKIE_NAME))


def _configuration(configuration: PushConfiguration) -> PushConfigurationResponse:
    return PushConfigurationResponse(
        configured=configuration.configured,
        public_key=configuration.public_key,
        kinds=[
            PushKindResponse(kind=kind.value, enabled=enabled)
            for kind, enabled in configuration.kinds
        ],
    )


@router.get(
    "/configuration",
    operation_id="getPushConfiguration",
    response_model=PushConfigurationResponse,
)
async def get_push_configuration(
    request: Request, response: Response
) -> PushConfigurationResponse:
    member = await _member(request, response)
    return _configuration(await _service(request).configuration(member.principal))


@router.put(
    "/subscriptions",
    operation_id="savePushSubscription",
    response_model=PushSubscriptionResponse,
)
async def save_push_subscription(
    request: Request, response: Response, body: SavePushSubscriptionRequest
) -> PushSubscriptionResponse:
    member = await _member(request, response)
    subscription_id = await _service(request).subscribe(
        member.principal,
        session_id=member.session.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=request.headers.get("user-agent", ""),
        request_id=cast(str, request.state.request_id),
    )
    return PushSubscriptionResponse(id=subscription_id)


@router.delete(
    "/subscriptions/{subscription_id}",
    operation_id="deletePushSubscription",
    status_code=204,
)
async def delete_push_subscription(
    subscription_id: UUID, request: Request, response: Response
) -> Response:
    member = await _member(request, response)
    await _service(request).unsubscribe(
        member.principal,
        subscription_id,
        request_id=cast(str, request.state.request_id),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.put(
    "/preferences",
    operation_id="updatePushPreferences",
    response_model=PushConfigurationResponse,
)
async def update_push_preferences(
    request: Request, response: Response, body: UpdatePushPreferencesRequest
) -> PushConfigurationResponse:
    member = await _member(request, response)
    configuration = await _service(request).set_preferences(
        member.principal,
        {PushKind(item.kind): item.enabled for item in body.preferences},
        request_id=cast(str, request.state.request_id),
    )
    return _configuration(configuration)


@router.post(
    "/test",
    operation_id="sendTestPush",
    response_model=PushTestResponse,
    status_code=202,
)
async def send_test_push(
    request: Request, response: Response, body: SendTestPushRequest
) -> PushTestResponse:
    member = await _member(request, response)
    await _service(request).send_test(member.principal, body.subscription_id)
    return PushTestResponse(status="queued")
