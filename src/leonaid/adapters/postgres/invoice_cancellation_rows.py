"""Row mapping of invoice cancellations, shared by list and command reads."""

from __future__ import annotations

from typing import Any

import asyncpg

from leonaid.domain.commitments import Money
from leonaid.domain.invoice_settlements import (
    InvoiceCancellation,
    InvoiceRefundSettlement,
)
from leonaid.domain.invoices import InvoiceStatus

# The columns a list query selects next to its own, aliased ``cancellation_*``.
CANCELLATION_LIST_COLUMNS = """
    cancellation.id AS cancellation_id,
    cancellation.action_id AS cancellation_action_id,
    cancellation.invoice_id AS cancellation_invoice_id,
    cancellation.original_status AS cancellation_original_status,
    cancellation.reason_snapshot AS cancellation_reason_snapshot,
    cancellation.requested_by_user_id AS cancellation_requested_by_user_id,
    cancellation.requested_at AS cancellation_requested_at,
    cancellation.number AS cancellation_number,
    cancellation.issued_on AS cancellation_issued_on,
    cancellation.refund_settled_on AS cancellation_refund_settled_on,
    cancellation.refund_note AS cancellation_refund_note,
    cancellation.refund_settled_by_user_id
      AS cancellation_refund_settled_by_user_id,
    cancellation.refund_settled_at AS cancellation_refund_settled_at
"""


def cancellation_from_row(
    row: asyncpg.Record,
    *,
    requested_by_display_name: str | None,
    received: Money,
    replayed: bool = False,
    prefix: str = "",
) -> InvoiceCancellation:
    """A cancellation from its columns; ``prefix`` names aliased columns.

    Needs ``refund_settled_by_display_name`` next to the table's columns.
    """

    def column(name: str) -> Any:
        return row[f"{prefix}{name}"]

    refund = (
        InvoiceRefundSettlement(
            settled_on=column("refund_settled_on"),
            note=(
                str(column("refund_note"))
                if column("refund_note") is not None
                else None
            ),
            settled_by_user_id=column("refund_settled_by_user_id"),
            settled_at=column("refund_settled_at"),
            settled_by_display_name=(
                str(column("refund_settled_by_display_name"))
                if column("refund_settled_by_display_name") is not None
                else None
            ),
        )
        if column("refund_settled_on") is not None
        else None
    )
    return InvoiceCancellation(
        id=column("id"),
        action_id=column("action_id"),
        invoice_id=column("invoice_id"),
        original_status=InvoiceStatus(str(column("original_status"))),
        reason=str(column("reason_snapshot")),
        requested_by_user_id=column("requested_by_user_id"),
        requested_at=column("requested_at"),
        requested_by_display_name=requested_by_display_name,
        replayed=replayed,
        number=str(column("number")) if column("number") is not None else None,
        issued_on=column("issued_on"),
        received=received,
        refund=refund,
    )
