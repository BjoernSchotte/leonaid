"""Atomic completion with immutable booked times and optimistic edit protection."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import read_configuration, select_order_window
from leonaid.application.delivery_completion import (
    DeliveryCompletionDraft,
    delivery_completion_version,
)
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.commitments import Commitment, CommitmentStatus
from leonaid.domain.errors import DomainInvariantError

COMMAND = "complete_delivery_v1"


class AsyncpgDeliveryCompletionRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self.pool = pool

    async def complete(
        self,
        *,
        action_id: UUID,
        order_id: UUID,
        actor_id: UUID,
        draft: DeliveryCompletionDraft,
        key: str,
        request_id: str,
        now: datetime,
    ) -> Commitment:
        request_hash = draft.fingerprint(action_id, order_id)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", key
                )
                previous = await connection.fetchrow(
                    "SELECT * FROM command_receipt WHERE idempotency_key = $1", key
                )
                if previous:
                    if (
                        previous["command_type"] != COMMAND
                        or previous["request_hash"] != request_hash
                    ):
                        raise Conflict(
                            "idempotency_conflict",
                            "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
                        )
                    return await AsyncpgCommitmentRepository._get(
                        connection, order_id, replayed=True
                    )
                action_status = await connection.fetchval(
                    "SELECT status FROM charity_action WHERE id = $1 FOR SHARE",
                    action_id,
                )
                if action_status is None:
                    raise ResourceNotFound(
                        "action_not_found", "Diese Aktion wurde nicht gefunden."
                    )
                if action_status == "archived":
                    raise Conflict(
                        "delivery_action_archived",
                        "Archivierte Bestellungen können nicht ergänzt werden.",
                    )
                found = await connection.fetchval(
                    "SELECT id FROM commitment WHERE id = $1 AND action_id = $2 FOR UPDATE",
                    order_id,
                    action_id,
                )
                if found is None:
                    raise ResourceNotFound(
                        "commitment_not_found", "Diese Bestellung wurde nicht gefunden."
                    )
                order = await AsyncpgCommitmentRepository._get(
                    connection, order_id, replayed=False
                )
                if order.status not in (
                    CommitmentStatus.DRAFT,
                    CommitmentStatus.REVIEW_READY,
                ):
                    raise Conflict(
                        "delivery_completion_closed",
                        "Nur Entwürfe und prüfbereite Bestellungen können ergänzt werden.",
                    )
                if await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM invoice WHERE commitment_id = $1)",
                    order_id,
                ):
                    raise Conflict(
                        "delivery_completion_invoiced",
                        "Eine bereits abgerechnete Bestellung bleibt unverändert.",
                    )
                if delivery_completion_version(order) != draft.expected_version:
                    raise Conflict(
                        "delivery_completion_conflict",
                        "Die Bestellung wurde inzwischen geändert. Bitte neu laden und die Angaben abgleichen.",
                    )
                if order.delivery_window_id:
                    if draft.window_id != order.delivery_window_id:
                        raise Conflict(
                            "delivery_completion_reschedule_forbidden",
                            "Ein gebuchtes Lieferfenster bleibt unverändert.",
                        )
                    snapshot = order.delivery_window_snapshot
                    if snapshot is None:
                        raise Conflict(
                            "delivery_completion_snapshot_missing",
                            "Der gespeicherte Liefertermin ist unvollständig und muss geprüft werden.",
                        )
                elif draft.confirm_historical_delivery:
                    if draft.window_id is None:
                        raise DomainInvariantError(
                            "delivery_historical_window_invalid",
                            "Bitte das damalige Lieferfenster auswählen.",
                        )
                    config = await read_configuration(connection, action_id)
                    historical = config.select_historical(draft.window_id, now=now)
                    snapshot = historical.snapshot(config.timezone)
                else:
                    snapshot = await select_order_window(
                        connection,
                        action_id,
                        window_id=draft.window_id,
                        recipient=draft.delivery_recipient,
                        complete=True,
                        now=now,
                    )
                config = await read_configuration(connection, action_id)
                if config.enabled and snapshot is None:
                    raise Conflict(
                        "delivery_details_required", "Bitte ein Lieferfenster ergänzen."
                    )
                await connection.execute(
                    """UPDATE commitment SET delivery_recipient_snapshot = $2::jsonb,
                    invoice_recipient_snapshot = $3::jsonb, delivery_window_id = $4,
                    delivery_window_snapshot = $5::jsonb, status = 'review_ready', updated_at = $6
                    WHERE id = $1""",
                    order_id,
                    json.dumps(draft.delivery_recipient.payload()),
                    json.dumps(draft.invoice_recipient.payload()),
                    draft.window_id,
                    json.dumps(snapshot) if snapshot else None,
                    now,
                )
                await connection.execute(
                    """INSERT INTO audit_event (id, action_id, actor_user_id, event_type,
                    entity_type, entity_id, request_id, payload, occurred_at)
                    VALUES ($1, $2, $3, 'commitment_delivery_completed', 'commitment', $4, $5, $6::jsonb, $7)""",
                    uuid4(),
                    action_id,
                    actor_id,
                    order_id,
                    request_id,
                    json.dumps(
                        {
                            "previousStatus": order.status.value,
                            "status": "review_ready",
                            "historicalDeliveryConfirmed": bool(
                                draft.confirm_historical_delivery
                                and not order.delivery_window_id
                            ),
                        }
                    ),
                    now,
                )
                await connection.execute(
                    """INSERT INTO command_receipt (idempotency_key, command_type, request_hash, result, completed_at)
                    VALUES ($1, $2, $3, $4::jsonb, $5)""",
                    key,
                    COMMAND,
                    request_hash,
                    json.dumps({"commitmentId": str(order_id)}),
                    now,
                )
                return await AsyncpgCommitmentRepository._get(
                    connection, order_id, replayed=False
                )
