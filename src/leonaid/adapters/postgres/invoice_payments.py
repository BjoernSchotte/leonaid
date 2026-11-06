"""Reads the payment entries of invoices, each with its reversal."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from leonaid.domain.commitments import Money
from leonaid.domain.invoice_settlements import PaymentRecord, PaymentReversal

_PAYMENT_ROWS = """
    SELECT
        payment.id,
        payment.invoice_id,
        invoice.action_id,
        payment.amount_minor,
        payment.currency,
        payment.received_on,
        payment.reference,
        payment.note,
        payment.recorded_by_user_id,
        payment.created_at,
        recorder.display_name AS recorded_by_display_name,
        reversal.id AS reversal_id,
        reversal.reason_snapshot AS reversal_reason,
        reversal.reversed_by_user_id,
        reversal.reversed_at,
        reverser.display_name AS reversed_by_display_name
    FROM payment_record AS payment
    JOIN invoice ON invoice.id = payment.invoice_id
    JOIN user_account AS recorder
      ON recorder.id = payment.recorded_by_user_id
    LEFT JOIN payment_reversal AS reversal
      ON reversal.payment_id = payment.id
    LEFT JOIN user_account AS reverser
      ON reverser.id = reversal.reversed_by_user_id
    WHERE {condition}
    ORDER BY payment.invoice_id, payment.received_on, payment.created_at, payment.id
"""


def payment_from_row(row: asyncpg.Record, *, replayed: bool = False) -> PaymentRecord:
    reversal = (
        PaymentReversal(
            id=row["reversal_id"],
            action_id=row["action_id"],
            invoice_id=row["invoice_id"],
            payment_id=row["id"],
            reason=str(row["reversal_reason"]),
            reversed_by_user_id=row["reversed_by_user_id"],
            reversed_at=row["reversed_at"],
            reversed_by_display_name=str(row["reversed_by_display_name"]),
        )
        if row["reversal_id"] is not None
        else None
    )
    return PaymentRecord(
        id=row["id"],
        action_id=row["action_id"],
        invoice_id=row["invoice_id"],
        amount=Money(int(row["amount_minor"]), str(row["currency"])),
        received_on=row["received_on"],
        reference=str(row["reference"]),
        recorded_by_user_id=row["recorded_by_user_id"],
        recorded_at=row["created_at"],
        recorded_by_display_name=str(row["recorded_by_display_name"]),
        replayed=replayed,
        note=str(row["note"]) if row["note"] is not None else None,
        reversal=reversal,
    )


async def payments_for_action(
    connection: asyncpg.Connection[Any],
    action_id: UUID,
) -> dict[UUID, tuple[PaymentRecord, ...]]:
    """Every payment entry of the action's invoices, oldest first per invoice."""

    rows = await connection.fetch(
        _PAYMENT_ROWS.format(condition="invoice.action_id = $1"),
        action_id,
    )
    grouped: dict[UUID, list[PaymentRecord]] = {}
    for row in rows:
        grouped.setdefault(row["invoice_id"], []).append(payment_from_row(row))
    return {invoice_id: tuple(items) for invoice_id, items in grouped.items()}


async def payments_for_invoice(
    connection: asyncpg.Connection[Any],
    invoice_id: UUID,
) -> tuple[PaymentRecord, ...]:
    rows = await connection.fetch(
        _PAYMENT_ROWS.format(condition="payment.invoice_id = $1"),
        invoice_id,
    )
    return tuple(payment_from_row(row) for row in rows)


async def payment_by_id(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    payment_id: UUID,
    replayed: bool = False,
) -> PaymentRecord | None:
    row = await connection.fetchrow(
        _PAYMENT_ROWS.format(condition="payment.id = $1 AND invoice.action_id = $2"),
        payment_id,
        action_id,
    )
    return payment_from_row(row, replayed=replayed) if row is not None else None


async def payment_by_reversal_id(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    reversal_id: UUID,
) -> PaymentRecord | None:
    row = await connection.fetchrow(
        _PAYMENT_ROWS.format(condition="reversal.id = $1 AND invoice.action_id = $2"),
        reversal_id,
        action_id,
    )
    return payment_from_row(row) if row is not None else None
