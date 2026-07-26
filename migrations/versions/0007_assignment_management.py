"""Add optimistic revisions and a chronological index for assignments.

Revision ID: 0007_assignment_management
Revises: 0006_action_administration
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_assignment_management"
down_revision: str | None = "0006_action_administration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "acquisition_assignment",
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_assignment_revision_positive",
        "acquisition_assignment",
        "revision > 0",
    )
    op.create_index(
        "ix_assignment_history_timeline",
        "acquisition_assignment_history",
        ["assignment_id", "changed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assignment_history_timeline",
        table_name="acquisition_assignment_history",
    )
    op.drop_constraint(
        "ck_assignment_revision_positive",
        "acquisition_assignment",
        type_="check",
    )
    op.drop_column("acquisition_assignment", "revision")
