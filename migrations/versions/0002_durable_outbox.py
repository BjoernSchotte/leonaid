"""Add command idempotency and durable outbox processing state.

Revision ID: 0002_durable_outbox
Revises: 0001_core_schema
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0002_durable_outbox"
down_revision: str | None = "0001_core_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "command_receipt",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("command_type", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("result", JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_command_receipt_request_hash",
        ),
        sa.CheckConstraint(
            "(result IS NULL) = (completed_at IS NULL)",
            name="ck_command_receipt_completion",
        ),
    )
    op.add_column("outbox_event", sa.Column("claim_token", UUID))
    op.add_column("outbox_event", sa.Column("claimed_by", sa.Text()))
    op.add_column("outbox_event", sa.Column("last_worker_id", sa.Text()))
    op.add_column(
        "outbox_event", sa.Column("last_attempt_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "outbox_event", sa.Column("dead_lettered_at", sa.DateTime(timezone=True))
    )
    op.add_column("outbox_event", sa.Column("last_error_detail", sa.Text()))
    op.add_column(
        "outbox_event",
        sa.Column(
            "manual_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "outbox_event",
        sa.Column("last_manual_retry_at", sa.DateTime(timezone=True)),
    )
    op.add_column("outbox_event", sa.Column("last_manual_retry_by", sa.Text()))
    op.create_check_constraint(
        "ck_outbox_claim_pair",
        "outbox_event",
        "(claim_token IS NULL) = (claimed_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_outbox_processing_claim",
        "outbox_event",
        "status <> 'processing' OR "
        "(claim_token IS NOT NULL AND claimed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_outbox_dead_letter_time",
        "outbox_event",
        "(status = 'dead_letter') = (dead_lettered_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_outbox_manual_retry_count",
        "outbox_event",
        "manual_retry_count >= 0",
    )

    op.add_column("activity_event", sa.Column("source_outbox_event_id", UUID))
    op.create_unique_constraint(
        "uq_activity_event_source_outbox",
        "activity_event",
        ["source_outbox_event_id"],
    )

    op.add_column("commitment", sa.Column("idempotency_key", sa.Text()))
    op.create_unique_constraint(
        "uq_commitment_idempotency_key",
        "commitment",
        ["idempotency_key"],
    )
    op.add_column("invoice", sa.Column("idempotency_key", sa.Text()))
    op.create_unique_constraint(
        "uq_invoice_idempotency_key",
        "invoice",
        ["idempotency_key"],
    )

    op.create_table(
        "mail_delivery",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "outbox_event_id",
            UUID,
            sa.ForeignKey("outbox_event.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("message_id", sa.Text(), nullable=False, unique=True),
        sa.Column("recipient_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "recipient_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_mail_delivery_recipient_sha256",
        ),
        sa.CheckConstraint(
            "status IN ('sent')",
            name="ck_mail_delivery_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("mail_delivery")
    op.drop_constraint("uq_invoice_idempotency_key", "invoice", type_="unique")
    op.drop_column("invoice", "idempotency_key")
    op.drop_constraint("uq_commitment_idempotency_key", "commitment", type_="unique")
    op.drop_column("commitment", "idempotency_key")
    op.drop_constraint(
        "uq_activity_event_source_outbox",
        "activity_event",
        type_="unique",
    )
    op.drop_column("activity_event", "source_outbox_event_id")
    op.drop_constraint("ck_outbox_manual_retry_count", "outbox_event", type_="check")
    op.drop_constraint("ck_outbox_dead_letter_time", "outbox_event", type_="check")
    op.drop_constraint("ck_outbox_processing_claim", "outbox_event", type_="check")
    op.drop_constraint("ck_outbox_claim_pair", "outbox_event", type_="check")
    op.drop_column("outbox_event", "last_manual_retry_by")
    op.drop_column("outbox_event", "last_manual_retry_at")
    op.drop_column("outbox_event", "manual_retry_count")
    op.drop_column("outbox_event", "last_error_detail")
    op.drop_column("outbox_event", "dead_lettered_at")
    op.drop_column("outbox_event", "last_attempt_at")
    op.drop_column("outbox_event", "claimed_by")
    op.drop_column("outbox_event", "last_worker_id")
    op.drop_column("outbox_event", "claim_token")
    op.drop_table("command_receipt")
