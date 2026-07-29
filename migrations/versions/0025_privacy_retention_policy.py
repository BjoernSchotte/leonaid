"""Snapshot active retention policy in privacy erasure cases.

Revision ID: 0025_privacy_retention_policy
Revises: 0024_invoice_legal_configuration
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0025_privacy_retention_policy"
down_revision: str | None = "0024_invoice_legal_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Bestehende Löschprotokolle behalten ihre bisherigen Gründe; neue Fälle "
    "speichern zusätzlich die freigegebene Aufbewahrungsregel unveränderlich."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.add_column(
        "privacy_erasure_case",
        sa.Column(
            "legal_configuration_version_id",
            UUID,
            sa.ForeignKey(
                "legal_configuration_version.id",
                ondelete="SET NULL",
            ),
        ),
    )
    op.add_column(
        "privacy_erasure_case",
        sa.Column("retention_schedule", JSONB),
    )
    op.create_index(
        "ix_privacy_erasure_legal_configuration_version",
        "privacy_erasure_case",
        ["legal_configuration_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_privacy_erasure_legal_configuration_version",
        table_name="privacy_erasure_case",
    )
    op.drop_column("privacy_erasure_case", "retention_schedule")
    op.drop_column(
        "privacy_erasure_case",
        "legal_configuration_version_id",
    )
