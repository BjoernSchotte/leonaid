"""PostgreSQL side of the buyer mail settings, mail status and resend."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import has_delivery_capability
from leonaid.adapters.postgres.order_mail_jobs import insert_order_mail_event
from leonaid.application.buyer_mails import (
    BuyerMailJob,
    BuyerMailLedger,
    BuyerMailRepository,
    next_sequence,
    resend_refusal,
)
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.order_mails import (
    EVENT_TYPES,
    KEY_PREFIXES,
    OrderMailKind,
    OrderMailLinks,
    order_mail_event,
)
from leonaid.domain.buyer_mails import (
    DEFAULT_DELIVERY_DAY_SEND_TIME,
    BuyerMailConfiguration,
)
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.commitments import CommitmentStatus

RESEND_COMMAND_TYPE = "resend_buyer_mail_v1"


# Ledger rows of one order and kind: the first key and its ``:resend:{n}``
# keys lie between the first key and the same text followed by ";" (the
# character after ":") in byte order. ``ix_mail_delivery_key_c`` serves it.
SENT_SQL = " OR ".join(
    f"""(idempotency_key COLLATE "C" >= ${index}
        AND idempotency_key COLLATE "C" < ${index} || ';')"""
    for index in range(1, len(KEY_PREFIXES) + 1)
)


class AsyncpgBuyerMailRepository(BuyerMailRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def configuration(self, action_id: UUID) -> BuyerMailConfiguration:
        async with self._pool.acquire() as connection:
            return await self._configuration(connection, action_id)

    @staticmethod
    async def _configuration(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
        *,
        for_update: bool = False,
    ) -> BuyerMailConfiguration:
        # The action row is the lock: a settings row may be missing for an
        # action that was not created through the application.
        if not await connection.fetchval(
            "SELECT true FROM charity_action WHERE id = $1"
            + (" FOR UPDATE" if for_update else ""),
            action_id,
        ):
            raise ResourceNotFound(
                "action_not_found", "Die Charity-Aktion wurde nicht gefunden."
            )
        row = await connection.fetchrow(
            """
            SELECT internal_order_mails, delivery_day_mail,
                delivery_day_send_time, revision
            FROM action_buyer_mail_configuration
            WHERE action_id = $1
            """,
            action_id,
        )
        if row is None:
            return BuyerMailConfiguration(action_id=action_id)
        return BuyerMailConfiguration(
            action_id=action_id,
            internal_order_mails=bool(row["internal_order_mails"]),
            delivery_day_mail=bool(row["delivery_day_mail"]),
            delivery_day_send_time=row["delivery_day_send_time"],
            revision=int(row["revision"]),
        )

    async def save_configuration(
        self,
        configuration: BuyerMailConfiguration,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> BuyerMailConfiguration:
        action_id = configuration.action_id
        async with self._pool.acquire() as connection, connection.transaction():
            current = await self._configuration(connection, action_id, for_update=True)
            if current.revision != configuration.revision:
                raise Conflict(
                    "buyer_mail_configuration_conflict",
                    "Die Einstellungen wurden inzwischen geändert. Bitte den "
                    "aktuellen Stand laden.",
                )
            if configuration.delivery_day_mail and not await has_delivery_capability(
                connection, action_id
            ):
                raise Conflict(
                    "buyer_mail_delivery_required",
                    "Die Liefertags-E-Mail setzt die Funktion „Lieferung“ der "
                    "Aktion voraus.",
                )
            await connection.execute(
                """
                INSERT INTO action_buyer_mail_configuration (
                    action_id, internal_order_mails, delivery_day_mail,
                    delivery_day_send_time, revision
                )
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (action_id) DO UPDATE SET
                    internal_order_mails = EXCLUDED.internal_order_mails,
                    delivery_day_mail = EXCLUDED.delivery_day_mail,
                    delivery_day_send_time = EXCLUDED.delivery_day_send_time,
                    revision = EXCLUDED.revision
                """,
                action_id,
                configuration.internal_order_mails,
                configuration.delivery_day_mail,
                configuration.delivery_day_send_time,
                current.revision + 1,
            )

            def values(value: BuyerMailConfiguration) -> dict[str, object]:
                return {
                    "internalOrderMails": value.internal_order_mails,
                    "deliveryDayMail": value.delivery_day_mail,
                    "deliveryDaySendTime": f"{value.delivery_day_send_time:%H:%M}",
                }

            await connection.execute(
                """
                INSERT INTO audit_event (
                    id, action_id, actor_user_id, event_type, entity_type,
                    entity_id, request_id, payload, occurred_at
                ) VALUES ($1, $2, $3, 'buyer_mail_configuration_changed',
                    'charity_action', $2, $4, $5::jsonb, $6)
                """,
                uuid4(),
                action_id,
                actor_user_id,
                request_id,
                json.dumps(
                    {"previous": values(current), "current": values(configuration)},
                    separators=(",", ":"),
                ),
                occurred_at,
            )
            return await self._configuration(connection, action_id)

    async def ledger(self, *, action_id: UUID, commitment_id: UUID) -> BuyerMailLedger:
        async with self._pool.acquire() as connection:
            # One snapshot for the order, its jobs and the ledger rows.
            async with connection.transaction(
                isolation="repeatable_read", readonly=True
            ):
                return await self._ledger(connection, action_id, commitment_id)

    @staticmethod
    async def _ledger(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
        commitment_id: UUID,
        *,
        for_update: bool = False,
    ) -> BuyerMailLedger:
        row = await connection.fetchrow(
            """
            SELECT COALESCE(mails.internal_order_mails, false)
                    AS internal_order_mails,
                COALESCE(mails.delivery_day_mail, false) AND EXISTS (
                    SELECT 1 FROM charity_action_capability AS capability
                    WHERE capability.action_id = commitment.action_id
                      AND capability.capability = 'delivery'
                ) AS delivery_day_mail,
                mails.delivery_day_send_time,
                delivery_settings.timezone AS delivery_zone,
                action.status AS action_status,
                delivery.state AS drop_state,
                cancellation.previous_status
            FROM commitment
            JOIN charity_action AS action ON action.id = commitment.action_id
            LEFT JOIN action_buyer_mail_configuration AS mails
              ON mails.action_id = commitment.action_id
            LEFT JOIN action_delivery_configuration AS delivery_settings
              ON delivery_settings.action_id = commitment.action_id
            LEFT JOIN commitment_delivery AS delivery
              ON delivery.commitment_id = commitment.id
            LEFT JOIN commitment_cancellation AS cancellation
              ON cancellation.commitment_id = commitment.id
            WHERE commitment.id = $1 AND commitment.action_id = $2
            """
            + (" FOR UPDATE OF commitment" if for_update else ""),
            commitment_id,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "commitment_not_found", "Die Bestellung wurde nicht gefunden."
            )
        jobs = await connection.fetch(
            """
            SELECT idempotency_key, status, last_error_code
            FROM outbox_event
            WHERE aggregate_type = 'commitment'
              AND aggregate_id = $1
              AND event_type = ANY($2::text[])
            """,
            commitment_id,
            list(EVENT_TYPES.values()),
        )
        sent = await connection.fetch(
            """
            SELECT idempotency_key, sent_at
            FROM mail_delivery
            WHERE status = 'sent' AND ("""
            + SENT_SQL
            + ")",
            *(f"{prefix}{commitment_id}" for prefix in KEY_PREFIXES.values()),
        )
        return BuyerMailLedger(
            commitment=await AsyncpgCommitmentRepository._get(
                connection, commitment_id, replayed=False
            ),
            internal_order_mails=bool(row["internal_order_mails"]),
            previous_status=(
                CommitmentStatus(str(row["previous_status"]))
                if row["previous_status"] is not None
                else None
            ),
            jobs=tuple(
                BuyerMailJob(
                    key=str(job["idempotency_key"]),
                    status=str(job["status"]),
                    error_code=(
                        str(job["last_error_code"])
                        if job["last_error_code"] is not None
                        else None
                    ),
                )
                for job in jobs
            ),
            sent=tuple(
                (str(item["idempotency_key"]), item["sent_at"]) for item in sent
            ),
            action_status=str(row["action_status"]),
            drop_state=(
                str(row["drop_state"]) if row["drop_state"] is not None else None
            ),
            delivery_day_mail=bool(row["delivery_day_mail"]),
            delivery_day_send_time=(
                row["delivery_day_send_time"] or DEFAULT_DELIVERY_DAY_SEND_TIME
            ),
            delivery_zone=(
                ZoneInfo(str(row["delivery_zone"]))
                if row["delivery_zone"] is not None
                else INSTALLATION_TIME_ZONE
            ),
        )

    async def resend(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        kind: OrderMailKind,
        actor_user_id: UUID,
        links: OrderMailLinks,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> tuple[BuyerMailLedger, bool]:
        async with self._pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                idempotency_key,
            )
            # The order row serializes resends of one order, so two of them
            # never take the same number.
            ledger = await self._ledger(
                connection, action_id, commitment_id, for_update=True
            )
            replayed = await AsyncpgCommitmentRepository._existing_command(
                connection,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                command_type=RESEND_COMMAND_TYPE,
            )
            if replayed is not None:
                if replayed != commitment_id:
                    raise Conflict(
                        "idempotency_conflict",
                        "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
                    )
                return ledger, True
            refusal = resend_refusal(kind, ledger, now=occurred_at)
            if refusal is not None:
                # Rolls the command receipt back: the key stays free.
                raise refusal
            # 0: the mail was never queued, this writes its first job.
            number = next_sequence(kind, ledger)
            event = order_mail_event(
                kind,
                action_id=action_id,
                commitment_id=commitment_id,
                links=links,
                resend=number or None,
                # The delivery-day mail is keyed by the order's window now.
                window_id=(
                    ledger.commitment.delivery_window_id
                    if kind is OrderMailKind.DELIVERY_DAY
                    else None
                ),
            )
            await insert_order_mail_event(connection, event, occurred_at)
            # Older failed jobs of this mail are settled by this send: an
            # operator who retried one later would mail the buyer twice. (The
            # worker also skips a job that a newer sent one superseded.)
            await connection.execute(
                """
                UPDATE outbox_event
                SET status = 'completed', completed_at = $3,
                    dead_lettered_at = NULL, claim_token = NULL, claimed_by = NULL
                WHERE aggregate_type = 'commitment' AND aggregate_id = $1
                  AND event_type = $2 AND status = 'dead_letter'
                """,
                commitment_id,
                EVENT_TYPES[kind],
                occurred_at,
            )
            # No address in the audit event: the order may be erased later.
            await connection.execute(
                """
                INSERT INTO audit_event (
                    id, action_id, actor_user_id, event_type, entity_type,
                    entity_id, request_id, payload, occurred_at
                ) VALUES ($1, $2, $3, 'order_mail_resent', 'commitment', $4, $5,
                    $6::jsonb, $7)
                """,
                uuid4(),
                action_id,
                actor_user_id,
                commitment_id,
                request_id,
                json.dumps(
                    {"kind": kind.value, "resend": number}, separators=(",", ":")
                ),
                occurred_at,
            )
            await connection.execute(
                """
                UPDATE command_receipt SET result = $2::jsonb, completed_at = $3
                WHERE idempotency_key = $1
                """,
                idempotency_key,
                json.dumps(
                    {
                        "commitmentId": str(commitment_id),
                        "kind": kind.value,
                        "resend": number,
                    },
                    separators=(",", ":"),
                ),
                occurred_at,
            )
            return await self._ledger(connection, action_id, commitment_id), False
