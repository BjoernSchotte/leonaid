"""FastAPI composition root and transport-level policies."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openfeature import api as openfeature_api
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from leonaid.adapters.feature_flags.openfeature import (
    LeonAidFeatureProvider,
    OpenFeatureBooleanEvaluator,
)
from leonaid.adapters.http_readiness import HttpReadinessProbe
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.application.order_mails import OrderMailLinkResolver
from leonaid.adapters.postgres.acquisition import (
    AsyncpgAcquisitionPolicyRepository,
)
from leonaid.adapters.postgres.activity_feed import AsyncpgActivityFeedRepository
from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.adapters.postgres.campaign_aliases import AsyncpgCampaignAliasRepository
from leonaid.adapters.postgres.site_hosts import (
    AsyncpgSiteHostRepository,
    CanonicalResolver,
)
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.application.delivery import DeliveryService
from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery_completion import (
    AsyncpgDeliveryCompletionRepository,
)
from leonaid.adapters.postgres.documents import AsyncpgGeneratedDocumentRepository
from leonaid.adapters.postgres.dashboard import AsyncpgDashboardRepository
from leonaid.adapters.postgres.email_changes import AsyncpgEmailChangeRepository
from leonaid.adapters.postgres.feature_flags import AsyncpgFeatureFlagRepository
from leonaid.adapters.postgres.identity import AsyncpgIdentityRepository
from leonaid.adapters.postgres.invoice_deliveries import (
    AsyncpgInvoiceDeliveryRepository,
)
from leonaid.adapters.postgres.invoice_settlements import (
    AsyncpgInvoiceSettlementRepository,
)
from leonaid.adapters.postgres.invoices import AsyncpgInvoiceRepository
from leonaid.adapters.postgres.invitations import AsyncpgInvitationRepository
from leonaid.adapters.postgres.legal_configuration import (
    AsyncpgLegalConfigurationRepository,
)
from leonaid.adapters.postgres.pool import create_pool
from leonaid.bootstrap.api import (
    build_delivery_board_service,
    build_delivery_tour_service,
    build_order_cancellation_service,
    build_push_service,
    build_inbox_service,
    build_knowledge_service,
    build_material_service,
    build_survey_services,
    build_task_service,
    module_navigation,
    parked_event_types,
    privacy_contributors,
    register_api_modules,
)
from leonaid.platform.http_body import RequestBodyLimitMiddleware
from leonaid.adapters.postgres.privacy import AsyncpgPrivacyRepository
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.adapters.postgres.readiness import PostgresReadinessProbe
from leonaid.adapters.postgres.search import AsyncpgSearchRepository
from leonaid.adapters.postgres.sessions import AsyncpgSessionRepository
from leonaid.adapters.postgres.security import (
    AsyncpgSecurityRateLimitRepository,
)
from leonaid.adapters.storage import S3ObjectStorage
from leonaid.adapters.twenty.gateway import (
    TwentyCrmGateway,
    TwentyGatewaySettings,
)
from leonaid.application.acquisition import AcquisitionPolicyService
from leonaid.application.activity_feed import ActivityFeedService
from leonaid.application.activities import AcquisitionActivityService
from leonaid.application.assignments import AssignmentManagementService
from leonaid.application.actions import CharityActionService
from leonaid.application.campaign_aliases import CampaignAliasService
from leonaid.application.site_hosts import SiteHostService
from leonaid.adapters.postgres.buyer_mails import AsyncpgBuyerMailRepository
from leonaid.application.buyer_mails import BuyerMailService
from leonaid.application.commitments import CommitmentService
from leonaid.application.delivery_completion import DeliveryCompletionService
from leonaid.application.documents import GeneratedDocumentService
from leonaid.application.dashboard import DashboardService
from leonaid.application.email_changes import EmailChangeService
from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    DependencyUnavailable,
    PermissionDenied,
    RateLimited,
    ResourceNotFound,
)
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.application.identity import (
    IdentityAdministrationService,
    IdentityQueryService,
)
from leonaid.application.invoice_deliveries import InvoiceDeliveryService
from leonaid.adapters.postgres.donation_receipts import (
    AsyncpgDonationReceiptRepository,
)
from leonaid.adapters.postgres.donations import AsyncpgDonationRepository
from leonaid.application.donation_receipts import DonationReceiptService
from leonaid.application.donations import DonationService
from leonaid.application.invoice_settlements import InvoiceSettlementService
from leonaid.application.invoices import InvoiceService
from leonaid.application.invitations import InvitationService
from leonaid.application.legal_configuration import LegalConfigurationService
from leonaid.adapters.operations import (
    ApiMetrics,
    InMemoryRequestDiagnostics,
    OperationsService,
    structured_event,
)
from leonaid.application.platform import PlatformApplicationService
from leonaid.application.privacy import PrivacyService
from leonaid.application.public_orders import (
    PublicOrderService,
    PublicOrderTokenCodec,
)
from leonaid.application.search import SearchService
from leonaid.application.sessions import SessionService
from leonaid.application.sponsor_matching import SponsorMatchingService
from leonaid.configuration import (
    Settings,
    load_map_settings,
    load_module_settings,
    load_push_settings,
    load_settings,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.platform import PlatformIdentity
from leonaid.entrypoints.fastapi.push import router as push_router
from leonaid.entrypoints.fastapi.routes import router
from leonaid.entrypoints.fastapi.site_hosts import (
    action_router as action_url_router,
    infrastructure_router as site_host_infrastructure_router,
    public_router as public_site_router,
    router as site_host_router,
)
from leonaid.adapters.postgres.site_directory import (
    AsyncpgSiteDirectory,
    SiteHostPublicOrigins,
)
from leonaid.adapters.postgres.site_host_verification import (
    AsyncpgSiteHostVerification,
)
from leonaid.adapters.site_host_checks import HostChecker
from leonaid.entrypoints.fastapi.maintenance import writes_are_blocked
from leonaid.entrypoints.fastapi.order_proxy import order_proxy_denied
from leonaid.entrypoints.fastapi.security import (
    csrf_violation,
    public_origin_allowed,
    rate_limit_violation,
)

# Request bodies are bounded before parsing; uploads get headroom for the
# multipart envelope around the 25 MiB file.
SURVEY_REQUEST_BYTES = 1_048_576
MATERIAL_UPLOAD_BYTES = 25 * 1024 * 1024 + 65_536
BODY_LIMITS: tuple[tuple[str, int], ...] = (
    ("/api/v1/surveys", SURVEY_REQUEST_BYTES),
    ("/api/v1/public/surveys", SURVEY_REQUEST_BYTES),
    ("/api/v1/survey-settings", SURVEY_REQUEST_BYTES),
    ("/api/v1/materials", MATERIAL_UPLOAD_BYTES),
    ("/api/v1/public/inbox-cases", 64 * 1024),
    ("/api/v1/inbox-cases", 64 * 1024),
)
REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}\Z")
PATH_UUID = re.compile(
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)"
)


# One API process at a time runs the re-check (§7.4).
SITE_HOST_RECHECK_LOCK = 527063


async def site_host_recheck_loop(
    service: SiteHostService, pool: Any, interval_seconds: float
) -> None:
    """Re-checks campaign hosts in the API process, which has egress.

    Verified hosts every run (until their certificate is there), active and
    lapsed hosts once a day. Failures land on the host and in the operations
    view; this loop never stops on them.
    """
    await asyncio.sleep(min(60.0, interval_seconds))
    while True:
        try:
            async with pool.acquire() as connection:
                if await connection.fetchval(
                    "SELECT pg_try_advisory_lock($1)", SITE_HOST_RECHECK_LOCK
                ):
                    try:
                        checked = await service.recheck_due(
                            request_id=f"site-host-recheck:{uuid4()}"
                        )
                    finally:
                        await connection.execute(
                            "SELECT pg_advisory_unlock($1)", SITE_HOST_RECHECK_LOCK
                        )
                    if checked:
                        print(
                            structured_event("site_host.rechecked", hosts=checked),
                            flush=True,
                        )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - logged by type, retried
            print(
                structured_event(
                    "site_host.recheck_failed", errorType=type(error).__name__
                ),
                flush=True,
            )
        await asyncio.sleep(interval_seconds)


def request_id_for(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else str(uuid4())


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    request.state.error_code = code
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "requestId": request_id_for(request),
    }
    if details is not None:
        error["details"] = details
    return JSONResponse(
        status_code=status_code,
        headers={"Cache-Control": "no-store"}
        if status_code in {401, 403}
        or request.url.path.startswith(
            ("/api/v1/inbox-cases", "/api/v1/public/inbox-cases")
        )
        or request.url.path.startswith("/api/v1/public/actions/")
        or (
            request.url.path.startswith("/api/v1/actions/")
            and request.url.path.split("/")[5:6] == ["redirect-aliases"]
        )
        else None,
        content={"error": error},
    )


def crm_probes(settings: Settings) -> tuple[HttpReadinessProbe, ...]:
    """Twenty is a readiness dependency only with an integration key.

    Without the key the CRM features are off (decision E-031). Production
    requires the key: the pilot doctor fails without it
    (tools/pilot_deployment/doctor.py).
    """
    if settings.twenty_integration_api_key is None:
        return ()
    return (HttpReadinessProbe("twenty", str(settings.twenty_health_url)),)


def build_service(
    settings: Settings, postgres_probe: PostgresReadinessProbe
) -> PlatformApplicationService:
    identity = PlatformIdentity(
        service=settings.service_name,
        release=settings.service_version,
        api_version=settings.api_version,
    )
    return PlatformApplicationService(
        identity=identity,
        probes=(
            postgres_probe,
            *crm_probes(settings),
            HttpReadinessProbe("rustfs", str(settings.rustfs_health_url)),
        ),
    )


def create_app(configured_settings: Settings | None = None) -> FastAPI:
    # Routes are fixed when the app is built, before the lifespan loads the
    # full settings, so the module switches are read here.
    disabled_modules = (
        configured_settings.disabled_modules
        if configured_settings is not None
        else load_module_settings().disabled_modules
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = configured_settings or load_settings()
        application.state.settings_summary = settings.safe_summary()
        application.state.club_name = settings.club_name
        application.state.order_submission_key = (
            settings.order_submission_key.get_secret_value()
            if settings.order_submission_key is not None
            else None
        )
        pool = await create_pool(settings.core_database_url.get_secret_value())
        application.state.platform_service = build_service(
            settings, PostgresReadinessProbe(pool)
        )
        api_metrics = ApiMetrics()
        application.state.operations_service = OperationsService(
            pool,
            api_metrics=api_metrics,
            dependency_urls={
                "twenty": str(settings.twenty_health_url),
                "rustfs": str(settings.rustfs_health_url),
                "mail": str(settings.mail_health_url),
                "worker": str(settings.worker_health_url),
            },
            monitor_status_url=(
                str(settings.pilot_monitor_status_url)
                if settings.pilot_monitor_status_url is not None
                else None
            ),
            alertmanager_url=(
                str(settings.pilot_alertmanager_url)
                if settings.pilot_alertmanager_url is not None
                else None
            ),
            release=settings.release_commit or settings.service_version,
            parked_event_types=parked_event_types(disabled_modules),
        )
        application.state.api_metrics = api_metrics
        application.state.request_diagnostics = InMemoryRequestDiagnostics(
            release=settings.release_commit or settings.service_version,
        )
        application.state.security_rate_limits = AsyncpgSecurityRateLimitRepository(
            pool
        )
        application.state.security_secret = (
            settings.invitation_hmac_secret.get_secret_value()
        )
        application.state.allowed_origins = settings.allowed_origins
        application.state.links = settings.links
        application.state.trust_proxy_headers = settings.trust_proxy_headers
        application.state.maintenance_flag_path = settings.maintenance_flag_path
        identity_repository = AsyncpgIdentityRepository(pool)
        application.state.identity_service = IdentityQueryService(
            identity_repository,
            module_navigation=module_navigation(disabled_modules),
            delivery_navigation=identity_repository.manages_delivery,
            donation_actions=identity_repository.donation_actions,
            cms_enabled=settings.cms_enabled,
            fresh_login_window=timedelta(seconds=settings.fresh_login_seconds),
        )
        application.state.identity_administration_service = (
            IdentityAdministrationService(identity_repository)
        )
        application.state.action_service = CharityActionService(
            AsyncpgCharityActionRepository(pool)
        )
        application.state.campaign_alias_service = CampaignAliasService(
            AsyncpgCampaignAliasRepository(pool)
        )
        canonical = CanonicalResolver(
            settings.configured_hosts, str(settings.site_base_url)
        )
        application.state.canonical_urls = canonical
        site_directory = AsyncpgSiteDirectory(pool, canonical)
        application.state.site_directory = site_directory
        # The public host and its aliases plus every active campaign host,
        # read at request time (§6.3, D7).
        application.state.public_origins = SiteHostPublicOrigins(
            settings.public_origins,
            site_directory,
            production=settings.environment == "production",
        )
        application.state.site_host_check_secret = settings.site_host_check_secret
        site_host_verification = AsyncpgSiteHostVerification(pool)
        application.state.site_host_verification = site_host_verification
        application.state.site_host_service = SiteHostService(
            AsyncpgSiteHostRepository(pool, canonical),
            settings.configured_hosts,
            site_host_verification,
            HostChecker(settings.host_check_settings),
        )
        application.state.activity_feed_service = ActivityFeedService(
            AsyncpgActivityFeedRepository(pool)
        )
        application.state.dashboard_service = DashboardService(
            AsyncpgDashboardRepository(pool)
        )
        application.state.delivery_service = DeliveryService(
            AsyncpgDeliveryRepository(pool)
        )
        feature_flag_provider = LeonAidFeatureProvider()
        feature_flag_evaluator = OpenFeatureBooleanEvaluator(feature_flag_provider)
        application.state.feature_flag_service = FeatureFlagService(
            AsyncpgFeatureFlagRepository(pool),
            feature_flag_evaluator,
        )
        application.state.delivery_board_service = build_delivery_board_service(
            pool, disabled_modules, application.state.feature_flag_service
        )
        # The buyer's order mails link the campaign and the legal pages. The
        # campaign link is the permanent edition URL on the campaign host
        # (decision D8), else the public host page, else none (§7.6).
        order_mail_links = OrderMailLinkResolver(
            settings.links, site_directory.edition_link
        )
        application.state.commitment_service = CommitmentService(
            AsyncpgCommitmentRepository(pool), mail_links=order_mail_links
        )
        application.state.buyer_mail_service = BuyerMailService(
            AsyncpgBuyerMailRepository(pool), mail_links=order_mail_links
        )
        application.state.search_service = SearchService(AsyncpgSearchRepository(pool))
        application.state.delivery_completion_service = DeliveryCompletionService(
            AsyncpgDeliveryCompletionRepository(pool), mail_links=order_mail_links
        )
        application.state.invoice_service = InvoiceService(
            AsyncpgInvoiceRepository(pool)
        )
        application.state.invoice_delivery_service = InvoiceDeliveryService(
            AsyncpgInvoiceDeliveryRepository(pool)
        )
        application.state.invoice_settlement_service = InvoiceSettlementService(
            AsyncpgInvoiceSettlementRepository(pool)
        )
        donation_repository = AsyncpgDonationRepository(pool)
        application.state.donation_service = DonationService(donation_repository)
        application.state.donation_receipt_service = DonationReceiptService(
            AsyncpgDonationReceiptRepository(pool, donation_repository)
        )
        application.state.order_cancellation_service = build_order_cancellation_service(
            pool, disabled_modules, mail_links=order_mail_links
        )
        application.state.delivery_tour_service = build_delivery_tour_service(
            pool, application.state.feature_flag_service, load_map_settings()
        )
        application.state.push_service = build_push_service(
            pool,
            application.state.feature_flag_service,
            disabled_modules,
            load_push_settings(),
        )
        legal_configuration_repository = AsyncpgLegalConfigurationRepository(pool)
        application.state.legal_configuration_service = LegalConfigurationService(
            legal_configuration_repository,
            production=settings.environment == "production",
        )
        privacy_service = PrivacyService(
            AsyncpgPrivacyRepository(
                pool,
                subject_hmac_secret=(
                    settings.invitation_hmac_secret.get_secret_value()
                ),
                contributors=privacy_contributors(),
            )
        )
        application.state.privacy_service = privacy_service
        document_repository = AsyncpgGeneratedDocumentRepository(pool)
        object_storage = S3ObjectStorage(
            endpoint_url=str(settings.object_storage_endpoint_url),
            access_key=settings.object_storage_access_key.get_secret_value(),
            secret_key=settings.object_storage_secret_key.get_secret_value(),
            bucket=settings.object_storage_bucket,
            region=settings.object_storage_region,
            path_style=settings.object_storage_path_style,
        )
        application.state.document_service = GeneratedDocumentService(
            repository=document_repository,
            storage=object_storage,
        )
        (
            application.state.survey_service,
            application.state.survey_exports,
            checkpoint_publisher,
        ) = build_survey_services(pool, settings, object_storage)
        application.state.task_service = build_task_service(pool)
        application.state.material_service = build_material_service(
            pool, object_storage
        )
        application.state.knowledge_service = build_knowledge_service(
            pool, object_storage
        )
        public_order_tokens = PublicOrderTokenCodec(
            settings.invitation_hmac_secret.get_secret_value()
        )
        application.state.public_order_tokens = public_order_tokens
        application.state.public_order_fingerprint_secret = (
            settings.invitation_hmac_secret.get_secret_value()
        )
        mail_payload = SecureMailPayload(
            settings.mail_payload_secret.get_secret_value()
        )
        application.state.invitation_service = InvitationService(
            AsyncpgInvitationRepository(pool),
            mail_payload,
            hmac_secret=settings.invitation_hmac_secret.get_secret_value(),
            links=settings.links,
            ttl=timedelta(minutes=settings.invitation_ttl_minutes),
        )
        application.state.email_change_service = EmailChangeService(
            AsyncpgEmailChangeRepository(pool),
            mail_payload,
            hmac_secret=settings.invitation_hmac_secret.get_secret_value(),
            links=settings.links,
            ttl=timedelta(minutes=settings.invitation_ttl_minutes),
        )
        application.state.session_service = SessionService(
            AsyncpgSessionRepository(pool),
            mail_payload,
            hmac_secret=settings.invitation_hmac_secret.get_secret_value(),
            links=settings.links,
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
                privacy_service,
            )
            application.state.public_order_service = PublicOrderService(
                AsyncpgPublicOrderRepository(pool),
                crm_gateway,
                public_order_tokens,
                legal_configuration_repository,
                mail_links=order_mail_links,
            )
        else:
            application.state.acquisition_service = None
            application.state.sponsor_matching_service = None
            application.state.assignment_management_service = None
            application.state.activity_management_service = None
            application.state.public_order_service = None
        application.state.inbox_service = build_inbox_service(pool, crm_gateway)
        recheck = (
            asyncio.create_task(
                site_host_recheck_loop(
                    application.state.site_host_service,
                    pool,
                    settings.site_host_recheck_interval_seconds,
                )
            )
            if settings.site_host_recheck_interval_seconds > 0
            else None
        )
        try:
            if settings.survey_erasure_archive_dir is not None:
                await checkpoint_publisher.publish()
            yield
        finally:
            if recheck is not None:
                recheck.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await recheck
            if crm_gateway is not None:
                await crm_gateway.close()
            await pool.close()
            openfeature_api.shutdown()

    application = FastAPI(
        title="LeonAid Core",
        version="0.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(RequestBodyLimitMiddleware, limits=BODY_LIMITS)

    @application.middleware("http")
    async def correlate_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = (
            supplied if REQUEST_ID.fullmatch(supplied) else str(uuid4())
        )
        if order_proxy_denied(request, key=request.app.state.order_submission_key):
            denied = error_response(
                request,
                status_code=404,
                code="order_proxy_denied",
                message="Dieser Bestellzugang ist nicht verfügbar.",
            )
            denied.headers["Cache-Control"] = "no-store"
            return denied
        allowed_origins = tuple(request.app.state.allowed_origins)
        origin = request.headers.get("origin")
        # Public and campaign hosts call only the public API, without
        # credentials; the admin origins keep the credentialed CORS (§6.3).
        public_origin = await public_origin_allowed(
            request,
            origin,
            allowed_origins=allowed_origins,
            public_origins=request.app.state.public_origins,
        )
        if (
            request.method == "OPTIONS"
            and origin is not None
            and request.headers.get("access-control-request-method")
        ):
            if origin.rstrip("/") not in allowed_origins and not public_origin:
                return error_response(
                    request,
                    status_code=403,
                    code="cors_origin_rejected",
                    message="Diese Browser-Anfrage ist für LeonAid nicht freigegeben.",
                )
            preflight = Response(status_code=204)
            preflight.headers["Access-Control-Allow-Origin"] = origin
            if not public_origin:
                preflight.headers["Access-Control-Allow-Credentials"] = "true"
            preflight.headers["Access-Control-Allow-Methods"] = (
                "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS"
            )
            preflight.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Idempotency-Key, X-Request-ID"
            )
            preflight.headers["Access-Control-Max-Age"] = "600"
            preflight.headers["Vary"] = "Origin"
            return preflight
        if writes_are_blocked(
            request.method,
            request.app.state.maintenance_flag_path,
        ):
            maintenance_response = error_response(
                request,
                status_code=503,
                code="maintenance_mode",
                message=(
                    "LeonAid wird gerade aktualisiert. Lesen ist weiterhin "
                    "möglich; Änderungen sind vorübergehend gesperrt."
                ),
            )
            maintenance_response.headers["Retry-After"] = "60"
            return maintenance_response
        csrf_reason = csrf_violation(
            request,
            allowed_origins=(
                (*allowed_origins, origin.rstrip("/"))
                if public_origin and origin is not None
                else allowed_origins
            ),
        )
        if csrf_reason is not None:
            return error_response(
                request,
                status_code=403,
                code="csrf_rejected",
                message=(
                    "Diese Anfrage wurde aus Sicherheitsgründen abgelehnt. "
                    "Bitte die Seite neu laden und erneut versuchen."
                ),
            )
        rate_policy = await rate_limit_violation(
            request,
            repository=request.app.state.security_rate_limits,
            secret=request.app.state.security_secret,
            trust_proxy_headers=request.app.state.trust_proxy_headers,
        )
        if rate_policy is not None:
            limited_response = error_response(
                request,
                status_code=429,
                code="request_rate_limited",
                message="Zu viele Versuche. Bitte kurz warten und erneut versuchen.",
            )
            limited_response.headers["Retry-After"] = str(
                max(1, int(rate_policy.window.total_seconds()))
            )
            return limited_response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if origin is not None and origin.rstrip("/") in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = (
                "Content-Disposition, X-Request-ID"
            )
            response.headers["Vary"] = "Origin"
        elif public_origin and origin is not None:
            # Never Access-Control-Allow-Credentials for a public origin.
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
            response.headers["Vary"] = "Origin"
        return response

    @application.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = round((perf_counter() - started) * 1000, 2)
            request.app.state.api_metrics.record(
                status_code=status_code,
                latency_ms=latency_ms,
            )
            route = request.scope.get("route")
            route_template = getattr(route, "path", None)
            if not isinstance(route_template, str) or not route_template.startswith(
                "/"
            ):
                route_template = "<unmatched>"
            request.app.state.request_diagnostics.record(
                request_id=request_id_for(request),
                method=request.method,
                route=route_template,
                status_code=status_code,
                error_code=getattr(request.state, "error_code", None),
            )
            entity_match = PATH_UUID.search(request.url.path)
            entity_id = entity_match.group(1) if entity_match else None
            action_id = (
                entity_id
                if entity_id is not None
                and request.url.path.startswith("/api/v1/actions/")
                else None
            )
            print(
                structured_event(
                    "http.request.completed",
                    requestId=request_id_for(request),
                    method=request.method,
                    path=request.url.path,
                    statusCode=status_code,
                    latencyMs=latency_ms,
                    actionId=action_id,
                    entityId=entity_id,
                ),
                flush=True,
            )

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
        elif isinstance(error, RateLimited):
            status_code = 429
        return error_response(
            request,
            status_code=status_code,
            code=error.code,
            message=error.message,
            details=error.details,
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

    register_api_modules(
        application,
        core=(
            router,
            site_host_router,
            push_router,
            public_site_router,
            site_host_infrastructure_router,
            action_url_router,
        ),
        disabled=disabled_modules,
    )
    return application


app = create_app()
