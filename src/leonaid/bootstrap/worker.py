"""Worker composition: outbox handlers and background loops per owning area.

Areas that are not yet migrated to ``leonaid.modules`` register here with
their existing adapters, so every handler has exactly one named owner and
duplicate event types fail at startup.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
import httpx
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
from leonaid.adapters.postgres.push import AsyncpgPushRepository
from leonaid.adapters.storage import S3ObjectStorage
from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.adapters.typst import TypstInvoiceRenderer
from leonaid.adapters.web_push import WebPushSender
from leonaid.application.delivery_geo import GeocodingJob
from leonaid.application.documents import InvoiceDocumentStorageHandler
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.application.crm import CrmGateway
from leonaid.application.object_storage import ObjectStorage
from leonaid.application.order_mails import (
    EVENT_TYPES,
    OrderMailHandler,
    OrderMailKind,
)
from leonaid.application.outbox import OutboxEventHandler, OutboxWorker
from leonaid.application.push import FollowUpPushJob, PushNotificationHandler
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
    PushSettings,
    load_mail_transport_settings,
    load_module_settings,
    load_push_settings,
)
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy
from leonaid.domain.push import PUSH_EVENT_TYPE, PushEndpointPolicy
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
    # The HTTP client and keys for Web Push; None without a VAPID key.
    push: WebPushSender | None = None
    push_public_key: str | None = None


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
            "invoicing",
            handlers=_invoice_handlers(dependencies) if dependencies else {},
        ),
        ModuleRegistration(
            "mail",
            handlers=_mail_handlers(dependencies) if dependencies else {},
        ),
        ModuleRegistration(
            "push",
            handlers=_push_handlers(dependencies) if dependencies else {},
            handler_timeouts=PUSH_HANDLER_TIMEOUTS if dependencies else {},
            background_loops=(push_follow_up_loop(database_url),),
        ),
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
    return {
        "invoice.document.render.requested.v1": InvoiceDocumentStorageHandler(
            repository=AsyncpgGeneratedDocumentRepository(dependencies.pool),
            renderer=TypstInvoiceRenderer(),
            storage=dependencies.storage,
        ),
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


# One request to a push service ends after PUSH_REQUEST_SECONDS as a whole.
# The job sends to all devices of a member at once and ends by itself after
# PUSH_JOB_SECONDS (application/push.py); the handler timeout is only the
# backstop behind that. Mail and document jobs wait behind a push job for
# seconds, not minutes.
PUSH_REQUEST_SECONDS = 10.0
PUSH_HANDLER_TIMEOUTS = {PUSH_EVENT_TYPE: 45.0}
PUSH_FOLLOW_UP_LOOP = "push_follow_ups"
PUSH_FOLLOW_UP_INTERVAL_SECONDS = 300.0


def _flags(pool: asyncpg.Pool[Any]) -> FeatureFlagService:
    return FeatureFlagService(
        AsyncpgFeatureFlagRepository(pool),
        OpenFeatureBooleanEvaluator(LeonAidFeatureProvider()),
    )


def _push_handlers(
    dependencies: HandlerDependencies,
) -> dict[str, OutboxEventHandler]:
    return {
        PUSH_EVENT_TYPE: PushNotificationHandler(
            AsyncpgPushRepository(dependencies.pool),
            dependencies.push,
            _flags(dependencies.pool),
            vapid_public_key=dependencies.push_public_key,
            observer=observe_push_failure,
        )
    }


def observe_push_failure(
    *,
    kind: str,
    host: str,
    status: int | None,
    outcome: str,
    attempt: int,
    device_removed: bool,
) -> None:
    """One log line per message that did not reach a device.

    What an operator needs to see why pushes do not arrive: the push
    service's host and its HTTP status (401 and 403 point at the VAPID key
    or subject). Never the endpoint's path, which is the device's token,
    and never the member.
    """
    print(
        structured_event(
            "worker.push.undelivered",
            kind=kind,
            host=host,
            status=status,
            outcome=outcome,
            attempt=attempt,
            deviceRemoved=device_removed,
        ),
        flush=True,
    )


def push_sender(
    settings: PushSettings,
) -> tuple[WebPushSender, httpx.AsyncClient] | None:
    """The Web Push sender and its HTTP client; None without a VAPID key.

    The client follows no redirects and reads no proxy settings from the
    environment: it calls the allowlisted push services and nothing else.
    """
    signer = settings.signer()
    if signer is None:
        return None
    client = httpx.AsyncClient(
        timeout=PUSH_REQUEST_SECONDS, follow_redirects=False, trust_env=False
    )
    sender = WebPushSender(
        signer, client, PushEndpointPolicy(), request_seconds=PUSH_REQUEST_SECONDS
    )
    return sender, client


def _public_key(settings: PushSettings) -> str | None:
    signer = settings.signer()
    return signer.public_key if signer is not None else None


async def close_all(closers: Sequence[Callable[[], Awaitable[None]]]) -> None:
    """Run every closer, also after one of them failed; then raise the
    first failure. One client that cannot close keeps no other one open."""
    failures: list[Exception] = []
    for closer in closers:
        try:
            await closer()
        except Exception as error:
            failures.append(error)
    if failures:
        raise failures[0]


def push_follow_up_loop(database_url: str) -> BackgroundLoop:
    """Every five minutes: the daily follow-up push (from 08:00 club time)
    and the removal of devices whose session ended."""

    async def run(report: LoopReporter) -> None:
        while True:
            pool = None
            try:
                pool = await create_pool(database_url, maximum_size=1)
                job = FollowUpPushJob(
                    AsyncpgPushRepository(pool),
                    _flags(pool),
                    vapid_public_key=_public_key(load_push_settings()),
                )
                while True:
                    asked = await job.run_once(now=datetime.now(timezone.utc))
                    report.succeeded()
                    if asked:
                        print(
                            structured_event("worker.push.follow_ups", members=asked),
                            flush=True,
                        )
                    await asyncio.sleep(PUSH_FOLLOW_UP_INTERVAL_SECONDS)
            except Exception as error:
                # Logged by type and location only, never with row data.
                await asyncio.sleep(report.failed(error))
            finally:
                if pool is not None:
                    await pool.close()

    return BackgroundLoop(
        PUSH_FOLLOW_UP_LOOP,
        stall_after_seconds=PUSH_FOLLOW_UP_INTERVAL_SECONDS * 3,
        run=run,
    )


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
    # What this function opened so far. If a later step fails, the caller
    # gets no worker to close, so everything is closed here.
    closers: list[Callable[[], Awaitable[None]]] = []
    try:
        crm = crm_gateway_from_environment()
        if crm is not None:
            closers.append(crm.close)
        push_settings = load_push_settings()
        push = push_sender(push_settings)
        if push is not None:
            closers.append(push[1].aclose)
        all_modules = worker_modules(
            database_url,
            HandlerDependencies(
                pool=pool,
                storage=object_storage_from_environment(),
                mail_transport=mail_transport_from_environment(),
                payload_secret=os.environ["LEONAID_SESSION_ENCRYPTION_KEY"],
                crm=crm,
                push=push[0] if push is not None else None,
                push_public_key=_public_key(push_settings),
            ),
        )
        modules, parked = split_enabled(all_modules, switched_off)
        # Jobs of switched-off modules stay pending until the module is back
        # on; they are neither claimed nor dead-lettered as unhandled.
        queue = AsyncpgOutboxQueue(
            pool,
            claim_lease=timedelta(seconds=claim_lease_seconds),
            excluded_event_types=frozenset(
                event_type for module in parked for event_type in module.handlers
            ),
        )
        handler_clients = tuple(closers)
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
            on_close=(
                (lambda: close_all(handler_clients)) if handler_clients else None
            ),
        )
    except BaseException:
        await close_all([*closers, pool.close])
        raise
    return pool, queue, worker


def build_geocoding_job(
    pool: asyncpg.Pool[Any], settings: MapSettings
) -> tuple[GeocodingJob, NominatimGeocoder]:
    """The geocoding job and its HTTP client; the caller closes the client."""

    geocoder = NominatimGeocoder(settings.geocoder_url, settings.geocoder_user_agent)
    return (
        GeocodingJob(AsyncpgDeliveryGeoRepository(pool), geocoder, _flags(pool)),
        geocoder,
    )
