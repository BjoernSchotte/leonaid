"""Add optimistic action revisions and tighten publication invariants.

Revision ID: 0006_action_administration
Revises: 0005_action_templates
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_action_administration"
down_revision: str | None = "0005_action_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "charity_action",
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_charity_action_revision_positive",
        "charity_action",
        "revision > 0",
    )
    op.create_check_constraint(
        "ck_charity_action_publication_complete",
        "charity_action",
        "(publication_starts_at IS NULL) = (publication_ends_at IS NULL)",
    )
    op.create_unique_constraint(
        "uq_public_action_alias_action",
        "public_action_alias",
        ["action_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_public_action_alias_action",
        "public_action_alias",
        type_="unique",
    )
    op.drop_constraint(
        "ck_charity_action_publication_complete",
        "charity_action",
        type_="check",
    )
    op.drop_constraint(
        "ck_charity_action_revision_positive",
        "charity_action",
        type_="check",
    )
    op.drop_column("charity_action", "revision")
