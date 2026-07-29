"""Add immutable legal configuration versions and four-eyes activation.

Revision ID: 0023_legal_configuration
Revises: 0022_email_change_workflow
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0023_legal_configuration"
down_revision: str | None = "0022_email_change_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")
SINGLETON_ID = "00000000-0000-4000-8000-000000000044"


def upgrade() -> None:
    op.create_table(
        "legal_configuration_version",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("version", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("street_line_1", sa.Text(), nullable=False),
        sa.Column("postal_code", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("tax_identifier", sa.Text(), nullable=False),
        sa.Column("issuer_email", sa.Text(), nullable=False),
        sa.Column("bank_account_holder", sa.Text(), nullable=False),
        sa.Column("iban", sa.Text(), nullable=False),
        sa.Column("bic", sa.Text()),
        sa.Column("tax_treatment", sa.Text(), nullable=False),
        sa.Column("tax_rate_basis_points", sa.Integer(), nullable=False),
        sa.Column("tax_note", sa.Text(), nullable=False),
        sa.Column("number_prefix", sa.Text(), nullable=False),
        sa.Column("number_width", sa.SmallInteger(), nullable=False),
        sa.Column("payment_terms_days", sa.SmallInteger(), nullable=False),
        sa.Column("public_order_legal_basis", sa.Text(), nullable=False),
        sa.Column("public_order_notice_text", sa.Text(), nullable=False),
        sa.Column("consent_text_version", sa.Text(), nullable=False),
        sa.Column("privacy_contact_email", sa.Text(), nullable=False),
        sa.Column("invoice_retention_days", sa.Integer(), nullable=False),
        sa.Column("commitment_retention_days", sa.Integer(), nullable=False),
        sa.Column("contact_retention_days", sa.Integer(), nullable=False),
        sa.Column("consent_evidence_retention_days", sa.Integer(), nullable=False),
        sa.Column("audit_retention_days", sa.Integer(), nullable=False),
        sa.Column("e_invoice_decision", sa.Text(), nullable=False),
        sa.Column("tax_evidence_id", sa.Text(), nullable=False),
        sa.Column("privacy_evidence_id", sa.Text(), nullable=False),
        sa.Column("e_invoice_evidence_id", sa.Text()),
        sa.Column(
            "created_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "tax_treatment IN ('standard_vat', 'small_business', 'tax_exempt')",
            name="ck_legal_configuration_tax_treatment",
        ),
        sa.CheckConstraint(
            "(tax_treatment = 'standard_vat' "
            "AND tax_rate_basis_points BETWEEN 1 AND 10000) "
            "OR (tax_treatment <> 'standard_vat' AND tax_rate_basis_points = 0)",
            name="ck_legal_configuration_tax_rate",
        ),
        sa.CheckConstraint(
            "number_width BETWEEN 3 AND 8",
            name="ck_legal_configuration_number_width",
        ),
        sa.CheckConstraint(
            "payment_terms_days BETWEEN 1 AND 120",
            name="ck_legal_configuration_payment_terms",
        ),
        sa.CheckConstraint(
            "invoice_retention_days BETWEEN 1 AND 36500 "
            "AND commitment_retention_days BETWEEN 1 AND 36500 "
            "AND contact_retention_days BETWEEN 1 AND 36500 "
            "AND consent_evidence_retention_days BETWEEN 1 AND 36500 "
            "AND audit_retention_days BETWEEN 1 AND 36500",
            name="ck_legal_configuration_retention",
        ),
        sa.CheckConstraint(
            "e_invoice_decision IN ('pending', 'not_required', 'required')",
            name="ck_legal_configuration_e_invoice_decision",
        ),
    )
    op.create_table(
        "legal_configuration_approval",
        sa.Column(
            "version_id",
            UUID,
            sa.ForeignKey("legal_configuration_version.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "approved_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
    )
    op.create_table(
        "legal_configuration_state",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "draft_version_id",
            UUID,
            sa.ForeignKey("legal_configuration_version.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "active_version_id",
            UUID,
            sa.ForeignKey("legal_configuration_version.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "updated_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_legal_configuration_state_revision",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO legal_configuration_state (id, revision)
            VALUES (:id, 1)
            """
        ).bindparams(sa.bindparam("id", value=SINGLETON_ID, type_=UUID))
    )


def downgrade() -> None:
    op.drop_table("legal_configuration_state")
    op.drop_table("legal_configuration_approval")
    op.drop_table("legal_configuration_version")
