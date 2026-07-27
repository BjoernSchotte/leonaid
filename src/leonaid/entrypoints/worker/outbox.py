"""Executable composition root and operational CLI for the durable outbox."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.adapters.mail.invoice_smtp import InvoiceSmtpHandler
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.mail.smtp import SmtpMailHandler
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
from leonaid.application.outbox import OutboxEventHandler, OutboxWorker
from leonaid.domain.outbox import OutboxState, RetryPolicy


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
    handlers: dict[str, OutboxEventHandler] = {
        "charity_action.progress.recorded.v1": ActionProgressActivityHandler(pool),
        "invoice.document.render.requested.v1": InvoiceDocumentStorageHandler(
            repository=AsyncpgGeneratedDocumentRepository(pool),
            renderer=TypstInvoiceRenderer(),
            storage=object_storage,
        ),
        "invoice.mail.send.requested.v1": InvoiceSmtpHandler(
            repository=AsyncpgInvoiceDeliveryRepository(pool),
            storage=object_storage,
            host=os.environ.get("MAILPIT_SMTP_HOST", "mailpit"),
            port=int(os.environ.get("MAILPIT_SMTP_PORT", "1025")),
            sender=os.environ.get(
                "LEONAID_MAIL_FROM",
                "LeonAid <noreply@leonaid.invalid>",
            ),
        ),
        "mail.send.v1": SmtpMailHandler(
            pool,
            host=os.environ.get("MAILPIT_SMTP_HOST", "mailpit"),
            port=int(os.environ.get("MAILPIT_SMTP_PORT", "1025")),
            sender=os.environ.get(
                "LEONAID_MAIL_FROM",
                "LeonAid <noreply@leonaid.invalid>",
            ),
            secure_payload=SecureMailPayload(
                os.environ["LEONAID_SESSION_ENCRYPTION_KEY"]
            ),
        ),
    }
    worker = OutboxWorker(
        worker_id=worker_id,
        queue=queue,
        handlers=handlers,
        retry_policy=RetryPolicy(
            max_attempts=max_attempts,
            base_delay=timedelta(seconds=base_backoff_seconds),
            maximum_delay=timedelta(minutes=15),
        ),
    )
    return pool, queue, worker


async def execute(arguments: argparse.Namespace) -> int:
    database_url = os.environ["CORE_DATABASE_URL"]
    pool, queue, worker = await build_worker(
        database_url=database_url,
        worker_id=arguments.worker_id,
        max_attempts=arguments.max_attempts,
        base_backoff_seconds=arguments.base_backoff_seconds,
        claim_lease_seconds=arguments.claim_lease_seconds,
    )
    try:
        if arguments.command == "run-once":
            print(
                json.dumps(
                    {"handled": await worker.run_once()},
                    separators=(",", ":"),
                )
            )
            return 0
        if arguments.command == "run-until-idle":
            handled = await worker.run_until_idle(
                maximum_events=arguments.maximum_events
            )
            print(json.dumps({"handled": handled}, separators=(",", ":")))
            return 0
        if arguments.command == "retry":
            retried_state = await queue.manual_retry(
                event_id=UUID(arguments.event_id),
                operator=arguments.operator,
                now=datetime.now(timezone.utc),
            )
            print(json.dumps(_json_state(retried_state), separators=(",", ":")))
            return 0
        if arguments.command == "status":
            current_state = await queue.state(UUID(arguments.event_id))
            if current_state is None:
                print(
                    json.dumps(
                        {"errorCode": "outbox_event_not_found"},
                        separators=(",", ":"),
                    )
                )
                return 4
            print(json.dumps(_json_state(current_state), separators=(",", ":")))
            return 0
        raise RuntimeError(f"Unbekannter Worker-Befehl: {arguments.command}")
    finally:
        await pool.close()


def _json_state(state: OutboxState) -> dict[str, object]:
    values = asdict(state)
    return {
        key: (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
        )
        for key, value in values.items()
    }


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description=__doc__)
    command_parser.add_argument(
        "--worker-id",
        default=f"{socket.gethostname()}-{os.getpid()}",
    )
    command_parser.add_argument("--max-attempts", type=int, default=5)
    command_parser.add_argument("--base-backoff-seconds", type=float, default=5)
    command_parser.add_argument("--claim-lease-seconds", type=float, default=300)
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("run-once")
    run_until_idle = subcommands.add_parser("run-until-idle")
    run_until_idle.add_argument("--maximum-events", type=int, default=10_000)
    retry = subcommands.add_parser("retry")
    retry.add_argument("event_id")
    retry.add_argument("--operator", required=True)
    status = subcommands.add_parser("status")
    status.add_argument("event_id")
    return command_parser


def main() -> None:
    raise SystemExit(asyncio.run(execute(parser().parse_args())))


if __name__ == "__main__":
    main()
