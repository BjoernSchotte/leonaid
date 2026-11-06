"""Atomic order cancellation in PostgreSQL.

Lock order: idempotency key, action row (shared), the order's delivery window
(like every delivery board command), the order row, its delivery row and its
invoice. A mark-delivered on the board and this command therefore serialize
on the window: the board then sees the cancelled status, or the cancellation
sees the delivery. Commands that lock the order before its window (draft and
delivery completion) can deadlock with this one; PostgreSQL aborts one side
and the command retries like a serialization failure.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery_board import order_link, order_reference
from leonaid.adapters.postgres.invoice_settlements import (
    AsyncpgInvoiceSettlementRepository,
)
from leonaid.adapters.postgres.retry import (
    SERIALIZABLE_ATTEMPTS,
    serialization_pause,
)
from leonaid.application.delivery_board import DeliveryFollowUp
from leonaid.application.delivery_completion import delivery_completion_version
from leonaid.application.errors import (
    AuthenticationRequired,
    Conflict,
    ResourceNotFound,
)
from leonaid.application.order_cancellation import (
    OrderCancellationRepository,
    OrderCancellationRequest,
    OrderCancellationResult,
)
from leonaid.domain.calendar import INSTALLATION_TIME_ZONE
from leonaid.domain.commitments import CommitmentStatus
from leonaid.domain.invoices import InvoiceStatus
from leonaid.domain.order_cancellation import (
    OrderCancellation,
    OrderInvoiceState,
    cancellation_block,
)

COMMAND_TYPE = "cancel_commitment_v1"


def follow_up_closing_note(requested_at: datetime) -> str:
    """No personal data and no free text: the task outlives the order."""

    day = requested_at.astimezone(INSTALLATION_TIME_ZONE)
    return (
        f"Erledigt: Die Bestellung wurde am {day:%d.%m.%Y} storniert. "
        "Kein Nachliefern nötig; den Grund zeigt die Bestellung."
    )


async def invoice_payment_recorded(
    connection: asyncpg.Connection[Any], invoice_id: UUID
) -> bool:
    """Whether any payment is booked on the invoice.

    The one place the cancellation reads payments; payment recording itself
    stays in the invoice settlement adapter.
    """

    return bool(
        await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM payment_record WHERE invoice_id = $1)",
            invoice_id,
        )
    )


class AsyncpgOrderCancellationRepository(OrderCancellationRepository):
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        follow_up: Callable[[asyncpg.Connection[Any]], DeliveryFollowUp] | None = None,
    ) -> None:
        self._pool = pool
        self._follow_up = follow_up
        self._invoices = AsyncpgInvoiceSettlementRepository(pool)

    async def cancel(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        request: OrderCancellationRequest,
        fresh_login: bool,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> OrderCancellationResult:
        async with self._pool.acquire() as connection:
            for attempt in range(SERIALIZABLE_ATTEMPTS):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._cancel_once(
                            connection,
                            action_id=action_id,
                            commitment_id=commitment_id,
                            actor_user_id=actor_user_id,
                            request=request,
                            fresh_login=fresh_login,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except (
                    asyncpg.SerializationError,
                    asyncpg.DeadlockDetectedError,
                ):
                    if attempt == SERIALIZABLE_ATTEMPTS - 1:
                        raise Conflict(
                            "commitment_concurrent_retry",
                            "Die Bestellung wurde gleichzeitig verarbeitet. "
                            "Bitte denselben Vorgang erneut ausführen.",
                        ) from None
                    await serialization_pause(attempt)
        raise RuntimeError("Die Stornierung wurde nicht ausgeführt.")

    async def _cancel_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        commitment_id: UUID,
        actor_user_id: UUID,
        request: OrderCancellationRequest,
        fresh_login: bool,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> OrderCancellationResult:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            idempotency_key,
        )
        action_status = await connection.fetchval(
            "SELECT status FROM charity_action WHERE id = $1 FOR SHARE",
            action_id,
        )
        if action_status is None:
            raise ResourceNotFound(
                "commitment_action_not_found",
                "Die Charity-Aktion wurde nicht gefunden.",
            )
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
            return OrderCancellationResult(
                commitment=await AsyncpgCommitmentRepository._get(
                    connection, commitment_id, replayed=True
                ),
                cancellation=await self._get_cancellation(connection, commitment_id),
                replayed=True,
            )
        if str(action_status) == "archived":
            raise Conflict(
                "commitment_cancellation_action_archived",
                "Bestellungen archivierter Aktionen können nicht storniert werden.",
            )
        window_id = await self._window_of(connection, action_id, commitment_id)
        if window_id is not None:
            await connection.execute(
                "SELECT id FROM action_delivery_window WHERE id = $1 FOR UPDATE",
                window_id,
            )
        locked_window = await connection.fetchrow(
            """
            SELECT delivery_window_id FROM commitment
            WHERE id = $1 AND action_id = $2
            FOR UPDATE
            """,
            commitment_id,
            action_id,
        )
        if locked_window is None:
            raise ResourceNotFound(
                "commitment_not_found", "Die Bestellung wurde nicht gefunden."
            )
        if locked_window["delivery_window_id"] != window_id:
            # A completion booked a window in between: the view is stale.
            raise Conflict(
                "commitment_cancellation_conflict",
                "Die Bestellung wurde inzwischen geändert. Bitte den aktuellen "
                "Stand laden.",
            )
        order = await AsyncpgCommitmentRepository._get(
            connection, commitment_id, replayed=False
        )
        delivery_state = await connection.fetchval(
            "SELECT state FROM commitment_delivery WHERE commitment_id = $1 FOR UPDATE",
            commitment_id,
        )
        invoice = await self._invoice_of(connection, commitment_id)
        block = cancellation_block(
            status=order.status,
            delivered=delivery_state == "delivered",
            invoice=invoice,
        )
        if block is not None:
            raise Conflict(block.code, block.message)
        if delivery_completion_version(order) != request.expected_version:
            raise Conflict(
                "commitment_cancellation_conflict",
                "Die Bestellung wurde inzwischen geändert. Bitte den aktuellen "
                "Stand laden.",
            )
        cancellation_id = uuid4()
        invoice_cancellation_id: UUID | None = None
        if invoice is not None and invoice.needs_cancellation:
            if not fresh_login:
                raise AuthenticationRequired(
                    "fresh_login_required",
                    "Für diese Änderung muss die Anmeldung erneut bestätigt werden.",
                )
            inner_key = f"order-cancellation:{cancellation_id}"
            invoice_cancellation = await self._invoices._cancel_once(
                connection,
                action_id=action_id,
                invoice_id=invoice.id,
                reason=request.reason,
                actor_user_id=actor_user_id,
                idempotency_key=inner_key,
                request_hash=hashlib.sha256(inner_key.encode("utf-8")).hexdigest(),
                request_id=request_id,
                occurred_at=occurred_at,
            )
            invoice_cancellation_id = invoice_cancellation.id

        cancellation = OrderCancellation(
            id=cancellation_id,
            action_id=action_id,
            commitment_id=commitment_id,
            previous_status=order.status,
            reason=request.reason,
            note=request.note,
            requested_by_user_id=actor_user_id,
            requested_at=occurred_at,
            invoice_cancellation_id=invoice_cancellation_id,
        )
        updated = await connection.execute(
            """
            UPDATE commitment SET status = 'cancelled', updated_at = $2
            WHERE id = $1 AND status <> 'cancelled'
            """,
            commitment_id,
            occurred_at,
        )
        if updated != "UPDATE 1":
            raise RuntimeError("Die gesperrte Bestellung hat sich verändert.")
        await connection.execute(
            """
            INSERT INTO commitment_cancellation (
                id, action_id, commitment_id, previous_status, reason_snapshot,
                note_snapshot, requested_by_user_id, invoice_cancellation_id,
                requested_at, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
            """,
            cancellation.id,
            action_id,
            commitment_id,
            cancellation.previous_status.value,
            cancellation.reason,
            cancellation.note,
            actor_user_id,
            invoice_cancellation_id,
            occurred_at,
        )
        # The note stays out of audit and activity: it may hold personal
        # data that the privacy erasure clears on the cancellation record.
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type, entity_id,
                request_id, payload, occurred_at
            ) VALUES ($1, $2, $3, 'commitment_cancelled', 'commitment', $4, $5,
                $6::jsonb, $7)
            """,
            uuid4(),
            action_id,
            actor_user_id,
            commitment_id,
            request_id,
            json.dumps(
                {
                    "cancellationId": str(cancellation.id),
                    "previousStatus": order.status.value,
                    "status": CommitmentStatus.CANCELLED.value,
                    "reason": cancellation.reason,
                    "invoiceId": str(invoice.id) if invoice else None,
                    "invoiceNumber": invoice.number if invoice else None,
                    "invoiceCancellationId": (
                        str(invoice_cancellation_id)
                        if invoice_cancellation_id
                        else None
                    ),
                    "deliveryState": delivery_state,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            occurred_at,
        )
        # The order's entry on the buyer's CRM timeline, next to its
        # public_order_received event; no feed recipients.
        await connection.execute(
            """
            INSERT INTO activity_event (
                id, action_id, event_type, twenty_company_id, twenty_person_id,
                payload, occurred_at
            ) VALUES ($1, $2, 'commitment_cancelled', $3, $4, $5::jsonb, $6)
            """,
            uuid4(),
            action_id,
            order.buyer.company_id,
            order.buyer.person_id,
            json.dumps(
                {
                    "commitmentId": str(commitment_id),
                    "publicReference": order.public_reference,
                    "previousStatus": order.status.value,
                    "totalMinor": order.total.amount_minor,
                    "currency": order.total.currency,
                    "quantities": [item.payload() for item in order.quantities],
                    "invoiceNumber": (
                        invoice.number
                        if invoice is not None and invoice_cancellation_id
                        else None
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            occurred_at,
        )
        if self._follow_up is not None and window_id is not None:
            # Closes an open "Nachliefern" task; does nothing without one.
            await self._follow_up(connection).sync(
                connection,
                action_id=action_id,
                commitment_id=commitment_id,
                title=(
                    "Nachliefern: Bestellung "
                    f"{order_reference(commitment_id, order.public_reference)}"
                ),
                description=(
                    f"Bestellung öffnen: {order_link(action_id, commitment_id)}"
                ),
                needed=False,
                assignee_user_id=actor_user_id,
                actor_user_id=actor_user_id,
                request_id=request_id,
                occurred_at=occurred_at,
                closing_note=follow_up_closing_note(occurred_at),
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
                    "cancellationId": str(cancellation.id),
                }
            ),
            occurred_at,
        )
        return OrderCancellationResult(
            commitment=await AsyncpgCommitmentRepository._get(
                connection, commitment_id, replayed=False
            ),
            cancellation=await self._get_cancellation(connection, commitment_id),
        )

    @staticmethod
    async def _window_of(
        connection: asyncpg.Connection[Any], action_id: UUID, commitment_id: UUID
    ) -> UUID | None:
        row = await connection.fetchrow(
            "SELECT delivery_window_id FROM commitment WHERE id = $1 AND action_id = $2",
            commitment_id,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "commitment_not_found", "Die Bestellung wurde nicht gefunden."
            )
        value = row["delivery_window_id"]
        return value if isinstance(value, UUID) or value is None else UUID(str(value))

    @staticmethod
    async def _invoice_of(
        connection: asyncpg.Connection[Any], commitment_id: UUID
    ) -> OrderInvoiceState | None:
        row = await connection.fetchrow(
            "SELECT id, number, status FROM invoice WHERE commitment_id = $1"
            " FOR UPDATE",
            commitment_id,
        )
        if row is None:
            return None
        return OrderInvoiceState(
            id=row["id"],
            number=str(row["number"]),
            status=InvoiceStatus(str(row["status"])),
            payment_recorded=await invoice_payment_recorded(connection, row["id"]),
        )

    @staticmethod
    async def _get_cancellation(
        connection: asyncpg.Connection[Any], commitment_id: UUID
    ) -> OrderCancellation:
        row = await connection.fetchrow(
            """
            SELECT cancellation.*, account.display_name AS requested_by_name,
                invoice.number AS invoice_number
            FROM commitment_cancellation AS cancellation
            JOIN user_account AS account
              ON account.id = cancellation.requested_by_user_id
            LEFT JOIN invoice_cancellation
              ON invoice_cancellation.id = cancellation.invoice_cancellation_id
            LEFT JOIN invoice ON invoice.id = invoice_cancellation.invoice_id
            WHERE cancellation.commitment_id = $1
            """,
            commitment_id,
        )
        if row is None:
            raise RuntimeError("Die bestätigte Stornierung fehlt.")
        return OrderCancellation(
            id=row["id"],
            action_id=row["action_id"],
            commitment_id=row["commitment_id"],
            previous_status=CommitmentStatus(str(row["previous_status"])),
            reason=str(row["reason_snapshot"]),
            note=(
                str(row["note_snapshot"]) if row["note_snapshot"] is not None else None
            ),
            requested_by_user_id=row["requested_by_user_id"],
            requested_at=row["requested_at"],
            invoice_cancellation_id=row["invoice_cancellation_id"],
            invoice_number=(
                str(row["invoice_number"])
                if row["invoice_number"] is not None
                else None
            ),
            requested_by_display_name=str(row["requested_by_name"]),
        )
