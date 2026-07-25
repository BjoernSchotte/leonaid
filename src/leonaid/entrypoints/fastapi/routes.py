"""FastAPI route adapter for platform application services."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request, Response, status

from leonaid.application.platform import PlatformApplicationService
from leonaid.entrypoints.fastapi.schemas import (
    ERROR_RESPONSES,
    PlatformInformationResponse,
    PlatformStatusResponse,
    ReadinessResponse,
)

router = APIRouter()


def platform_service(request: Request) -> PlatformApplicationService:
    return cast(PlatformApplicationService, request.app.state.platform_service)


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
