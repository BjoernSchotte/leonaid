"""FastAPI route adapter for platform application services."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request, Response, status

from leonaid.application.platform import PlatformApplicationService

router = APIRouter()


def platform_service(request: Request) -> PlatformApplicationService:
    return cast(PlatformApplicationService, request.app.state.platform_service)


@router.get("/health/live")
async def live(request: Request) -> object:
    return platform_service(request).live()


@router.get("/health/ready")
async def ready(request: Request, response: Response) -> object:
    result = await platform_service(request).readiness()
    if result.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/api/v1/platform")
async def information(request: Request) -> object:
    return platform_service(request).information()
