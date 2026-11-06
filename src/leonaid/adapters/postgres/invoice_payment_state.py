"""Whether money is booked on an invoice, as one SQL predicate.

The order list and the order cancellation read it; payment recording itself
stays in the invoice settlement adapter. A change to how payments are stored
(partial payments, reversals) adjusts this predicate only.
"""

from __future__ import annotations

# Use where the invoice row is in scope as ``invoice``.
PAYMENT_RECORDED_SQL = """EXISTS (
    SELECT 1 FROM payment_record WHERE payment_record.invoice_id = invoice.id
)"""
