"""Index orders by action and creation time.

Revision ID: 0048_commitment_action_created
Revises: 0047_task_delivery_follow_up

The admin dashboard sums an action's orders per week of the last eight
weeks on every load. Without an index starting with ``action_id`` this scans
all orders of the installation. The index also serves the order list, which
filters by action and sorts by creation time.

Follows the delivery board migrations (0046, 0047), so the chain stays
linear: 0045 → 0046 → 0047 → 0048.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0048_commitment_action_created"
down_revision: str | None = "0047_task_delivery_follow_up"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_commitment_action_created "
        "ON commitment (action_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_commitment_action_created")
