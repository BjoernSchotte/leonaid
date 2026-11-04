"""Store the invoice date with the issued invoice.

Revision ID: 0045_invoice_issued_on
Revises: 0044_inbox

The invoice date was derived from ``issued_at`` whenever a document was
rendered. It is part of the issued invoice and must not change with later
code (the switch from the UTC day to the club's Berlin day would have moved
the printed date of night-hour invoices whose PDF was not rendered yet).
Existing invoices keep the day the old code used for their PDF and due
date: the UTC day of ``issued_at``. The column joins the immutable snapshot.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_invoice_issued_on"
down_revision: str | None = "0044_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Immutable snapshot fields as of 0026_invoice_payment_snapshot.
_SNAPSHOT_FIELDS = (
    "action_id",
    "commitment_id",
    "number",
    "idempotency_key",
    "issued_at",
    "service_on",
    "due_on",
    "currency",
    "net_minor",
    "tax_minor",
    "gross_minor",
    "issuer_snapshot",
    "payment_details_snapshot",
    "recipient_snapshot",
    "line_snapshot",
    "tax_treatment",
    "tax_rate_basis_points",
    "tax_note",
    "payment_reference",
    "approved_by_user_id",
)


def _protection(fields: Sequence[str]) -> str:
    comparisons = "\n       OR ".join(
        f"NEW.{field} IS DISTINCT FROM OLD.{field}" for field in fields
    )
    return f"""
CREATE OR REPLACE FUNCTION protect_invoice_issue_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF {comparisons}
    THEN
        RAISE EXCEPTION
            'issued invoice snapshots are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column("invoice", sa.Column("issued_on", sa.Date()))
    op.execute("UPDATE invoice SET issued_on = (issued_at AT TIME ZONE 'UTC')::date")
    op.alter_column("invoice", "issued_on", nullable=False)
    op.create_check_constraint(
        "ck_invoice_due_on_after_issued_on",
        "invoice",
        "due_on >= issued_on",
    )
    op.execute(_protection((*_SNAPSHOT_FIELDS, "issued_on")))


def downgrade() -> None:
    op.execute(_protection(_SNAPSHOT_FIELDS))
    op.drop_constraint("ck_invoice_due_on_after_issued_on", "invoice", type_="check")
    op.drop_column("invoice", "issued_on")
