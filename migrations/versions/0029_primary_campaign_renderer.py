"""Select the primary alias renderer without changing order identity.

Revision ID: 0029_primary_campaign_renderer
Revises: 0028_multiple_campaign_aliases
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_primary_campaign_renderer"
down_revision: str | None = "0028_multiple_campaign_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Existing primary aliases retain their legacy renderer and order identity. "
    "Additional aliases remain canonical redirects. Downgrade refuses selected "
    "campaign renderers; use the audited Core command to select legacy first."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "public_action_alias",
        sa.Column(
            "campaign_redirect", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_check_constraint(
        "ck_public_action_alias_renderer",
        "public_action_alias",
        "is_primary OR NOT campaign_redirect",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE public_action_alias IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM public_action_alias "
        "WHERE campaign_redirect) THEN RAISE EXCEPTION "
        "'campaign renderer downgrade requires explicit legacy selection'; "
        "END IF; END $$"
    )
    op.drop_constraint(
        "ck_public_action_alias_renderer", "public_action_alias", type_="check"
    )
    op.drop_column("public_action_alias", "campaign_redirect")
