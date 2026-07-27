"""Add exact payment and durable invoice cancellation records.

Revision ID: 0016_invoice_settlements
Revises: 0015_invoice_delivery
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0016_invoice_settlements"
down_revision: str | None = "0015_invoice_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.execute(
        """
        UPDATE payment_record AS payment
        SET reference = invoice.payment_reference
        FROM invoice
        WHERE invoice.id = payment.invoice_id
          AND (
            payment.reference IS NULL
            OR length(btrim(payment.reference)) = 0
          )
        """
    )
    op.alter_column("payment_record", "reference", nullable=False)
    op.create_unique_constraint(
        "uq_payment_record_invoice",
        "payment_record",
        ["invoice_id"],
    )
    op.create_check_constraint(
        "ck_payment_currency",
        "payment_record",
        "currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        "ck_payment_reference",
        "payment_record",
        "length(btrim(reference)) BETWEEN 1 AND 160",
    )

    op.create_table(
        "invoice_cancellation",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            UUID,
            sa.ForeignKey("invoice.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("original_status", sa.Text(), nullable=False),
        sa.Column("reason_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "requested_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "requested_at",
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
            "original_status IN ('issued', 'sent', 'paid')",
            name="ck_invoice_cancellation_original_status",
        ),
        sa.CheckConstraint(
            "length(btrim(reason_snapshot)) BETWEEN 8 AND 500",
            name="ck_invoice_cancellation_reason",
        ),
    )
    op.create_index(
        "ix_invoice_cancellation_action_requested",
        "invoice_cancellation",
        ["action_id", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_cancellation_action_requested",
        table_name="invoice_cancellation",
    )
    op.drop_table("invoice_cancellation")
    op.drop_constraint(
        "ck_payment_reference",
        "payment_record",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_currency",
        "payment_record",
        type_="check",
    )
    op.drop_constraint(
        "uq_payment_record_invoice",
        "payment_record",
        type_="unique",
    )
    op.alter_column("payment_record", "reference", nullable=True)
