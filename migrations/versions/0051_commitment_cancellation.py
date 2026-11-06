"""Durable, reasoned order cancellation.

Revision ID: 0051_commitment_cancellation
Revises: 0050_invoice_partial_payments

One cancellation per order. It keeps the status the order had, the reason,
an optional note, who cancelled it and when, and the invoice cancellation it
caused (ADR-0009) when the order had an issued, unpaid invoice. The order row
itself only changes its status to ``cancelled``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0051_commitment_cancellation"
down_revision: str | None = "0050_invoice_partial_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE commitment_cancellation (
            id uuid PRIMARY KEY,
            action_id uuid NOT NULL
                REFERENCES charity_action(id) ON DELETE RESTRICT,
            commitment_id uuid NOT NULL UNIQUE
                REFERENCES commitment(id) ON DELETE RESTRICT,
            previous_status text NOT NULL,
            reason_snapshot text NOT NULL,
            note_snapshot text,
            requested_by_user_id uuid NOT NULL
                REFERENCES user_account(id) ON DELETE RESTRICT,
            invoice_cancellation_id uuid UNIQUE
                REFERENCES invoice_cancellation(id) ON DELETE RESTRICT,
            requested_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_commitment_cancellation_previous_status
                CHECK (previous_status IN
                    ('draft', 'review_ready', 'confirmed', 'invoiced')),
            CONSTRAINT ck_commitment_cancellation_reason
                CHECK (length(btrim(reason_snapshot)) BETWEEN 8 AND 500),
            CONSTRAINT ck_commitment_cancellation_note
                CHECK (note_snapshot IS NULL
                    OR length(btrim(note_snapshot)) BETWEEN 1 AND 1000)
        );
        CREATE INDEX ix_commitment_cancellation_action_requested
            ON commitment_cancellation (action_id, requested_at);
        """
    )


def downgrade() -> None:
    # A recorded cancellation is the only reason and author of a cancelled
    # order; the old schema cannot hold it, so the downgrade refuses.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM commitment_cancellation) THEN
                RAISE EXCEPTION
                    'order cancellations exist; downgrade refused';
            END IF;
        END;
        $$;
        """
    )
    op.execute("DROP TABLE commitment_cancellation")
