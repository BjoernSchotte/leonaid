"""Add durable privacy evidence and data-subject workflow records.

Revision ID: 0019_privacy_workflows
Revises: 0018_security_rate_limits
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0019_privacy_workflows"
down_revision: str | None = "0018_security_rate_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")
DATA_MIGRATION_REFERENCE = (
    "Bestehende Nachweise erhalten konservativ den Typ explicit_consent und "
    "bleiben bis zur fachlichen Prüfung als legal_review_pending markiert."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.add_column("consent_record", sa.Column("action_id", UUID))
    op.add_column("consent_record", sa.Column("commitment_id", UUID))
    op.add_column("consent_record", sa.Column("normalized_recipient", sa.Text()))
    op.add_column(
        "consent_record",
        sa.Column(
            "evidence_kind",
            sa.Text(),
            nullable=False,
            server_default="explicit_consent",
        ),
    )
    op.add_column(
        "consent_record",
        sa.Column(
            "legal_basis_status",
            sa.Text(),
            nullable=False,
            server_default="legal_review_pending",
        ),
    )
    op.create_foreign_key(
        "fk_consent_action",
        "consent_record",
        "charity_action",
        ["action_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_consent_commitment",
        "consent_record",
        "commitment",
        ["commitment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_consent_evidence_kind",
        "consent_record",
        "evidence_kind IN ('notice_acknowledgement', 'explicit_consent')",
    )
    op.create_check_constraint(
        "ck_consent_legal_basis_status",
        "consent_record",
        "legal_basis_status IN ('legal_review_pending', 'confirmed')",
    )
    op.create_index(
        "ix_consent_normalized_recipient",
        "consent_record",
        ["normalized_recipient"],
    )

    op.add_column(
        "suppression_entry",
        sa.Column(
            "consent_record_id",
            UUID,
            sa.ForeignKey("consent_record.id", ondelete="SET NULL"),
        ),
    )

    op.create_table(
        "privacy_erasure_case",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("subject_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column(
            "requested_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("anonymized_commitments", sa.Integer(), nullable=False),
        sa.Column("cleared_activity_notes", sa.Integer(), nullable=False),
        sa.Column("cleared_reminders", sa.Integer(), nullable=False),
        sa.Column("revoked_consents", sa.Integer(), nullable=False),
        sa.Column("retained_invoice_ids", JSONB, nullable=False),
        sa.Column("retained_document_ids", JSONB, nullable=False),
        sa.Column("retention_reasons", JSONB, nullable=False),
        sa.Column("open_decisions", JSONB, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status = 'completed_with_retention'",
            name="ck_privacy_erasure_status",
        ),
        sa.CheckConstraint(
            "subject_hash ~ '^[0-9a-f]{64}$'",
            name="ck_privacy_erasure_subject_hash",
        ),
    )


def downgrade() -> None:
    op.drop_table("privacy_erasure_case")
    op.drop_column("suppression_entry", "consent_record_id")
    op.drop_index("ix_consent_normalized_recipient", table_name="consent_record")
    op.drop_constraint(
        "ck_consent_legal_basis_status",
        "consent_record",
        type_="check",
    )
    op.drop_constraint("ck_consent_evidence_kind", "consent_record", type_="check")
    op.drop_constraint("fk_consent_commitment", "consent_record", type_="foreignkey")
    op.drop_constraint("fk_consent_action", "consent_record", type_="foreignkey")
    op.drop_column("consent_record", "legal_basis_status")
    op.drop_column("consent_record", "evidence_kind")
    op.drop_column("consent_record", "normalized_recipient")
    op.drop_column("consent_record", "commitment_id")
    op.drop_column("consent_record", "action_id")
