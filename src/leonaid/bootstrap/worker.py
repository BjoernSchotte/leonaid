"""Concrete construction of the durable worker and its module contributions."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import asyncpg

from leonaid.adapters.mail.invoice_smtp import InvoiceSmtpHandler
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.mail.smtp import SmtpMailHandler
from leonaid.adapters.mail.transport import SmtpTransport
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
from leonaid.adapters.operations import structured_event
from leonaid.application.outbox import OutboxWorker
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    collect_handlers,
    collect_background_tasks,
)
from leonaid.modules.surveys.jobs import (
    handlers as survey_handlers,
    survey_timeout_loop,
)
from leonaid.platform.worker_signals import record_success
from leonaid.configuration import load_mail_transport_settings
from leonaid.domain.outbox import ClaimedOutboxEvent, RetryPolicy


def observe_job(
    name: str,
    event: ClaimedOutboxEvent,
    error_code: str | None,
    duration_ms: float | None,
) -> None:
    if name == "outbox.job.completed":
        record_success("job_completion")
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


async def build_worker(
    *,
    database_url: str,
    worker_id: str,
    max_attempts: int,
    base_backoff_seconds: float,
    claim_lease_seconds: float,
) -> tuple[asyncpg.Pool[Any], AsyncpgOutboxQueue, OutboxWorker]:
    pool = await create_pool(database_url, maximum_size=5)
    queue = AsyncpgOutboxQueue(
        pool,
        claim_lease=timedelta(seconds=claim_lease_seconds),
    )
    object_storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
        path_style=os.environ.get("OBJECT_STORAGE_PATH_STYLE", "true").casefold()
        == "true",
    )
    mail_settings = load_mail_transport_settings()
    mail_transport = SmtpTransport(
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
    handlers = collect_handlers(
        (
            ModuleRegistration(
                "surveys",
                handlers=survey_handlers(
                    pool,
                    object_storage,
                    mail_transport,
                    os.environ["LEONAID_SESSION_ENCRYPTION_KEY"],
                ),
            ),
            ModuleRegistration(
                "actions",
                handlers={
                    "charity_action.progress.recorded.v1": ActionProgressActivityHandler(
                        pool
                    ),
                },
            ),
            ModuleRegistration(
                "invoicing",
                handlers={
                    "invoice.document.render.requested.v1": InvoiceDocumentStorageHandler(
                        repository=AsyncpgGeneratedDocumentRepository(pool),
                        renderer=TypstInvoiceRenderer(),
                        storage=object_storage,
                    ),
                    "invoice.mail.send.requested.v1": InvoiceSmtpHandler(
                        repository=AsyncpgInvoiceDeliveryRepository(pool),
                        storage=object_storage,
                        transport=mail_transport,
                    ),
                },
            ),
            ModuleRegistration(
                "mail",
                handlers={
                    "mail.send.v1": SmtpMailHandler(
                        pool,
                        transport=mail_transport,
                        secure_payload=SecureMailPayload(
                            os.environ["LEONAID_SESSION_ENCRYPTION_KEY"]
                        ),
                    ),
                },
            ),
        )
    )
    worker = OutboxWorker(
        worker_id=worker_id,
        queue=queue,
        handlers=handlers,
        retry_policy=RetryPolicy(
            max_attempts=max_attempts,
            base_delay=timedelta(seconds=base_backoff_seconds),
            maximum_delay=timedelta(minutes=15),
        ),
        observer=observe_job,
        # Export rendering is repeatable; keep time for cancellation and queue update.
        # Legacy mail handlers retain their transport/recovery semantics.
        handler_timeouts={
            "survey.export.render.v1": min(240.0, claim_lease_seconds * 0.8),
        },
    )
    return pool, queue, worker


def background_tasks() -> dict[str, Callable[[], Awaitable[None]]]:
    return collect_background_tasks(
        (
            ModuleRegistration(
                "surveys",
                background_tasks={"surveys.deadlines": survey_timeout_loop},
            ),
        )
    )
