"""Atomic manager completion of delivery and billing details.

Lock order matches order capture and schedule writes: action row first,
delivery configuration second, order row third. Booked windows stay immutable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.retry import (
    SERIALIZABLE_ATTEMPTS,
    serialization_pause,
)
from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import (
    guard_window_booking,
    lock_configuration,
    write_order_delivery,
)
from leonaid.application.delivery_completion import (
    DeliveryCompletionDraft,
    DeliveryCompletionRepository,
    delivery_completion_version,
)
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.commitments import Commitment, CommitmentStatus
from leonaid.domain.errors import DomainInvariantError

COMMAND_TYPE = "complete_delivery_v1"


class AsyncpgDeliveryCompletionRepository(DeliveryCompletionRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def complete_delivery(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        draft: DeliveryCompletionDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Commitment:
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._complete_once(
                            connection,
                            action_id=action_id,
                            commitment_id=commitment_id,
                            actor_user_id=actor_user_id,
                            draft=draft,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except asyncpg.SerializationError:
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise Conflict(
                            "commitment_concurrent_retry",
                            "Die Bestellung wurde gleichzeitig verarbeitet. "
                            "Bitte versuche denselben Vorgang erneut.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Liefervervollständigung wurde nicht ausgeführt.")

    @staticmethod
    async def _complete_once(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        draft: DeliveryCompletionDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Commitment:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            idempotency_key,
        )
        action = await connection.fetchrow(
            """
            SELECT status, EXISTS (
                SELECT 1 FROM charity_action_capability
                WHERE action_id = charity_action.id AND capability = 'ordering'
            ) AS ordering_enabled
            FROM charity_action WHERE id = $1 FOR SHARE
            """,
            action_id,
        )
        if action is None:
            raise ResourceNotFound(
                "commitment_action_not_found",
                "Die Charity-Aktion wurde nicht gefunden.",
            )
        delivery = await lock_configuration(connection, action_id)
        replayed = await AsyncpgCommitmentRepository._existing_command(
            connection,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            command_type=COMMAND_TYPE,
        )
        if replayed is not None:
            if replayed != commitment_id:
                raise Conflict(
                    "idempotency_conflict",
                    "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
                )
            return await AsyncpgCommitmentRepository._get(
                connection, replayed, replayed=True
            )
        if str(action["status"]) == "archived":
            raise Conflict(
                "delivery_action_archived",
                "Bestellungen archivierter Aktionen können nicht ergänzt werden.",
            )
        found = await connection.fetchval(
            """
            SELECT id FROM commitment WHERE id = $1 AND action_id = $2
            FOR UPDATE
            """,
            commitment_id,
            action_id,
        )
        if found is None:
            raise ResourceNotFound(
                "commitment_not_found", "Die Bestellung wurde nicht gefunden."
            )
        order = await AsyncpgCommitmentRepository._get(
            connection, commitment_id, replayed=False
        )
        if order.status not in (CommitmentStatus.DRAFT, CommitmentStatus.REVIEW_READY):
            raise Conflict(
                "delivery_completion_closed",
                "Nur Entwürfe und prüfbereite Bestellungen können ergänzt werden.",
            )
        if await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM invoice WHERE commitment_id = $1)",
            commitment_id,
        ):
            raise Conflict(
                "delivery_completion_invoiced",
                "Eine bereits abgerechnete Bestellung bleibt unverändert.",
            )
        if delivery_completion_version(order) != draft.expected_version:
            raise Conflict(
                "delivery_completion_conflict",
                "Die Bestellung wurde inzwischen geändert. Bitte den aktuellen "
                "Stand laden und die Angaben abgleichen.",
            )
        # Completing a draft confirms it. After the order period closed
        # ("completed") a manager may still do so to record an order that was
        # actually delivered; archived actions were rejected above.
        if order.status is CommitmentStatus.DRAFT and (
            not action["ordering_enabled"]
            or str(action["status"])
            not in {"draft", "scheduled", "active", "completed"}
        ):
            raise Conflict(
                "commitment_action_closed",
                "Für diese Aktion können keine Entwürfe mehr abgeschlossen werden.",
            )
        if order.delivery_window_id is not None:
            # A booked time is part of the customer's order and never moves,
            # even if the window was retired afterwards.
            if draft.delivery_window_id != order.delivery_window_id:
                raise Conflict(
                    "delivery_completion_reschedule_forbidden",
                    "Ein gebuchtes Lieferfenster bleibt unverändert.",
                )
            if draft.delivery_recipient is None:
                raise DomainInvariantError(
                    "delivery_required",
                    "Bitte Lieferadresse und Lieferfenster ergänzen.",
                )
            snapshot = order.delivery_window_snapshot
            historical = False
            full_window_booked = False
        else:
            # Unlike capture, a manager may select a window that has already
            # started to record when the order was actually delivered.
            snapshot, historical = delivery.validate_manager_completion(
                window_id=draft.delivery_window_id,
                has_address=draft.delivery_recipient is not None,
                contact=draft.delivery_contact,
                now=datetime.now(timezone.utc),
            )
            # A historical window records what happened; only a still
            # bookable window is subject to the "ausgebucht" switch.
            full_window_booked = (
                False
                if historical
                else await guard_window_booking(
                    connection,
                    window_id=draft.delivery_window_id,
                    allow_full_window=draft.allow_full_window,
                )
            )
        await connection.execute(
            """
            UPDATE commitment SET status = 'review_ready',
                invoice_recipient_snapshot = $2::jsonb,
                delivery_recipient_snapshot = $3::jsonb,
                updated_at = $4
            WHERE id = $1
            """,
            commitment_id,
            json.dumps(draft.invoice_recipient.payload()),
            json.dumps(draft.delivery_recipient.payload())
            if draft.delivery_recipient
            else None,
            occurred_at,
        )
        await write_order_delivery(
            connection,
            commitment_id=commitment_id,
            window_id=draft.delivery_window_id,
            window_snapshot=snapshot,
            contact=draft.delivery_contact,
        )
        # The audit payload deliberately contains no address or contact data.
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type, entity_id,
                request_id, payload, occurred_at
            ) VALUES ($1,$2,$3,'commitment_delivery_completed','commitment',$4,$5,
                $6::jsonb,$7)
            """,
            uuid4(),
            action_id,
            actor_user_id,
            commitment_id,
            request_id,
            json.dumps(
                {
                    "previousStatus": order.status.value,
                    "status": "review_ready",
                    "historical": historical,
                    **({"fullWindowBooked": True} if full_window_booked else {}),
                }
            ),
            occurred_at,
        )
        await connection.execute(
            """
            UPDATE command_receipt SET result = $2::jsonb, completed_at = $3
            WHERE idempotency_key = $1
            """,
            idempotency_key,
            json.dumps({"commitmentId": str(commitment_id)}),
            occurred_at,
        )
        return await AsyncpgCommitmentRepository._get(
            connection, commitment_id, replayed=False
        )
