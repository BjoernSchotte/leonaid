"""When a queued acquisition order was saved on the device.

Revision ID: 0052_commitment_captured_at
Revises: 0051_commitment_cancellation

The PWA offline queue sends orders later with ``capturedAt``
(specs/pwa-offline-queue/PLAN.md §11.2). The column keeps that moment for the
order history; ``created_at`` stays the server's receive time and keeps
driving lists, weekly values and invoices. Core accepts only 14 days back and
5 minutes ahead of its own time (decision D5); the check repeats that bound
against ``created_at`` so no write path can store a far-away capture time.
Activities need no column: ``occurred_at`` takes ``capturedAt`` and
``created_at`` the receive time.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0052_commitment_captured_at"
down_revision: str | None = "0051_commitment_cancellation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE commitment ADD COLUMN captured_at timestamptz;
        ALTER TABLE commitment ADD CONSTRAINT ck_commitment_captured_at
            CHECK (
                captured_at IS NULL
                OR (
                    source = 'acquisition'
                    AND captured_at >= created_at - interval '14 days'
                    AND captured_at <= created_at + interval '5 minutes'
                )
            );
        """
    )


def downgrade() -> None:
    # The capture time is history only and also stands in the order's
    # ``commitment_created`` audit event (payload ``capturedAt``), so dropping
    # the column loses no information; the older schema needs none of it.
    op.execute("ALTER TABLE commitment DROP COLUMN captured_at")
