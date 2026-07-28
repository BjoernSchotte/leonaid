"""Add optimistic revisions for account status administration.

Revision ID: 0020_account_status_admin
Revises: 0019_privacy_workflows
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_account_status_admin"
down_revision: str | None = "0019_privacy_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_account",
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_user_account_revision_positive",
        "user_account",
        "revision > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_account_revision_positive",
        "user_account",
        type_="check",
    )
    op.drop_column("user_account", "revision")
