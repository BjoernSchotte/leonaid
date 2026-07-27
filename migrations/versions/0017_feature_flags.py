"""Add the provider-neutral feature-flag registry.

Revision ID: 0017_feature_flags
Revises: 0016_invoice_settlements
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0017_feature_flags"
down_revision: str | None = "0016_invoice_settlements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    feature_flag = op.create_table(
        "feature_flag",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "updated_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "key IN ('admin.system_status_panel', 'admin.preview_notice')",
            name="ck_feature_flag_known_key",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_feature_flag_revision",
        ),
    )
    op.bulk_insert(
        feature_flag,
        [
            {
                "id": "95000000-0000-4000-8000-000000000001",
                "key": "admin.system_status_panel",
                "enabled": False,
                "revision": 1,
            },
            {
                "id": "95000000-0000-4000-8000-000000000002",
                "key": "admin.preview_notice",
                "enabled": False,
                "revision": 1,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("feature_flag")
