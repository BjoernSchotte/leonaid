"""Harden offering quantities and commitment snapshots.

Revision ID: 0010_offering_commitments
Revises: 0009_public_action_routes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0010_offering_commitments"
down_revision: str | None = "0009_public_action_routes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offering",
        sa.Column("allowed_quantity_units", ARRAY(sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE offering
        SET allowed_quantity_units = ARRAY[unit]::text[]
        """
    )
    op.alter_column(
        "offering",
        "allowed_quantity_units",
        existing_type=ARRAY(sa.Text()),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_offering_allowed_quantity_units",
        "offering",
        "cardinality(allowed_quantity_units) > 0 "
        "AND unit = ANY(allowed_quantity_units) "
        "AND allowed_quantity_units <@ "
        "ARRAY['box', 'piece', 'package', 'sponsoring']::text[]",
    )
    op.create_check_constraint(
        "ck_offering_complete_availability",
        "offering",
        "(available_from IS NULL AND available_until IS NULL) "
        "OR (available_from IS NOT NULL AND available_until IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_commitment_currency",
        "commitment",
        "currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        "ck_commitment_line_unit",
        "commitment_line",
        "unit_snapshot IN ('box', 'piece', 'package', 'sponsoring')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_commitment_line_unit",
        "commitment_line",
        type_="check",
    )
    op.drop_constraint(
        "ck_commitment_currency",
        "commitment",
        type_="check",
    )
    op.drop_constraint(
        "ck_offering_complete_availability",
        "offering",
        type_="check",
    )
    op.drop_constraint(
        "ck_offering_allowed_quantity_units",
        "offering",
        type_="check",
    )
    op.drop_column("offering", "allowed_quantity_units")
