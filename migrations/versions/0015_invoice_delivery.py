"""Add durable invoice delivery intents linked to immutable PDFs.

Revision ID: 0015_invoice_delivery
Revises: 0014_generated_document_lookups
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0015_invoice_delivery"
down_revision: str | None = "0014_generated_document_lookups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "invoice_delivery",
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
        ),
        sa.Column(
            "generated_document_id",
            UUID,
            sa.ForeignKey("generated_document.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "outbox_event_id",
            UUID,
            sa.ForeignKey("outbox_event.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("recipient_email_snapshot", sa.Text(), nullable=False),
        sa.Column("subject_snapshot", sa.Text(), nullable=False),
        sa.Column("text_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "requested_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
            "length(btrim(recipient_email_snapshot)) > 3",
            name="ck_invoice_delivery_recipient",
        ),
        sa.CheckConstraint(
            "length(btrim(subject_snapshot)) > 0",
            name="ck_invoice_delivery_subject",
        ),
        sa.CheckConstraint(
            "length(btrim(text_snapshot)) > 0",
            name="ck_invoice_delivery_text",
        ),
    )
    op.create_index(
        "ix_invoice_delivery_invoice_requested",
        "invoice_delivery",
        ["invoice_id", "requested_at"],
    )
    op.create_index(
        "ix_invoice_delivery_action_requested",
        "invoice_delivery",
        ["action_id", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_delivery_action_requested",
        table_name="invoice_delivery",
    )
    op.drop_index(
        "ix_invoice_delivery_invoice_requested",
        table_name="invoice_delivery",
    )
    op.drop_table("invoice_delivery")
