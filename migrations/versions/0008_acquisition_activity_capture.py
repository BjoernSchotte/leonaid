"""Add manual acquisition activity snapshots and reminder indexes.

Revision ID: 0008_activity_capture
Revises: 0007_assignment_management
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_activity_capture"
down_revision: str | None = "0007_assignment_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "acquisition_activity",
        sa.Column("next_action_snapshot", sa.Text()),
    )
    op.add_column(
        "acquisition_activity",
        sa.Column("due_at_snapshot", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "acquisition_activity",
        sa.Column("assignment_revision", sa.BigInteger()),
    )
    op.create_check_constraint(
        "ck_acquisition_activity_next_action_length",
        "acquisition_activity",
        (
            "next_action_snapshot IS NULL "
            "OR char_length(next_action_snapshot) BETWEEN 1 AND 300"
        ),
    )
    op.create_check_constraint(
        "ck_acquisition_activity_reminder_pair",
        "acquisition_activity",
        "(next_action_snapshot IS NULL) = (due_at_snapshot IS NULL)",
    )
    op.create_check_constraint(
        "ck_acquisition_activity_assignment_revision",
        "acquisition_activity",
        (
            "assignment_revision IS NULL "
            "OR (assignment_revision > 0 AND assignment_id IS NOT NULL)"
        ),
    )
    op.create_index(
        "ix_acquisition_activity_assignment_timeline",
        "acquisition_activity",
        ["assignment_id", sa.text("occurred_at DESC"), "id"],
    )
    op.create_index(
        "ix_acquisition_assignment_acquirer_due",
        "acquisition_assignment",
        ["action_id", "acquirer_user_id", "due_at"],
        postgresql_where=sa.text("due_at IS NOT NULL AND status <> 'handed_over'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_acquisition_assignment_acquirer_due",
        table_name="acquisition_assignment",
    )
    op.drop_index(
        "ix_acquisition_activity_assignment_timeline",
        table_name="acquisition_activity",
    )
    op.drop_constraint(
        "ck_acquisition_activity_assignment_revision",
        "acquisition_activity",
        type_="check",
    )
    op.drop_constraint(
        "ck_acquisition_activity_reminder_pair",
        "acquisition_activity",
        type_="check",
    )
    op.drop_constraint(
        "ck_acquisition_activity_next_action_length",
        "acquisition_activity",
        type_="check",
    )
    op.drop_column("acquisition_activity", "assignment_revision")
    op.drop_column("acquisition_activity", "due_at_snapshot")
    op.drop_column("acquisition_activity", "next_action_snapshot")
