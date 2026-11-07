"""Start area a member chose: admin web app or acquisition PWA.

Revision ID: 0052_preferred_surface
Revises: 0051_commitment_cancellation

specs/multi-domain §6.7: `landingPath` honours this choice while the member
has a role for that app. NULL keeps the default rule. A personal setting: the
downgrade drops it, and members fall back to the default start area.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_preferred_surface"
down_revision: str | None = "0051_commitment_cancellation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "user_account", sa.Column("preferred_surface", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        "ck_user_account_preferred_surface",
        "user_account",
        "preferred_surface IS NULL OR preferred_surface IN ('web', 'pwa')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(
        "ck_user_account_preferred_surface", "user_account", type_="check"
    )
    op.drop_column("user_account", "preferred_surface")
