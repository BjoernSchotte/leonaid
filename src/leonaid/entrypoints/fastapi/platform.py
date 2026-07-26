"""FastAPI composition root and transport-level policies."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from leonaid.adapters.http_readiness import HttpReadinessProbe
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.postgres.acquisition import (
    AsyncpgAcquisitionPolicyRepository,
)
from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.identity import AsyncpgIdentityRepository
from leonaid.adapters.postgres.invitations import AsyncpgInvitationRepository
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.readiness import PostgresReadinessProbe
from leonaid.adapters.postgres.sessions import AsyncpgSessionRepository
from leonaid.adapters.twenty.gateway import (
    TwentyCrmGateway,
    TwentyGatewaySettings,
)
from leonaid.application.acquisition import AcquisitionPolicyService
from leonaid.application.activities import AcquisitionActivityService
from leonaid.application.assignments import AssignmentManagementService
from leonaid.application.actions import CharityActionService
from leonaid.application.commitments import CommitmentService
from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    DependencyUnavailable,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.application.identity import IdentityQueryService
from leonaid.application.invitations import InvitationService
from leonaid.application.platform import PlatformApplicationService
from leonaid.application.sessions import SessionService
from leonaid.application.sponsor_matching import SponsorMatchingService
from leonaid.configuration import Settings, load_settings
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.platform import PlatformIdentity
from leonaid.entrypoints.fastapi.routes import router

REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}\Z")


def request_id_for(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else str(uuid4())


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "requestId": request_id_for(request),
            }
        },
    )


def build_service(settings: Settings) -> PlatformApplicationService:
    identity = PlatformIdentity(
        service=settings.service_name,
        release=settings.service_version,
        api_version=settings.api_version,
    )
    return PlatformApplicationService(
        identity=identity,
        probes=(
            PostgresReadinessProbe(
                settings.core_database_url.get_secret_value(),
            ),
            HttpReadinessProbe("twenty", str(settings.twenty_health_url)),
            HttpReadinessProbe("rustfs", str(settings.rustfs_health_url)),
        ),
    )


def create_app(configured_settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = configured_settings or load_settings()
        application.state.settings_summary = settings.safe_summary()
        application.state.platform_service = build_service(settings)
        pool = await create_pool(settings.core_database_url.get_secret_value())
        application.state.identity_service = IdentityQueryService(
            AsyncpgIdentityRepository(pool),
            fresh_login_window=timedelta(seconds=settings.fresh_login_seconds),
        )
        application.state.action_service = CharityActionService(
            AsyncpgCharityActionRepository(pool)
        )
        application.state.commitment_service = CommitmentService(
            AsyncpgCommitmentRepository(pool)
        )
        mail_payload = SecureMailPayload(
            settings.mail_payload_secret.get_secret_value()
        )
        application.state.invitation_service = InvitationService(
            AsyncpgInvitationRepository(pool),
            mail_payload,
            hmac_secret=settings.invitation_hmac_secret.get_secret_value(),
            public_base_url=str(settings.public_base_url),
            ttl=timedelta(minutes=settings.invitation_ttl_minutes),
        )
        application.state.session_service = SessionService(
            AsyncpgSessionRepository(pool),
            mail_payload,
            hmac_secret=settings.invitation_hmac_secret.get_secret_value(),
            public_base_url=str(settings.public_base_url),
            challenge_ttl=timedelta(minutes=settings.login_challenge_ttl_minutes),
        )
        crm_gateway: TwentyCrmGateway | None = None
        if settings.twenty_integration_api_key is not None:
            crm_gateway = TwentyCrmGateway(
                TwentyGatewaySettings(
                    base_url=str(settings.twenty_base_url),
                    api_key=settings.twenty_integration_api_key,
                )
            )
            acquisition_repository = AsyncpgAcquisitionPolicyRepository(pool)
            application.state.acquisition_service = AcquisitionPolicyService(
                acquisition_repository,
                crm_gateway,
            )
            application.state.sponsor_matching_service = SponsorMatchingService(
                acquisition_repository,
                crm_gateway,
            )
            application.state.assignment_management_service = (
                AssignmentManagementService(
                    acquisition_repository,
                    crm_gateway,
                )
            )
            application.state.activity_management_service = AcquisitionActivityService(
                acquisition_repository,
                crm_gateway,
            )
        else:
            application.state.acquisition_service = None
            application.state.sponsor_matching_service = None
            application.state.assignment_management_service = None
            application.state.activity_management_service = None
        try:
            yield
        finally:
            if crm_gateway is not None:
                await crm_gateway.close()
            await pool.close()

    application = FastAPI(
        title="LeonAid Core",
        version="0.0.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def correlate_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = (
            supplied if REQUEST_ID.fullmatch(supplied) else str(uuid4())
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(ApplicationError)
    async def application_error(
        request: Request,
        error: ApplicationError,
    ) -> JSONResponse:
        status_code = 400
        if isinstance(error, AuthenticationRequired):
            status_code = 401
        elif isinstance(error, PermissionDenied):
            status_code = 403
        elif isinstance(error, ResourceNotFound):
            status_code = 404
        elif isinstance(error, Conflict):
            status_code = 409
        elif isinstance(error, DependencyUnavailable):
            status_code = 503
        return error_response(
            request,
            status_code=status_code,
            code=error.code,
            message=error.message,
        )

    @application.exception_handler(DomainInvariantError)
    async def domain_error(
        request: Request,
        error: DomainInvariantError,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code=error.code,
            message=error.message,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code="request_invalid",
            message="Die Anfrage enthält ungültige oder fehlende Angaben.",
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        codes = {
            404: ("endpoint_not_found", "Dieser API-Endpunkt existiert nicht."),
            405: ("method_not_allowed", "Diese HTTP-Methode ist hier nicht erlaubt."),
        }
        code, message = codes.get(
            error.status_code,
            ("http_error", "Die HTTP-Anfrage konnte nicht verarbeitet werden."),
        )
        return error_response(
            request,
            status_code=error.status_code,
            code=code,
            message=message,
        )

    @application.exception_handler(Exception)
    async def unexpected_error(
        request: Request,
        _error: Exception,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Die Anfrage ist unerwartet fehlgeschlagen.",
        )

    application.include_router(router)
    return application


app = create_app()
