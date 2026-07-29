"""Bind invoice profiles to immutable legal configuration versions.

Revision ID: 0024_invoice_legal_configuration
Revises: 0023_legal_configuration
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0024_invoice_legal_configuration"
down_revision: str | None = "0023_legal_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Bestehende Rechnungsprofile bleiben bewusst ungebunden und damit bis "
    "zur nächsten freigegebenen Rechtskonfiguration fail-closed."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.add_column(
        "invoice_profile",
        sa.Column(
            "legal_configuration_version_id",
            UUID,
            sa.ForeignKey(
                "legal_configuration_version.id",
                ondelete="RESTRICT",
            ),
        ),
    )
    op.create_index(
        "ix_invoice_profile_legal_configuration_version",
        "invoice_profile",
        ["legal_configuration_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_profile_legal_configuration_version",
        table_name="invoice_profile",
    )
    op.drop_column("invoice_profile", "legal_configuration_version_id")
