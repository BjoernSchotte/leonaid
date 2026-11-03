"""Worker composition: outbox handlers and background loops per owning area.

Areas that are not yet migrated to ``leonaid.modules`` register here with
their existing adapters, so every handler has exactly one named owner and
duplicate event types fail at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import asyncpg

from leonaid.adapters.mail.invoice_smtp import InvoiceSmtpHandler
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.mail.smtp import SmtpMailHandler
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.adapters.operations import structured_event
from leonaid.adapters.postgres.activity_projection import (
    ActionProgressActivityHandler,
)
from leonaid.adapters.postgres.documents import AsyncpgGeneratedDocumentRepository
from leonaid.adapters.postgres.invoice_deliveries import (
    AsyncpgInvoiceDeliveryRepository,
)
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.storage import S3ObjectStorage
from leonaid.adapters.typst import TypstInvoiceRenderer
from leonaid.application.documents import InvoiceDocumentStorageHandler
from leonaid.application.object_storage import ObjectStorage
from leonaid.application.outbox import OutboxEventHandler, OutboxWorker
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    RegistrationError,
    collect_background_loops,
    collect_handler_timeouts,
    collect_handlers,
    split_enabled,
)
from leonaid.configuration import load_mail_transport_settings, load_module_settings
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy
from leonaid.modules.surveys.jobs import (
    SURVEY_HANDLER_TIMEOUTS,
    survey_handlers,
    survey_sweep,
)
from leonaid.platform.background import BackgroundLoop


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


def _action_handlers(
    dependencies: HandlerDependencies,
) -> dict[str, OutboxEventHandler]:
    return {
        "charity_action.progress.recorded.v1": ActionProgressActivityHandler(
            dependencies.pool
        ),
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
    all_modules = worker_modules(
        database_url,
        HandlerDependencies(
            pool=pool,
            storage=object_storage_from_environment(),
            mail_transport=mail_transport_from_environment(),
            payload_secret=os.environ["LEONAID_SESSION_ENCRYPTION_KEY"],
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
    )
    return pool, queue, worker
