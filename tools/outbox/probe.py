#!/usr/bin/env python3
"""Real-system acceptance probe for POC-022."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4, uuid5

import asyncpg
import httpx

from leonaid.adapters.mail.smtp import SmtpMailHandler
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.adapters.postgres.action_progress import (
    AsyncpgActionProgressUnitOfWorkFactory,
    AsyncpgTransactionalOutboxRepository,
)
from leonaid.adapters.postgres.outbox import (
    OUTBOX_DETACHED_REFERENCES,
    OUTBOX_REFERENCES,
    AsyncpgOutboxQueue,
)
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.security import AsyncpgSecurityRateLimitRepository
from leonaid.application.action_progress import RecordActionProgress
from leonaid.application.errors import ApplicationError
from leonaid.application.outbox import OutboxWorker
from leonaid.configuration import RetentionSettings
from leonaid.domain.action_progress import RecordActionProgressCommand
from leonaid.domain.outbox import (
    ClaimedOutboxEvent,
    PendingOutboxEvent,
    RetryPolicy,
    json_payload,
)
from leonaid.entrypoints.worker.retention import sweep_operational_retention

USER_ADMIN = UUID("10000000-0000-4000-8000-000000000002")
USER_ACQUIRER = UUID("10000000-0000-4000-8000-000000000004")
ACTION = UUID("20000000-0000-4000-8000-000000000001")
COMPANY = UUID("40000000-0000-4000-8000-000000000001")
OFFERING = UUID("70000000-0000-4000-8000-000000000001")
COMMITMENT = UUID("80000000-0000-4000-8000-000000000001")
INVOICE = UUID("a0000000-0000-4000-8000-000000000001")
COMMAND = UUID("f1000000-0000-4000-8000-000000000001")
MAIL_EVENT = UUID("f3000000-0000-4000-8000-000000000001")
CLAIM_LOSS_EVENT = UUID("f3000000-0000-4000-8000-000000000002")
CLAIM_LOSS_EVENT_TYPE = "probe.claim_loss.v1"
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
    print("poc022: golden data baseline prepared")


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
        raise RuntimeError(f"commit/dispatch boundary inconsistent: {dict(row or {})}")
    print("poc022: commit survived process exit without a faked send")


async def verify_recovery() -> None:
    pool = await create_pool(database_url())
    try:
        result = await RecordActionProgress(
            AsyncpgActionProgressUnitOfWorkFactory(pool)
        ).execute(progress_command())
        if not result.replayed:
            raise RuntimeError("Repeated command was not detected as a replay.")
        try:
            await RecordActionProgress(
                AsyncpgActionProgressUnitOfWorkFactory(pool)
            ).execute(progress_command(value=Decimal("999.0000")))
        except ApplicationError as error:
            if error.code != "idempotency_conflict":
                raise
        else:
            raise RuntimeError("Divergent replay was not rejected.")
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
        raise RuntimeError(f"Recovery was not exactly-once: {dict(row or {})}")
    print("poc022: later domain projection processed exactly once")


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
    print(f"poc022: {count} competing worker jobs created")


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
        raise RuntimeError(f"worker concurrency inconsistent: {dict(row or {})}")
    if activities != expected_total:
        raise RuntimeError(f"projections {activities} instead of {expected_total}")
    print("poc022: two extra processes shared jobs without double processing")


def mail_event() -> PendingOutboxEvent:
    return PendingOutboxEvent(
        id=MAIL_EVENT,
        aggregate_type="charity_action",
        aggregate_id=ACTION,
        event_type="mail.send.v1",
        idempotency_key="poc022:mail:golden-v1",
        payload={
            "to": "sponsor@leonaid.invalid",
            "subject": "LeonAid POC-022 delivery proof",
            "text": "This synthetic message proves retry and idempotency.",
        },
    )


async def enqueue_mail() -> None:
    connection = await asyncpg.connect(database_url())
    try:
        async with connection.transaction():
            await AsyncpgTransactionalOutboxRepository(connection).append(mail_event())
    finally:
        await connection.close()
    print("poc022: real SMTP effect scheduled durably")


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
        raise RuntimeError("Mail outbox event missing.")
    state = dict(row)
    if (
        state["status"] != "dead_letter"
        or state["attempts"] != 3
        or state["dead"] is not True
        or state["detail"] is not True
        or state["manual_retry_count"] != 0
    ):
        raise RuntimeError(f"dead-letter state inconsistent: {state}")
    print(
        "poc022: retry, attempt count, error code and dead letter visible for real "
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
            raise RuntimeError("Mail outbox event missing.")
        handler = SmtpMailHandler(
            pool,
            transport=SmtpTransport(
                host=os.environ["MAIL_SMTP_HOST"],
                port=int(os.environ["MAIL_SMTP_PORT"]),
                sender=os.environ.get(
                    "MAIL_FROM",
                    "LeonAid <noreply@leonaid.invalid>",
                ),
                mode="plain",
                username=None,
                password=None,
                timeout_seconds=10,
                verify_certificates=True,
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
        f"{os.environ['MAIL_TEST_API_URL'].rstrip('/')}/api/v1/messages",
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or len(messages) != 1:
        raise RuntimeError(f"Mailpit does not hold exactly one mail: {payload}")
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
        raise RuntimeError(f"idempotency evidence inconsistent: {dict(state or {})}")
    print(
        "poc022: manual restart and replay each created exactly one "
        "order, invoice and mail"
    )


async def verify_business_idempotency(pool: asyncpg.Pool[Any]) -> None:
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO offering (
                    id, action_id, code, name, status, unit,
                    allowed_quantity_units, pieces_per_unit,
                    unit_price_minor, currency
                )
                VALUES (
                    $1, $2, 'krapfenbox-24', 'Krapfenbox',
                    'active', 'box', ARRAY['box']::text[], 24, 3600, 'EUR'
                )
                ON CONFLICT (id) DO NOTHING
                """,
                OFFERING,
                ACTION,
            )
            for candidate_commitment, public_reference in (
                (COMMITMENT, "LA-POC022-001"),
                (
                    UUID("80000000-0000-4000-8000-000000000099"),
                    "LA-POC022-099",
                ),
            ):
                returned_commitment = await connection.fetchval(
                    """
                    INSERT INTO commitment (
                        id, action_id, twenty_company_id, source, status,
                        customer_snapshot, currency, total_minor,
                        delivery_recipient_snapshot, public_reference,
                        idempotency_key
                    )
                    VALUES (
                        $1, $2, $3, 'public_form', 'confirmed',
                        '{"name":"Musterwerk GmbH"}'::jsonb, 'EUR', 3600,
                        '{
                          "recipientName":"Musterwerk GmbH",
                          "streetLine1":"Goldenweg 1",
                          "postalCode":"12345",
                          "city":"Musterstadt",
                          "countryCode":"DE"
                        }'::jsonb,
                        $4, $5
                    )
                    ON CONFLICT (idempotency_key) DO UPDATE
                    SET idempotency_key = EXCLUDED.idempotency_key
                    RETURNING id
                    """,
                    candidate_commitment,
                    ACTION,
                    COMPANY,
                    public_reference,
                    "poc022:commitment:golden-v1",
                )
                if returned_commitment != COMMITMENT:
                    raise RuntimeError(
                        "Commitment idempotency returned a different ID."
                    )
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
                        id, action_id, commitment_id, number, status,
                        issued_at, service_on, due_on, currency,
                        net_minor, tax_minor, gross_minor, issuer_snapshot,
                        payment_details_snapshot, recipient_snapshot,
                        line_snapshot, tax_treatment,
                        tax_rate_basis_points, tax_note, payment_reference,
                        approved_by_user_id, document_version, idempotency_key
                    )
                    VALUES (
                        $1, $2, $3, $4, 'issued',
                        CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_DATE + 14,
                        'EUR', 3600, 0, 3600,
                        '{
                          "legalName":"Lions Club Beispielstadt",
                          "streetLine1":"Goldenweg 1",
                          "postalCode":"12345",
                          "city":"Musterstadt",
                          "countryCode":"DE",
                          "taxIdentifier":"POC022",
                          "email":"poc022@leonaid.invalid"
                        }'::jsonb,
                        '{
                          "accountHolder":"Lions Club Beispielstadt",
                          "iban":"DE89370400440532013000",
                          "bic":"COBADEFFXXX"
                        }'::jsonb,
                        '{
                          "recipientName":"Musterwerk GmbH",
                          "streetLine1":"Goldenweg 1",
                          "postalCode":"12345",
                          "city":"Musterstadt",
                          "countryCode":"DE",
                          "email":null
                        }'::jsonb,
                        '[{
                          "description":"Krapfenbox",
                          "quantity":1,
                          "unit":"box",
                          "unitPriceGrossMinor":3600,
                          "taxRateBasisPoints":0,
                          "netMinor":3600,
                          "taxMinor":0,
                          "grossMinor":3600,
                          "currency":"EUR"
                        }]'::jsonb,
                        'small_business', 0,
                        'Kein Steuerausweis im synthetischen Nachweis.',
                        $4, $5, 1, $6
                    )
                    ON CONFLICT (idempotency_key) DO UPDATE
                    SET idempotency_key = EXCLUDED.idempotency_key
                    RETURNING id
                    """,
                    candidate_invoice,
                    ACTION,
                    COMMITMENT,
                    candidate_number,
                    USER_ADMIN,
                    "poc022:invoice:golden-v1",
                )
                if returned_invoice != INVOICE:
                    raise RuntimeError("Invoice idempotency returned a different ID.")


class LeaseTakeoverHandler:
    """Lets a second real worker take over the claim while this handler runs."""

    def __init__(self, queue: AsyncpgOutboxQueue) -> None:
        self._queue = queue
        self.takeover: ClaimedOutboxEvent | None = None

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        # A claim time one hour ahead makes the first worker's lease stale.
        self.takeover = await self._queue.claim_next(
            worker_id="poc022-takeover-worker",
            now=datetime.now(timezone.utc) + timedelta(hours=1),
        )


async def verify_claim_loss() -> None:
    pool = await create_pool(database_url())
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await AsyncpgTransactionalOutboxRepository(connection).append(
                    PendingOutboxEvent(
                        id=CLAIM_LOSS_EVENT,
                        aggregate_type="charity_action",
                        aggregate_id=ACTION,
                        event_type=CLAIM_LOSS_EVENT_TYPE,
                        idempotency_key="poc022:claim-loss:v1",
                        payload={},
                    )
                )
        queue = AsyncpgOutboxQueue(pool, claim_lease=timedelta(minutes=5))
        handler = LeaseTakeoverHandler(queue)
        observed: list[str] = []
        worker = OutboxWorker(
            worker_id="poc022-slow-worker",
            queue=queue,
            handlers={CLAIM_LOSS_EVENT_TYPE: handler},
            retry_policy=RetryPolicy(
                max_attempts=3,
                base_delay=timedelta(0),
                maximum_delay=timedelta(0),
            ),
            observer=lambda name, _event, _code: observed.append(name),
        )
        if not await worker.run_once():
            raise RuntimeError("Claim-loss event was not claimed.")
        takeover = handler.takeover
        if takeover is None or takeover.id != CLAIM_LOSS_EVENT:
            raise RuntimeError("The second worker did not take over the stale claim.")
        if observed != ["outbox.job.claimed", "outbox.job.claim_lost"]:
            raise RuntimeError(f"Unexpected worker observations: {observed}")
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT status, claimed_by, attempts FROM outbox_event WHERE id = $1",
                CLAIM_LOSS_EVENT,
            )
        if row is None or (row["status"], row["claimed_by"], row["attempts"]) != (
            "processing",
            "poc022-takeover-worker",
            2,
        ):
            raise RuntimeError(
                f"Stale worker overwrote the new claim: {dict(row or {})}"
            )
        await queue.complete(
            event_id=CLAIM_LOSS_EVENT,
            claim_token=takeover.claim_token,
            completed_at=datetime.now(timezone.utc),
        )
        state = await queue.state(CLAIM_LOSS_EVENT)
        if state is None or state.status != "completed":
            raise RuntimeError(f"Takeover worker could not complete: {state}")
    finally:
        await pool.close()
    print("poc022: stale claim was reported as lost and left to the new owner")


RETENTION_EVENT_TYPE = "probe.retention.v1"
RETENTION_CLAIM_EVENT_TYPE = "probe.retention.claim.v1"
RETENTION_SCOPE = "probe.retention"
RETENTION_FINGERPRINT = "ab" * 32
RETENTION_CLI_EVENTS = (
    UUID("f4000000-0000-4000-8000-000000000101"),
    UUID("f4000000-0000-4000-8000-000000000102"),
)


async def insert_retention_event(
    connection: asyncpg.Connection[Any],
    *,
    status: str,
    created_at: datetime,
    completed_at: datetime | None = None,
    dead_lettered_at: datetime | None = None,
    available_at: datetime | None = None,
    claimed_at: datetime | None = None,
    event_id: UUID | None = None,
    event_type: str = RETENTION_EVENT_TYPE,
) -> UUID:
    identifier = event_id or uuid4()
    processing = status == "processing"
    await connection.execute(
        """
        INSERT INTO outbox_event (
            id, aggregate_type, aggregate_id, event_type, idempotency_key,
            payload, status, attempts, available_at, created_at, completed_at,
            dead_lettered_at, claimed_at, claim_token, claimed_by
        )
        VALUES (
            $1, 'charity_action', $2, $3, $4, '{}'::json, $5, 1, $6, $7, $8,
            $9, $10, $11, $12
        )
        """,
        identifier,
        ACTION,
        event_type,
        f"poc022:retention:{identifier}",
        status,
        available_at or created_at,
        created_at,
        completed_at,
        dead_lettered_at,
        claimed_at,
        uuid4() if processing else None,
        "poc022-retention-holder" if processing else None,
    )
    return identifier


def retention_settings(*, batch_size: int, max_batches: int) -> RetentionSettings:
    # model_validate skips the environment, so the proof is deterministic.
    return RetentionSettings.model_validate(
        {"outbox_days": 30, "batch_size": batch_size, "max_batches": max_batches}
    )


async def outbox_status(pool: asyncpg.Pool[Any], event_id: UUID) -> str | None:
    async with pool.acquire() as connection:
        value = await connection.fetchval(
            "SELECT status FROM outbox_event WHERE id = $1", event_id
        )
    return None if value is None else str(value)


async def verify_retention_references(connection: asyncpg.Connection[Any]) -> None:
    rows = await connection.fetch(
        """
        SELECT constraint_row.conrelid::regclass::text AS table_name,
               attribute.attname AS column_name,
               constraint_row.confdeltype::text AS on_delete
        FROM pg_constraint AS constraint_row
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = constraint_row.conrelid
         AND attribute.attnum = ANY (constraint_row.conkey)
        WHERE constraint_row.contype = 'f'
          AND constraint_row.confrelid = 'outbox_event'::regclass
        """
    )
    # confdeltype: 'n' = SET NULL; every other kept reference must block deletes.
    actual = {
        (str(row["table_name"]), str(row["column_name"]), row["on_delete"] == "n")
        for row in rows
    }
    expected = {
        (table, column, False)
        for table, column, enforced in OUTBOX_REFERENCES
        if enforced
    } | {(table, column, True) for table, column in OUTBOX_DETACHED_REFERENCES}
    if actual != expected:
        raise RuntimeError(
            "Outbox foreign keys differ from the retention reference list: "
            f"database={sorted(actual)} retention={sorted(expected)}"
        )


async def verify_retention() -> None:
    """Prove what retention deletes, what it keeps and that it never blocks."""

    pool = await create_pool(database_url())
    queue = AsyncpgOutboxQueue(pool, claim_lease=timedelta(minutes=5))
    rate_limits = AsyncpgSecurityRateLimitRepository(pool)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=31)
    recent = now - timedelta(days=1)
    try:
        async with pool.acquire() as connection:
            await verify_retention_references(connection)
            async with connection.transaction():
                old_completed = [
                    await insert_retention_event(
                        connection,
                        status="completed",
                        created_at=old - timedelta(hours=1),
                        completed_at=old + timedelta(minutes=index),
                    )
                    for index in range(7)
                ]
                locked_completed = await insert_retention_event(
                    connection,
                    status="completed",
                    created_at=old - timedelta(hours=1),
                    completed_at=old + timedelta(hours=1),
                )
                kept = {
                    "recent completed": await insert_retention_event(
                        connection,
                        status="completed",
                        created_at=recent,
                        completed_at=recent,
                    ),
                    "old dead letter": await insert_retention_event(
                        connection,
                        status="dead_letter",
                        created_at=old,
                        dead_lettered_at=old,
                    ),
                    "old pending retry": await insert_retention_event(
                        connection,
                        status="pending",
                        created_at=old,
                        available_at=now + timedelta(days=1),
                    ),
                    "old processing": await insert_retention_event(
                        connection,
                        status="processing",
                        created_at=old,
                        claimed_at=now,
                    ),
                    "old completed survey erasure": await insert_retention_event(
                        connection,
                        status="completed",
                        created_at=old,
                        completed_at=old,
                    ),
                }
                await connection.execute(
                    """
                    INSERT INTO survey_deletion (
                        survey_id, requested_by, operation_hash,
                        expected_revision, event_id, requested_at, completed_at
                    )
                    VALUES ($1, $2, $3, 1, $4, $5, $5)
                    """,
                    uuid4(),
                    USER_ADMIN,
                    "0" * 64,
                    kept["old completed survey erasure"],
                    old,
                )
                # The sent mail of the earlier steps: its job expires, while
                # the mail_delivery evidence stays without the link.
                # Younger than the batch rows above, so the bounded batch
                # below still takes exactly the three oldest of those.
                await connection.execute(
                    "UPDATE outbox_event SET completed_at = $2 WHERE id = $1 "
                    "AND status = 'completed'",
                    MAIL_EVENT,
                    old + timedelta(hours=2),
                )
                sent_mail_delivery_id = await connection.fetchval(
                    "SELECT id FROM mail_delivery WHERE outbox_event_id = $1",
                    MAIL_EVENT,
                )
                if sent_mail_delivery_id is None:
                    raise RuntimeError(
                        "The sent-mail job has no mail_delivery to detach."
                    )
                claimable = await insert_retention_event(
                    connection,
                    status="pending",
                    created_at=now - timedelta(seconds=1),
                    event_type=RETENTION_CLAIM_EVENT_TYPE,
                )
                await connection.executemany(
                    """
                    INSERT INTO security_rate_attempt (
                        id, scope, fingerprint_hash, attempted_at
                    )
                    VALUES ($1, $2, $3, $4)
                    """,
                    [
                        (
                            uuid4(),
                            RETENTION_SCOPE,
                            RETENTION_FINGERPRINT,
                            now - timedelta(days=3, minutes=index),
                        )
                        for index in range(5)
                    ]
                    + [
                        (
                            uuid4(),
                            RETENTION_SCOPE,
                            RETENTION_FINGERPRINT,
                            now - timedelta(minutes=30 + index),
                        )
                        for index in range(2)
                    ],
                )

        # The request path only counts and inserts; it no longer deletes.
        allowed = await rate_limits.consume(
            scope=RETENTION_SCOPE,
            fingerprint_hash=RETENTION_FINGERPRINT,
            attempted_at=now,
            window=timedelta(hours=1),
            limit=10,
        )
        async with pool.acquire() as connection:
            attempts = await connection.fetchval(
                "SELECT count(*) FROM security_rate_attempt WHERE scope = $1",
                RETENTION_SCOPE,
            )
        if not allowed or attempts != 8:
            raise RuntimeError(
                f"Rate-limit request path changed: allowed={allowed} rows={attempts}"
            )

        # One batch never deletes more than its limit, oldest first.
        deleted = await queue.purge_completed(
            completed_before=now - timedelta(days=30), limit=3
        )
        survivors = [
            event_id
            for event_id in old_completed
            if await outbox_status(pool, event_id) is not None
        ]
        if deleted != 3 or survivors != old_completed[3:]:
            raise RuntimeError(
                f"Batch was not bounded: deleted={deleted} survivors={len(survivors)}"
            )

        # A row locked by another session is skipped, not waited for, and a
        # worker claim runs concurrently with the sweep.
        holder = await asyncpg.connect(database_url())
        try:
            async with holder.transaction():
                await holder.execute(
                    "SELECT 1 FROM outbox_event WHERE id = $1 FOR UPDATE",
                    locked_completed,
                )
                settings = retention_settings(batch_size=2, max_batches=100)
                result, claim = await asyncio.wait_for(
                    asyncio.gather(
                        sweep_operational_retention(
                            queue=queue,
                            rate_limits=rate_limits,
                            settings=settings,
                            now=now,
                        ),
                        queue.claim_next(worker_id="poc022-retention-claimer", now=now),
                    ),
                    timeout=15,
                )
                if await outbox_status(pool, locked_completed) != "completed":
                    raise RuntimeError(
                        "Retention deleted a row another session locked."
                    )
        finally:
            await holder.close()
        if (
            result.outbox_events_deleted != 5
            or result.rate_attempts_deleted != 5
            or not result.complete
        ):
            raise RuntimeError(f"Unexpected retention sweep result: {result}")
        if claim is None or claim.id != claimable:
            raise RuntimeError(f"Concurrent claim was disturbed: {claim}")
        await queue.complete(
            event_id=claim.id,
            claim_token=claim.claim_token,
            completed_at=datetime.now(timezone.utc),
        )

        # The released row goes with a later sweep. Three expired rows with a
        # cap of two one-row batches leave one behind and report it.
        async with pool.acquire() as connection:
            extra = [
                await insert_retention_event(
                    connection,
                    status="completed",
                    created_at=old,
                    completed_at=old + timedelta(seconds=index + 1),
                )
                for index in range(2)
            ]
        capped = await sweep_operational_retention(
            queue=queue,
            rate_limits=rate_limits,
            settings=retention_settings(batch_size=1, max_batches=2),
            now=now,
        )
        if capped.outbox_events_deleted != 2 or capped.complete:
            raise RuntimeError(f"Batch cap was not honoured: {capped}")
        final = await sweep_operational_retention(
            queue=queue,
            rate_limits=rate_limits,
            settings=retention_settings(batch_size=1, max_batches=2),
            now=now,
        )
        if final.outbox_events_deleted != 1 or not final.complete:
            raise RuntimeError(f"Remaining backlog was not finished: {final}")
        for event_id in (locked_completed, *extra, *old_completed, MAIL_EVENT):
            if await outbox_status(pool, event_id) is not None:
                raise RuntimeError(f"Expired completed job {event_id} survived.")

        expected_status = {
            "recent completed": "completed",
            "old dead letter": "dead_letter",
            "old pending retry": "pending",
            "old processing": "processing",
            "old completed survey erasure": "completed",
        }
        for name, event_id in kept.items():
            status = await outbox_status(pool, event_id)
            if status != expected_status[name]:
                raise RuntimeError(f"Retention touched the {name} job: {status}")
        async with pool.acquire() as connection:
            detached = await connection.fetchrow(
                "SELECT outbox_event_id, status FROM mail_delivery WHERE id = $1",
                sent_mail_delivery_id,
            )
            remaining_attempts = await connection.fetchval(
                "SELECT count(*) FROM security_rate_attempt WHERE scope = $1",
                RETENTION_SCOPE,
            )
        if (
            detached is None
            or detached["outbox_event_id"] is not None
            or detached["status"] != "sent"
        ):
            raise RuntimeError(
                f"The sent-mail evidence was not kept detached: {detached}"
            )
        if remaining_attempts != 3:
            raise RuntimeError(
                f"Rate-limit retention kept {remaining_attempts} attempts, expected 3."
            )
    finally:
        await pool.close()
    print(
        "poc022: retention deletes only expired completed jobs in bounded, "
        "non-blocking batches and keeps evidence, failures and open work"
    )


async def seed_retention_cli() -> None:
    old = datetime.now(timezone.utc) - timedelta(days=31)
    connection = await asyncpg.connect(database_url())
    try:
        async with connection.transaction():
            for event_id in RETENTION_CLI_EVENTS:
                await insert_retention_event(
                    connection,
                    status="completed",
                    created_at=old,
                    completed_at=old,
                    event_id=event_id,
                )
    finally:
        await connection.close()
    print("poc022: expired completed jobs for the worker CLI seeded")


async def verify_retention_cli() -> None:
    connection = await asyncpg.connect(database_url())
    try:
        remaining = await connection.fetchval(
            "SELECT count(*) FROM outbox_event WHERE id = ANY($1::uuid[])",
            list(RETENTION_CLI_EVENTS),
        )
    finally:
        await connection.close()
    if remaining != 0:
        raise RuntimeError(f"Worker retention CLI left {remaining} expired jobs.")
    print("poc022: worker retention CLI removed the expired completed jobs")


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
    elif arguments.command == "verify-claim-loss":
        await verify_claim_loss()
    elif arguments.command == "verify-retention":
        await verify_retention()
    elif arguments.command == "seed-retention-cli":
        await seed_retention_cli()
    elif arguments.command == "verify-retention-cli":
        await verify_retention_cli()
    else:
        raise RuntimeError(f"Unknown probe command: {arguments.command}")


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
        "verify-claim-loss",
        "verify-retention",
        "seed-retention-cli",
        "verify-retention-cli",
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
