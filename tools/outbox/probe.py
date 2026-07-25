#!/usr/bin/env python3
"""Real-system acceptance probe for POC-022."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.adapters.mail.smtp import SmtpMailHandler
from leonaid.adapters.postgres.action_progress import (
    AsyncpgActionProgressUnitOfWorkFactory,
    AsyncpgTransactionalOutboxRepository,
)
from leonaid.adapters.postgres.pool import create_pool
from leonaid.application.action_progress import RecordActionProgress
from leonaid.application.errors import ApplicationError
from leonaid.domain.action_progress import RecordActionProgressCommand
from leonaid.domain.outbox import ClaimedOutboxEvent, PendingOutboxEvent, json_payload

USER_ADMIN = UUID("10000000-0000-4000-8000-000000000002")
USER_ACQUIRER = UUID("10000000-0000-4000-8000-000000000004")
ACTION = UUID("20000000-0000-4000-8000-000000000001")
COMPANY = UUID("40000000-0000-4000-8000-000000000001")
OFFERING = UUID("70000000-0000-4000-8000-000000000001")
COMMITMENT = UUID("80000000-0000-4000-8000-000000000001")
INVOICE = UUID("a0000000-0000-4000-8000-000000000001")
COMMAND = UUID("f1000000-0000-4000-8000-000000000001")
MAIL_EVENT = UUID("f3000000-0000-4000-8000-000000000001")
COMMAND_NAMESPACE = UUID("9fd77fa3-417a-47a6-9b73-e755f209b342")


def database_url() -> str:
    return os.environ["CORE_DATABASE_URL"]


async def prepare() -> None:
    connection = await asyncpg.connect(database_url())
    try:
        async with connection.transaction():
            await connection.executemany(
                """
                INSERT INTO user_account (id, email, display_name, status)
                VALUES ($1, $2, $3, 'active')
                """,
                [
                    (
                        USER_ADMIN,
                        "klara.kern@leonaid.invalid",
                        "Klara Kern",
                    ),
                    (
                        USER_ACQUIRER,
                        "anna.akquise@leonaid.invalid",
                        "Anna Akquise",
                    ),
                ],
            )
            await connection.execute(
                """
                INSERT INTO charity_action (
                    id, carrier_name, name, purpose, status, starts_on, ends_on,
                    archive_slug, goal_value, actual_value, goal_unit, currency
                )
                VALUES (
                    $1, 'Lions Club Beispielstadt', 'Krapfentaxi 2026',
                    'POC-022 Golden Data', 'active', DATE '2026-09-01',
                    DATE '2026-11-15', 'krapfentaxi-2026', 100000, 0,
                    'cent', 'EUR'
                )
                """,
                ACTION,
            )
            await connection.executemany(
                """
                INSERT INTO action_membership (
                    id, action_id, user_id, role
                )
                VALUES ($1, $2, $3, $4)
                """,
                [
                    (
                        UUID("21000000-0000-4000-8000-000000000001"),
                        ACTION,
                        USER_ADMIN,
                        "charity_admin",
                    ),
                    (
                        UUID("21000000-0000-4000-8000-000000000004"),
                        ACTION,
                        USER_ACQUIRER,
                        "acquirer",
                    ),
                ],
            )
    finally:
        await connection.close()
    print("poc022: Golden-Data-Grundlage vorbereitet")


def progress_command(
    command_id: UUID = COMMAND,
    value: Decimal = Decimal("720.2500"),
) -> RecordActionProgressCommand:
    return RecordActionProgressCommand(
        command_id=command_id,
        action_id=ACTION,
        actor_user_id=USER_ADMIN,
        actual_value=value,
        request_id=f"poc022:{command_id}",
    )


async def produce_crash() -> None:
    pool = await create_pool(database_url())
    service = RecordActionProgress(AsyncpgActionProgressUnitOfWorkFactory(pool))
    result = await service.execute(progress_command())
    print(
        json.dumps(
            {
                "committed": True,
                "outboxEventId": str(result.outbox_event_id),
                "dispatchStarted": False,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    os._exit(23)


async def verify_crash_boundary() -> None:
    connection = await asyncpg.connect(database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT
              (SELECT actual_value FROM charity_action WHERE id = $1) AS value,
              (SELECT count(*) FROM audit_event WHERE action_id = $1) AS audits,
              (SELECT count(*) FROM outbox_event WHERE aggregate_id = $1) AS outbox,
              (SELECT count(*) FROM activity_event WHERE action_id = $1) AS activities,
              (SELECT count(*) FROM command_receipt) AS receipts
            """,
            ACTION,
        )
    finally:
        await connection.close()
    expected = {
        "value": Decimal("720.2500"),
        "audits": 1,
        "outbox": 1,
        "activities": 0,
        "receipts": 1,
    }
    if row is None or dict(row) != expected:
        raise RuntimeError(f"Commit/Dispatch-Grenze inkonsistent: {dict(row or {})}")
    print("poc022: Commit überlebte Prozessende ohne vorgetäuschten Versand")


async def verify_recovery() -> None:
    pool = await create_pool(database_url())
    try:
        result = await RecordActionProgress(
            AsyncpgActionProgressUnitOfWorkFactory(pool)
        ).execute(progress_command())
        if not result.replayed:
            raise RuntimeError("Wiederholter Befehl wurde nicht als Replay erkannt.")
        try:
            await RecordActionProgress(
                AsyncpgActionProgressUnitOfWorkFactory(pool)
            ).execute(progress_command(value=Decimal("999.0000")))
        except ApplicationError as error:
            if error.code != "idempotency_conflict":
                raise
        else:
            raise RuntimeError("Abweichendes Replay wurde nicht abgewiesen.")
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT
                  (SELECT count(*) FROM audit_event WHERE action_id = $1) AS audits,
                  (SELECT count(*) FROM outbox_event WHERE aggregate_id = $1) AS outbox,
                  (SELECT count(*) FROM activity_event WHERE action_id = $1) AS activities,
                  (
                    SELECT count(*)
                    FROM activity_event_recipient AS recipient
                    JOIN activity_event AS event
                      ON event.id = recipient.activity_event_id
                    WHERE event.action_id = $1
                  ) AS recipients,
                  (
                    SELECT min(status)
                    FROM outbox_event
                    WHERE aggregate_id = $1
                  ) AS status
                """,
                ACTION,
            )
    finally:
        await pool.close()
    expected = {
        "audits": 1,
        "outbox": 1,
        "activities": 1,
        "recipients": 2,
        "status": "completed",
    }
    if row is None or dict(row) != expected:
        raise RuntimeError(f"Recovery war nicht genau-einmalig: {dict(row or {})}")
    print("poc022: spätere fachliche Projektion genau einmal verarbeitet")


async def produce_many(count: int) -> None:
    pool = await create_pool(database_url(), maximum_size=10)
    service = RecordActionProgress(AsyncpgActionProgressUnitOfWorkFactory(pool))
    try:
        for index in range(count):
            command_id = uuid5(COMMAND_NAMESPACE, f"concurrency:{index}")
            await service.execute(
                progress_command(
                    command_id,
                    Decimal(1000 + index),
                )
            )
    finally:
        await pool.close()
    print(f"poc022: {count} konkurrierende Worker-Jobs erzeugt")


async def verify_concurrency(count: int) -> None:
    connection = await asyncpg.connect(database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT
              count(*) FILTER (
                WHERE status = 'completed'
              ) AS completed,
              count(*) FILTER (
                WHERE status <> 'completed'
              ) AS unfinished,
              count(DISTINCT last_worker_id) FILTER (
                WHERE last_worker_id IN ('poc022-worker-a', 'poc022-worker-b')
              ) AS workers,
              count(*) FILTER (
                WHERE attempts <> 1
              ) AS multiple_attempts
            FROM outbox_event
            WHERE event_type = 'charity_action.progress.recorded.v1'
            """
        )
        activities = await connection.fetchval(
            """
            SELECT count(*)
            FROM activity_event
            WHERE event_type = 'charity_action.progress.recorded'
            """
        )
    finally:
        await connection.close()
    expected_total = count + 1
    if row is None or dict(row) != {
        "completed": expected_total,
        "unfinished": 0,
        "workers": 2,
        "multiple_attempts": 0,
    }:
        raise RuntimeError(f"Worker-Konkurrenz inkonsistent: {dict(row or {})}")
    if activities != expected_total:
        raise RuntimeError(f"Projektionen {activities} statt {expected_total}")
    print("poc022: zwei zusätzliche Prozesse teilten Jobs ohne Doppelverarbeitung")


def mail_event() -> PendingOutboxEvent:
    return PendingOutboxEvent(
        id=MAIL_EVENT,
        aggregate_type="charity_action",
        aggregate_id=ACTION,
        event_type="mail.send.v1",
        idempotency_key="poc022:mail:golden-v1",
        payload={
            "to": "sponsor@leonaid.invalid",
            "subject": "LeonAid POC-022 Versandnachweis",
            "text": "Diese synthetische Nachricht beweist Retry und Idempotenz.",
        },
    )


async def enqueue_mail() -> None:
    connection = await asyncpg.connect(database_url())
    try:
        async with connection.transaction():
            await AsyncpgTransactionalOutboxRepository(connection).append(mail_event())
    finally:
        await connection.close()
    print("poc022: reale SMTP-Wirkung durable eingeplant")


async def verify_dead_letter() -> None:
    connection = await asyncpg.connect(database_url())
    try:
        row = await connection.fetchrow(
            """
            SELECT status, attempts, dead_lettered_at IS NOT NULL AS dead,
                   last_error_code, last_error_detail IS NOT NULL AS detail,
                   manual_retry_count
            FROM outbox_event
            WHERE id = $1
            """,
            MAIL_EVENT,
        )
    finally:
        await connection.close()
    if row is None:
        raise RuntimeError("Mail-Outbox-Event fehlt.")
    state = dict(row)
    if (
        state["status"] != "dead_letter"
        or state["attempts"] != 3
        or state["dead"] is not True
        or state["detail"] is not True
        or state["manual_retry_count"] != 0
    ):
        raise RuntimeError(f"Dead-Letter-Zustand inkonsistent: {state}")
    print(
        "poc022: Retry, Versuchszahl, Fehlercode und Dead Letter real sichtbar "
        f"({state['last_error_code']})"
    )


async def replay_and_verify_mail() -> None:
    pool = await create_pool(database_url())
    state: asyncpg.Record | None = None
    try:
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM outbox_event WHERE id = $1",
                MAIL_EVENT,
            )
        if row is None:
            raise RuntimeError("Mail-Outbox-Event fehlt.")
        handler = SmtpMailHandler(
            pool,
            host=os.environ["MAILPIT_SMTP_HOST"],
            port=int(os.environ["MAILPIT_SMTP_PORT"]),
            sender=os.environ.get(
                "LEONAID_MAIL_FROM",
                "LeonAid <noreply@leonaid.invalid>",
            ),
        )
        replay = ClaimedOutboxEvent(
            id=row["id"],
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=row["aggregate_id"],
            event_type=str(row["event_type"]),
            idempotency_key=str(row["idempotency_key"]),
            payload=json_payload(row["payload"]),
            attempts=int(row["attempts"]),
            claim_token=UUID("f4000000-0000-4000-8000-000000000001"),
            claimed_by="poc022-replay-proof",
        )
        await handler.handle(replay)
        await handler.handle(replay)
        await verify_business_idempotency(pool)
        async with pool.acquire() as connection:
            state = await connection.fetchrow(
                """
                SELECT status, attempts, manual_retry_count,
                       last_manual_retry_by, last_error_code,
                       (SELECT count(*) FROM mail_delivery) AS deliveries,
                       (SELECT count(*) FROM commitment
                        WHERE idempotency_key = 'poc022:commitment:golden-v1')
                          AS commitments,
                       (SELECT count(*) FROM invoice
                        WHERE idempotency_key = 'poc022:invoice:golden-v1')
                          AS invoices
                FROM outbox_event
                WHERE id = $1
                """,
                MAIL_EVENT,
            )
    finally:
        await pool.close()

    response = httpx.get(
        f"{os.environ['MAILPIT_API_URL'].rstrip('/')}/api/v1/messages",
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or len(messages) != 1:
        raise RuntimeError(f"Mailpit enthält nicht exakt eine Mail: {payload}")
    expected = {
        "status": "completed",
        "attempts": 4,
        "manual_retry_count": 1,
        "last_manual_retry_by": "poc022-operator",
        "last_error_code": None,
        "deliveries": 1,
        "commitments": 1,
        "invoices": 1,
    }
    if state is None or dict(state) != expected:
        raise RuntimeError(f"Idempotenznachweis inkonsistent: {dict(state or {})}")
    print(
        "poc022: manueller Wiederanlauf und Replay erzeugten je genau eine "
        "Bestellung, Rechnung und Mail"
    )


async def verify_business_idempotency(pool: asyncpg.Pool[Any]) -> None:
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO offering (
                    id, action_id, name, status, unit, pieces_per_unit,
                    unit_price_minor, currency
                )
                VALUES ($1, $2, 'Krapfenbox', 'active', 'box', 24, 3600, 'EUR')
                ON CONFLICT (id) DO NOTHING
                """,
                OFFERING,
                ACTION,
            )
            for candidate_commitment in (
                COMMITMENT,
                UUID("80000000-0000-4000-8000-000000000099"),
            ):
                returned_commitment = await connection.fetchval(
                    """
                    INSERT INTO commitment (
                        id, action_id, twenty_company_id, source, status,
                        customer_snapshot, currency, total_minor,
                        idempotency_key
                    )
                    VALUES (
                        $1, $2, $3, 'public_form', 'confirmed',
                        '{"name":"Musterwerk GmbH"}'::jsonb, 'EUR', 3600, $4
                    )
                    ON CONFLICT (idempotency_key) DO UPDATE
                    SET idempotency_key = EXCLUDED.idempotency_key
                    RETURNING id
                    """,
                    candidate_commitment,
                    ACTION,
                    COMPANY,
                    "poc022:commitment:golden-v1",
                )
                if returned_commitment != COMMITMENT:
                    raise RuntimeError("Commitment-Idempotenz lieferte eine andere ID.")
            for candidate_invoice, candidate_number in (
                (INVOICE, "KT26-POC022"),
                (
                    UUID("a0000000-0000-4000-8000-000000000099"),
                    "KT26-POC022-DUP",
                ),
            ):
                returned_invoice = await connection.fetchval(
                    """
                    INSERT INTO invoice (
                        id, commitment_id, number, status, currency,
                        net_minor, tax_minor, gross_minor, recipient_snapshot,
                        line_snapshot, tax_note, document_version,
                        idempotency_key
                    )
                    VALUES (
                        $1, $2, $3, 'draft', 'EUR',
                        3600, 0, 3600, '{"name":"Musterwerk GmbH"}'::jsonb,
                        '[{"quantity":1,"unitPriceMinor":3600}]'::jsonb,
                        'Kein Steuerausweis im synthetischen Nachweis.', 1, $4
                    )
                    ON CONFLICT (idempotency_key) DO UPDATE
                    SET idempotency_key = EXCLUDED.idempotency_key
                    RETURNING id
                    """,
                    candidate_invoice,
                    COMMITMENT,
                    candidate_number,
                    "poc022:invoice:golden-v1",
                )
                if returned_invoice != INVOICE:
                    raise RuntimeError("Rechnungs-Idempotenz lieferte eine andere ID.")


async def run(arguments: argparse.Namespace) -> None:
    if arguments.command == "prepare":
        await prepare()
    elif arguments.command == "produce-crash":
        await produce_crash()
    elif arguments.command == "verify-crash":
        await verify_crash_boundary()
    elif arguments.command == "verify-recovery":
        await verify_recovery()
    elif arguments.command == "produce-many":
        await produce_many(arguments.count)
    elif arguments.command == "verify-concurrency":
        await verify_concurrency(arguments.count)
    elif arguments.command == "enqueue-mail":
        await enqueue_mail()
    elif arguments.command == "verify-dead-letter":
        await verify_dead_letter()
    elif arguments.command == "replay-and-verify-mail":
        await replay_and_verify_mail()
    else:
        raise RuntimeError(f"Unbekannter Probe-Befehl: {arguments.command}")


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description=__doc__)
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    for name in (
        "prepare",
        "produce-crash",
        "verify-crash",
        "verify-recovery",
        "enqueue-mail",
        "verify-dead-letter",
        "replay-and-verify-mail",
    ):
        subcommands.add_parser(name)
    produce_many_command = subcommands.add_parser("produce-many")
    produce_many_command.add_argument("--count", type=int, default=20)
    verify_concurrency_command = subcommands.add_parser("verify-concurrency")
    verify_concurrency_command.add_argument("--count", type=int, default=20)
    return command_parser


def main() -> None:
    asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    main()
