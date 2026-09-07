"""Allow additional redirects while preserving the legacy primary order alias.

Revision ID: 0028_multiple_campaign_aliases
Revises: 0027_campaign_alias_namespaces
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_multiple_campaign_aliases"
down_revision: str | None = "0027_campaign_alias_namespaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Existing aliases remain enabled primary aliases with unchanged targets and "
    "switch timestamps. Downgrade refuses additional or edited aliases instead "
    "of silently discarding them. Resolve them explicitly before downgrade."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "public_action_alias",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")
        ),
    )
    op.add_column(
        "public_action_alias",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "public_action_alias",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "public_action_alias",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_unique_constraint(
        "uq_public_action_alias_id", "public_action_alias", ["id"]
    )
    op.create_check_constraint(
        "ck_public_action_alias_revision", "public_action_alias", "revision > 0"
    )
    # Existing publication controls remove a primary alias to disable it. New
    # redirect aliases have an independent enabled flag, not order authority.
    op.create_check_constraint(
        "ck_public_action_alias_primary_enabled",
        "public_action_alias",
        "NOT is_primary OR enabled",
    )
    op.drop_constraint(
        "uq_public_action_alias_action", "public_action_alias", type_="unique"
    )
    op.create_index(
        "uq_public_action_alias_primary_action",
        "public_action_alias",
        ["action_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.create_index(
        "ix_public_action_alias_action", "public_action_alias", ["action_id"]
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE public_action_alias IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM public_action_alias "
        "WHERE NOT is_primary OR NOT enabled OR revision <> 1) THEN "
        "RAISE EXCEPTION 'campaign alias downgrade requires extended alias resolution'; "
        "END IF; END $$"
    )
    op.drop_index("ix_public_action_alias_action", table_name="public_action_alias")
    op.drop_index(
        "uq_public_action_alias_primary_action", table_name="public_action_alias"
    )
    op.create_unique_constraint(
        "uq_public_action_alias_action", "public_action_alias", ["action_id"]
    )
    op.drop_constraint(
        "ck_public_action_alias_primary_enabled", "public_action_alias", type_="check"
    )
    op.drop_constraint(
        "ck_public_action_alias_revision", "public_action_alias", type_="check"
    )
    op.drop_constraint(
        "uq_public_action_alias_id", "public_action_alias", type_="unique"
    )
    for column in ("revision", "enabled", "is_primary", "id"):
        op.drop_column("public_action_alias", column)
