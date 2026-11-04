"""Manual "ausgebucht" switch per delivery window.

Revision ID: 0049_window_fully_booked
Revises: 0048_commitment_action_created

A manager marks a window as fully booked. Public orders can no longer choose
it; admin and acquisition capture may still book it after a confirmation.
Retiring a window clears the flag, so a retired window is never "full".
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0049_window_fully_booked"
down_revision: str | None = "0048_commitment_action_created"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE action_delivery_window
            ADD COLUMN fully_booked boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT ck_delivery_window_full_not_retired
                CHECK (NOT (retired AND fully_booked))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE action_delivery_window
            DROP CONSTRAINT ck_delivery_window_full_not_retired,
            DROP COLUMN fully_booked
        """
    )
