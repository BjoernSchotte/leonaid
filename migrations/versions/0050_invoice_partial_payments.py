"""Several payment entries per invoice, optional note and payment reversals.

Revision ID: 0050_invoice_partial_payments
Revises: 0049_window_fully_booked

ADR-0014 replaces the exact full payment of ADR-0009: an invoice may hold
several payment entries of any positive amount, and an entry is reversed by a
separate, reasoned `payment_reversal` row instead of being deleted. Existing
rows need no rewrite: each one already is exactly one payment entry, and the
stored invoice status (`paid` for a full payment) stays correct.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0050_invoice_partial_payments"
down_revision: str | None = "0049_window_fully_booked"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Only the one-payment-per-invoice unique constraint is dropped; no row is "
    "changed or removed. Every existing payment_record row stays as exactly "
    "one payment entry of its invoice, and invoice.status keeps its value. "
    "The downgrade refuses to run while any entry is not one exact full "
    "payment without a note (several entries, a reversal, a note, a partial "
    "or an over payment), so it never discards or misstates a booked payment."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.drop_constraint(
        "uq_payment_record_invoice",
        "payment_record",
        type_="unique",
    )
    op.create_index(
        "ix_payment_record_invoice_received",
        "payment_record",
        ["invoice_id", "received_on", "created_at"],
    )
    op.add_column("payment_record", sa.Column("note", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_payment_note",
        "payment_record",
        "note IS NULL OR length(btrim(note)) BETWEEN 1 AND 500",
    )
    # Target of the composite key below: a reversal names its entry and the
    # entry's own invoice, never another one.
    op.create_unique_constraint(
        "uq_payment_record_id_invoice",
        "payment_record",
        ["id", "invoice_id"],
    )

    op.create_table(
        "payment_reversal",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "payment_id",
            UUID,
            sa.ForeignKey("payment_record.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "invoice_id",
            UUID,
            sa.ForeignKey("invoice.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "reversed_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reversed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "length(btrim(reason_snapshot)) BETWEEN 8 AND 500",
            name="ck_payment_reversal_reason",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id", "invoice_id"],
            ["payment_record.id", "payment_record.invoice_id"],
            name="fk_payment_reversal_payment_invoice",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_payment_reversal_invoice",
        "payment_reversal",
        ["invoice_id"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            -- The previous schema knows only one exact full payment per
            -- invoice and no notes. Anything else would be lost or would
            -- show a partial or over payment as paid.
            IF EXISTS (SELECT 1 FROM payment_reversal)
               OR EXISTS (
                   SELECT 1
                   FROM payment_record
                   GROUP BY invoice_id
                   HAVING count(*) > 1
               )
               OR EXISTS (SELECT 1 FROM payment_record WHERE note IS NOT NULL)
               OR EXISTS (
                   SELECT 1
                   FROM payment_record AS payment
                   JOIN invoice ON invoice.id = payment.invoice_id
                   WHERE payment.amount_minor <> invoice.gross_minor
                      OR payment.currency <> invoice.currency
               )
            THEN
                RAISE EXCEPTION 'downgrade refused: payment entries beyond one exact full payment without note exist';
            END IF;
        END;
        $$;
        """
    )
    op.drop_index("ix_payment_reversal_invoice", table_name="payment_reversal")
    op.drop_table("payment_reversal")
    op.drop_constraint(
        "uq_payment_record_id_invoice",
        "payment_record",
        type_="unique",
    )
    op.drop_constraint("ck_payment_note", "payment_record", type_="check")
    op.drop_column("payment_record", "note")
    op.drop_index(
        "ix_payment_record_invoice_received",
        table_name="payment_record",
    )
    op.create_unique_constraint(
        "uq_payment_record_invoice",
        "payment_record",
        ["invoice_id"],
    )
