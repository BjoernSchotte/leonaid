"""Money booked on an invoice, as SQL expressions.

The order list and the order cancellation read them; payment recording itself
stays in the invoice settlement adapter. An entry counts while it is active:
a reversed entry (``payment_reversal``, ADR-0014) is money taken back.
"""

from __future__ import annotations

# Use where the invoice row is in scope as ``invoice``.
ACTIVE_PAID_MINOR_SQL = """(
    SELECT coalesce(sum(payment_record.amount_minor), 0)::bigint
    FROM payment_record
    WHERE payment_record.invoice_id = invoice.id
      AND NOT EXISTS (
          SELECT 1 FROM payment_reversal
          WHERE payment_reversal.payment_id = payment_record.id
      )
)"""
# Entries are positive, so any active entry means a positive sum.
PAYMENT_RECORDED_SQL = f"({ACTIVE_PAID_MINOR_SQL} > 0)"
