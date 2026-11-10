"""Worker composition: outbox handlers and background loops per owning area.

Areas that are not yet migrated to ``leonaid.modules`` register here with
their existing adapters, so every handler has exactly one named owner and
duplicate event types fail at startup.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from pydantic import SecretStr

from leonaid.adapters.feature_flags.openfeature import (
    LeonAidFeatureProvider,
    OpenFeatureBooleanEvaluator,
)
from leonaid.adapters.mail.invoice_smtp import InvoiceSmtpHandler
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.mail.smtp import SmtpMailHandler
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.adapters.operations import structured_event
from leonaid.adapters.postgres.activity_projection import (
    ActionProgressActivityHandler,
)
from leonaid.adapters.nominatim import NominatimGeocoder
from leonaid.adapters.postgres.delivery_geo import AsyncpgDeliveryGeoRepository
from leonaid.adapters.postgres.documents import AsyncpgGeneratedDocumentRepository
from leonaid.adapters.postgres.feature_flags import AsyncpgFeatureFlagRepository
from leonaid.adapters.postgres.invoice_deliveries import (
    AsyncpgInvoiceDeliveryRepository,
)
from leonaid.adapters.postgres.legal_configuration import (
    AsyncpgLegalConfigurationRepository,
)
from leonaid.adapters.postgres.order_mails import AsyncpgOrderMailReader
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.sponsor_search import AsyncpgSponsorSearchIndex
from leonaid.adapters.storage import S3ObjectStorage
from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.adapters.typst import (
    TypstInvoiceCancellationRenderer,
    TypstInvoiceRenderer,
)
from leonaid.application.delivery_geo import GeocodingJob
from leonaid.application.documents import DocumentStorageHandler
from leonaid.application.invoice_cancellation_documents import (
    InvoiceCancellationDocumentSource,
)
from leonaid.application.invoice_documents import InvoiceDocumentSource
from leonaid.domain.documents import DOCUMENT_RENDER_EVENTS, GeneratedDocumentType
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.application.crm import CrmGateway
from leonaid.application.object_storage import ObjectStorage
from leonaid.application.order_mails import (
    EVENT_TYPES,
    OrderMailHandler,
    OrderMailKind,
)
from leonaid.application.outbox import OutboxEventHandler, OutboxWorker
from leonaid.application.sponsor_search import (
    SYNC_INTERVAL_SECONDS,
    SYNC_REQUEST_BUDGET,
    SponsorSearchSync,
    retry_delay_seconds,
)
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    RegistrationError,
    collect_background_loops,
    collect_handler_timeouts,
    collect_handlers,
    split_enabled,
)
from leonaid.configuration import (
    MapSettings,
    load_mail_transport_settings,
    load_module_settings,
)
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy
from leonaid.modules.inbox.jobs import (
    INBOX_HANDLER_TIMEOUTS,
    InboxContactHandler,
)
from leonaid.modules.surveys.jobs import (
    SURVEY_HANDLER_TIMEOUTS,
    survey_handlers,
    survey_sweep,
)
from leonaid.platform.background import BackgroundLoop, LoopReporter


def observe_job(
    name: str,
    event: ClaimedOutboxEvent,
    error_code: str | None,
    duration_ms: float | None,
) -> None:
    action_value = event.payload.get("actionId")
    action_id = action_value if isinstance(action_value, str) else None
    print(
        structured_event(
            name,
            jobId=str(event.id),
            eventType=event.event_type,
            aggregateType=event.aggregate_type,
            aggregateId=str(event.aggregate_id),
            actionId=action_id,
            attempt=event.attempts,
            errorCode=error_code,
            durationMs=duration_ms,
        ),
        flush=True,
    )


@dataclass(frozen=True)
class HandlerDependencies:
    pool: asyncpg.Pool[Any]
    storage: ObjectStorage
    mail_transport: SmtpTransport
    payload_secret: str
    crm: CrmGateway | None = None


def worker_modules(
    database_url: str, dependencies: HandlerDependencies | None
) -> tuple[ModuleRegistration, ...]:
    """The single worker module table.

    Without ``dependencies`` the table carries background loops only; the
    process shell starts those loops before any outbox adapter exists.
    """
    return (
        ModuleRegistration(
            "surveys",
            handlers=_survey_handlers(dependencies) if dependencies else {},
            handler_timeouts=SURVEY_HANDLER_TIMEOUTS if dependencies else {},
            background_loops=(survey_sweep(database_url),),
            switchable=True,
        ),
        # Tasks have no jobs; registered so the switch list matches the API.
        ModuleRegistration("tasks", switchable=True),
        ModuleRegistration("materials", switchable=True),
        ModuleRegistration(
            "knowledge", switchable=True, requires=("tasks", "materials")
        ),
        ModuleRegistration(
            "inbox",
            handlers=_inbox_handlers(dependencies) if dependencies else {},
            handler_timeouts=INBOX_HANDLER_TIMEOUTS if dependencies else {},
            switchable=True,
            requires=("tasks", "materials"),
        ),
        ModuleRegistration(
            "actions",
            handlers=_action_handlers(dependencies) if dependencies else {},
        ),
        ModuleRegistration(
            "acquisition",
            background_loops=(sponsor_search_sync(database_url),),
        ),
        ModuleRegistration(
            "invoicing",
            handlers=_invoice_handlers(dependencies) if dependencies else {},
        ),
        ModuleRegistration(
            "mail",
            handlers=_mail_handlers(dependencies) if dependencies else {},
        ),
    )


SPONSOR_SEARCH_SYNC_LOOP = "sponsor_search_sync"
# One run sends at most SYNC_REQUEST_BUDGET requests, each bounded by the
# gateway timeout of five seconds.
_SPONSOR_SEARCH_RUN_SECONDS = SYNC_REQUEST_BUDGET * 5.0


@dataclass
class SponsorSearchSyncStatus:
    """What the worker's metrics say about the sync (one per process).

    The loop stays healthy when Twenty fails: that is not a fault of the
    worker. The operator's signal is the age of the last successful pass
    (alert ``LeonAidSponsorSearchStale``) and the error counter.
    """

    # False without an integration key: the loop idles and reports nothing.
    configured: bool = False
    # Age baseline until the first pass succeeded.
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_success: datetime | None = None
    crm_errors_total: int = 0
    # CRM errors in a row; the pause grows with it.
    failed_runs: int = 0

    def last_success_age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - (self.last_success or self.started_at)).total_seconds())


SPONSOR_SEARCH_SYNC_STATUS = SponsorSearchSyncStatus()


def sponsor_search_sync(database_url: str) -> BackgroundLoop:
    """Keeps the sponsor search index in step with Twenty.

    Every 15 minutes one bounded run (``SponsorSearchSync``); an unfinished
    full pass goes on after a minute. A CRM error or a 429 ends the run and
    is logged, and the pause doubles with each failed run up to the
    interval. The loop stays healthy meanwhile; ``SPONSOR_SEARCH_SYNC_STATUS``
    carries the age of the last successful pass for the stale-index alert.
    Without an integration key the loop idles. Logged by count only, never
    with a name.
    """

    status = SPONSOR_SEARCH_SYNC_STATUS

    async def run(report: LoopReporter) -> None:
        while True:
            pool = None
            crm = None
            try:
                pool = await create_pool(database_url, maximum_size=2)
                crm = crm_gateway_from_environment()
                status.configured = crm is not None
                if crm is None:
                    while True:
                        report.succeeded()
                        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
                index = AsyncpgSponsorSearchIndex(pool)
                sync = SponsorSearchSync(index, crm, zone=INSTALLATION_TIME_ZONE)
                while True:
                    result = await sync.run_once()
                    status.last_success = (await index.sync_state()).last_success
                    if result.crm_error is None:
                        status.failed_runs = 0
                    else:
                        status.failed_runs += 1
                        status.crm_errors_total += 1
                    report.succeeded()
                    if result.requests or result.deleted:
                        print(
                            structured_event(
                                "worker.sponsor_search.synced",
                                mode=result.mode,
                                requests=result.requests,
                                written=result.written,
                                deleted=result.deleted,
                                complete=result.complete,
                                rateLimited=result.rate_limited,
                                crmError=result.crm_error,
                                failedRuns=status.failed_runs,
                            ),
                            flush=True,
                        )
                    await asyncio.sleep(retry_delay_seconds(result, status.failed_runs))
            except Exception as error:
                # Logged by type and location only, never with party data.
                await asyncio.sleep(report.failed(error))
            finally:
                if crm is not None:
                    await crm.close()
                if pool is not None:
                    await pool.close()

    return BackgroundLoop(
        SPONSOR_SEARCH_SYNC_LOOP,
        stall_after_seconds=SYNC_INTERVAL_SECONDS + _SPONSOR_SEARCH_RUN_SECONDS + 150,
        run=run,
    )


def _survey_handlers(
    dependencies: HandlerDependencies,
) -> dict[str, OutboxEventHandler]:
    return survey_handlers(
        dependencies.pool,
        dependencies.storage,
        dependencies.mail_transport,
        dependencies.payload_secret,
    )


def _inbox_handlers(
    dependencies: HandlerDependencies,
) -> dict[str, OutboxEventHandler]:
    return {
        "inbox.contact_link.v1": InboxContactHandler(
            dependencies.pool, dependencies.crm
        )
    }


def _action_handlers(
    dependencies: HandlerDependencies,
) -> dict[str, OutboxEventHandler]:
    sender = SmtpMailHandler(dependencies.pool, transport=dependencies.mail_transport)
    reader = AsyncpgOrderMailReader(dependencies.pool)
    legal = AsyncpgLegalConfigurationRepository(dependencies.pool)
    return {
        "charity_action.progress.recorded.v1": ActionProgressActivityHandler(
            dependencies.pool
        ),
        # The buyer's order confirmation and cancellation notice.
        **{
            EVENT_TYPES[kind]: OrderMailHandler(
                kind, reader=reader, legal_configuration=legal, sender=sender
            )
            for kind in OrderMailKind
        },
    }


def _invoice_handlers(
    dependencies: HandlerDependencies,
) -> dict[str, OutboxEventHandler]:
    documents = AsyncpgGeneratedDocumentRepository(dependencies.pool)
    # One handler for every document kind; the type picks its source. A new
    # kind adds its source here and uses ``document.render.requested.v1``.
    render = DocumentStorageHandler(
        repository=documents,
        sources={
            GeneratedDocumentType.INVOICE_PDF: InvoiceDocumentSource(
                snapshots=documents,
                renderer=TypstInvoiceRenderer(),
            ),
            GeneratedDocumentType.INVOICE_CANCELLATION_PDF: (
                InvoiceCancellationDocumentSource(
                    documents=documents,
                    renderer=TypstInvoiceCancellationRenderer(),
                )
            ),
        },
        storage=dependencies.storage,
    )
    return {
        **{event_type: render for event_type in sorted(DOCUMENT_RENDER_EVENTS)},
        "invoice.mail.send.requested.v1": InvoiceSmtpHandler(
            repository=AsyncpgInvoiceDeliveryRepository(dependencies.pool),
            storage=dependencies.storage,
            transport=dependencies.mail_transport,
        ),
    }


def _mail_handlers(
    dependencies: HandlerDependencies,
) -> dict[str, OutboxEventHandler]:
    return {
        "mail.send.v1": SmtpMailHandler(
            dependencies.pool,
            transport=dependencies.mail_transport,
            secure_payload=SecureMailPayload(dependencies.payload_secret),
        ),
    }


def background_loops(
    database_url: str, disabled: frozenset[str]
) -> tuple[BackgroundLoop, ...]:
    """Loops of enabled modules; switched-off modules run none."""
    enabled, _ = split_enabled(worker_modules(database_url, None), disabled)
    return collect_background_loops(enabled)


def module_switch_problems(disabled: frozenset[str]) -> list[str]:
    """Report an unknown, core or still-required module in the switch list."""
    try:
        split_enabled(worker_modules("", None), disabled)
    except RegistrationError as error:
        return [f"LEONAID_DISABLED_MODULES:{error}"]
    return []


def object_storage_from_environment() -> S3ObjectStorage:
    return S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        path_style=os.environ.get("OBJECT_STORAGE_PATH_STYLE", "true").casefold()
        == "true",
    )


def crm_gateway_from_environment() -> TwentyCrmGateway | None:
    """The CRM gateway for jobs; absent without an integration key."""
    key = os.environ.get("TWENTY_INTEGRATION_API_KEY", "").strip()
    if not key:
        return None
    return TwentyCrmGateway(
        TwentyGatewaySettings(
            base_url=os.environ["TWENTY_BASE_URL"],
            api_key=SecretStr(key),
            # Durable job retries own the waiting; keep only the rate limiter.
            max_rate_limit_retries=0,
        )
    )


def mail_transport_from_environment() -> SmtpTransport:
    mail_settings = load_mail_transport_settings()
    return SmtpTransport(
        host=mail_settings.host,
        port=mail_settings.port,
        sender=mail_settings.sender,
        mode=mail_settings.mode,
        username=mail_settings.username,
        password=(
            mail_settings.password.get_secret_value()
            if mail_settings.password is not None
            else None
        ),
        timeout_seconds=mail_settings.timeout_seconds,
        verify_certificates=mail_settings.verify_certificates,
        ca_file=mail_settings.ca_file,
        envelope_from=mail_settings.envelope_from,
        reply_to=mail_settings.reply_to,
    )


def effective_timeouts(
    timeouts: dict[str, float], claim_lease_seconds: float
) -> dict[str, float]:
    """Keep every bounded handler well inside its claim lease.

    The last fifth of the lease covers cancellation and the queue update, so a
    timed-out job is released before another worker may claim it.
    """
    ceiling = claim_lease_seconds * 0.8
    return {event: min(seconds, ceiling) for event, seconds in timeouts.items()}


async def build_worker(
    *,
    database_url: str,
    worker_id: str,
    max_attempts: int,
    base_backoff_seconds: float,
    claim_lease_seconds: float,
    disabled: frozenset[str] | None = None,
) -> tuple[asyncpg.Pool[Any], AsyncpgOutboxQueue, OutboxWorker]:
    switched_off = (
        load_module_settings().disabled_modules if disabled is None else disabled
    )
    pool = await create_pool(database_url, maximum_size=5)
    crm = crm_gateway_from_environment()
    all_modules = worker_modules(
        database_url,
        HandlerDependencies(
            pool=pool,
            storage=object_storage_from_environment(),
            mail_transport=mail_transport_from_environment(),
            payload_secret=os.environ["LEONAID_SESSION_ENCRYPTION_KEY"],
            crm=crm,
        ),
    )
    modules, parked = split_enabled(all_modules, switched_off)
    # Jobs of switched-off modules stay pending until the module is back on;
    # they are neither claimed nor dead-lettered as unhandled.
    queue = AsyncpgOutboxQueue(
        pool,
        claim_lease=timedelta(seconds=claim_lease_seconds),
        excluded_event_types=frozenset(
            event_type for module in parked for event_type in module.handlers
        ),
    )
    worker = OutboxWorker(
        worker_id=worker_id,
        queue=queue,
        handlers=collect_handlers(modules),
        handler_timeouts=effective_timeouts(
            collect_handler_timeouts(modules), claim_lease_seconds
        ),
        retry_policy=RetryPolicy(
            max_attempts=max_attempts,
            base_delay=timedelta(seconds=base_backoff_seconds),
            maximum_delay=timedelta(minutes=15),
        ),
        observer=observe_job,
        on_close=crm.close if crm is not None else None,
    )
    return pool, queue, worker


def build_geocoding_job(
    pool: asyncpg.Pool[Any], settings: MapSettings
) -> tuple[GeocodingJob, NominatimGeocoder]:
    """The geocoding job and its HTTP client; the caller closes the client."""

    geocoder = NominatimGeocoder(settings.geocoder_url, settings.geocoder_user_agent)
    flags = FeatureFlagService(
        AsyncpgFeatureFlagRepository(pool),
        OpenFeatureBooleanEvaluator(LeonAidFeatureProvider()),
    )
    return (
        GeocodingJob(AsyncpgDeliveryGeoRepository(pool), geocoder, flags),
        geocoder,
    )
