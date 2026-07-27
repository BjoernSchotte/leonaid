"""Add confirmed invoice profiles and immutable issue snapshots.

Revision ID: 0012_invoice_issuing
Revises: 0011_public_orders
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0012_invoice_issuing"
down_revision: str | None = "0011_public_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")
DATA_MIGRATION_REFERENCE = (
    "upgrade() normalisiert bestehende Rechnungsstatus und ergänzt vor den "
    "NOT-NULL-Constraints sämtliche neuen Snapshotfelder."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.create_table(
        "invoice_profile",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("street_line_1", sa.Text(), nullable=False),
        sa.Column("postal_code", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("tax_identifier", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("tax_treatment", sa.Text(), nullable=False),
        sa.Column("tax_rate_basis_points", sa.Integer(), nullable=False),
        sa.Column("tax_note", sa.Text(), nullable=False),
        sa.Column("number_prefix", sa.Text(), nullable=False),
        sa.Column("next_number", sa.BigInteger(), nullable=False),
        sa.Column("number_width", sa.SmallInteger(), nullable=False),
        sa.Column("payment_terms_days", sa.SmallInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
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
            "tax_treatment IN ('standard_vat', 'small_business', 'tax_exempt')",
            name="ck_invoice_profile_tax_treatment",
        ),
        sa.CheckConstraint(
            "(tax_treatment = 'standard_vat' "
            "AND tax_rate_basis_points BETWEEN 1 AND 10000) "
            "OR (tax_treatment <> 'standard_vat' AND tax_rate_basis_points = 0)",
            name="ck_invoice_profile_tax_rate",
        ),
        sa.CheckConstraint(
            "number_prefix ~ '^[A-Z0-9][A-Z0-9-]{0,23}$'",
            name="ck_invoice_profile_number_prefix",
        ),
        sa.CheckConstraint(
            "next_number > 0 AND number_width BETWEEN 3 AND 8",
            name="ck_invoice_profile_sequence",
        ),
        sa.CheckConstraint(
            "payment_terms_days BETWEEN 1 AND 120",
            name="ck_invoice_profile_payment_terms",
        ),
        sa.CheckConstraint(
            "country_code ~ '^[A-Z]{2}$'",
            name="ck_invoice_profile_country",
        ),
    )

    op.add_column("invoice", sa.Column("action_id", UUID))
    op.add_column("invoice", sa.Column("service_on", sa.Date()))
    op.add_column("invoice", sa.Column("issuer_snapshot", JSONB))
    op.add_column(
        "invoice",
        sa.Column(
            "approved_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column("invoice", sa.Column("tax_treatment", sa.Text()))
    op.add_column("invoice", sa.Column("tax_rate_basis_points", sa.Integer()))
    op.add_column("invoice", sa.Column("payment_reference", sa.Text()))

    op.execute(
        """
        UPDATE invoice
        SET action_id = commitment.action_id,
            service_on = charity_action.ends_on,
            issuer_snapshot = jsonb_build_object(
                'legalName', charity_action.carrier_name,
                'streetLine1', 'MIGRATION_REVIEW_REQUIRED',
                'postalCode', '00000',
                'city', 'MIGRATION_REVIEW_REQUIRED',
                'countryCode', 'DE',
                'taxIdentifier', 'REVIEW-REQUIRED',
                'email', 'review@leonaid.invalid'
            ),
            recipient_snapshot = jsonb_build_object(
                'recipientName', COALESCE(
                    invoice.recipient_snapshot ->> 'recipientName',
                    invoice.recipient_snapshot ->> 'recipient',
                    commitment.invoice_recipient_snapshot ->> 'recipientName',
                    commitment.customer_snapshot ->> 'displayName',
                    'MIGRATION_REVIEW_REQUIRED'
                ),
                'streetLine1', COALESCE(
                    invoice.recipient_snapshot ->> 'streetLine1',
                    invoice.recipient_snapshot ->> 'street',
                    commitment.invoice_recipient_snapshot ->> 'streetLine1',
                    'MIGRATION_REVIEW_REQUIRED'
                ),
                'postalCode', COALESCE(
                    invoice.recipient_snapshot ->> 'postalCode',
                    commitment.invoice_recipient_snapshot ->> 'postalCode',
                    '00000'
                ),
                'city', COALESCE(
                    invoice.recipient_snapshot ->> 'city',
                    commitment.invoice_recipient_snapshot ->> 'city',
                    'MIGRATION_REVIEW_REQUIRED'
                ),
                'countryCode', COALESCE(
                    invoice.recipient_snapshot ->> 'countryCode',
                    invoice.recipient_snapshot ->> 'country',
                    commitment.invoice_recipient_snapshot ->> 'countryCode',
                    'DE'
                ),
                'email', COALESCE(
                    invoice.recipient_snapshot -> 'email',
                    commitment.invoice_recipient_snapshot -> 'email',
                    'null'::jsonb
                )
            ),
            line_snapshot = CASE
                WHEN invoice.tax_minor = 0
                 AND EXISTS (
                    SELECT 1
                    FROM commitment_line
                    WHERE commitment_line.commitment_id = invoice.commitment_id
                 )
                THEN (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'description', commitment_line.description_snapshot,
                            'quantity', commitment_line.quantity,
                            'unit', commitment_line.unit_snapshot,
                            'unitPriceGrossMinor', commitment_line.unit_price_minor,
                            'taxRateBasisPoints', 0,
                            'netMinor', commitment_line.line_total_minor,
                            'taxMinor', 0,
                            'grossMinor', commitment_line.line_total_minor,
                            'currency', invoice.currency
                        )
                        ORDER BY commitment_line.id
                    )
                    FROM commitment_line
                    WHERE commitment_line.commitment_id = invoice.commitment_id
                )
                ELSE jsonb_build_array(
                    jsonb_build_object(
                        'description', 'Migrierte Alt-Rechnung',
                        'quantity', 1,
                        'unit', 'sponsoring',
                        'unitPriceGrossMinor', invoice.gross_minor,
                        'taxRateBasisPoints', CASE
                            WHEN invoice.net_minor > 0
                            THEN LEAST(
                                10000,
                                ROUND(
                                    invoice.tax_minor::numeric
                                    * 10000
                                    / invoice.net_minor
                                )::integer
                            )
                            ELSE 0
                        END,
                        'netMinor', invoice.net_minor,
                        'taxMinor', invoice.tax_minor,
                        'grossMinor', invoice.gross_minor,
                        'currency', invoice.currency
                    )
                )
            END,
            approved_by_user_id = COALESCE(
                (
                    SELECT user_account.id
                    FROM user_account
                    JOIN user_global_role
                      ON user_global_role.user_id = user_account.id
                    WHERE user_global_role.role = 'system_admin'
                    ORDER BY user_account.id
                    LIMIT 1
                ),
                (
                    SELECT user_account.id
                    FROM user_account
                    ORDER BY user_account.id
                    LIMIT 1
                )
            ),
            tax_treatment = CASE
                WHEN invoice.tax_minor > 0 THEN 'standard_vat'
                ELSE 'tax_exempt'
            END,
            tax_rate_basis_points = CASE
                WHEN invoice.tax_minor > 0 AND invoice.net_minor > 0
                THEN LEAST(
                    10000,
                    ROUND(
                        invoice.tax_minor::numeric
                        * 10000
                        / invoice.net_minor
                    )::integer
                )
                ELSE 0
            END,
            payment_reference = invoice.number
        FROM commitment
        JOIN charity_action ON charity_action.id = commitment.action_id
        WHERE commitment.id = invoice.commitment_id
        """
    )
    op.drop_constraint("ck_invoice_status", "invoice", type_="check")
    op.execute(
        """
        UPDATE invoice
        SET status = 'issued',
            issued_at = COALESCE(issued_at, created_at),
            due_on = COALESCE(due_on, created_at::date)
        WHERE status IN ('draft', 'approved', 'open')
        """
    )
    op.create_check_constraint(
        "ck_invoice_status",
        "invoice",
        "status IN ('issued', 'sent', 'paid', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_invoice_tax_treatment",
        "invoice",
        "tax_treatment IN ('standard_vat', 'small_business', 'tax_exempt')",
    )
    op.create_check_constraint(
        "ck_invoice_tax_rate",
        "invoice",
        "tax_rate_basis_points BETWEEN 0 AND 10000",
    )
    op.create_unique_constraint(
        "uq_invoice_commitment",
        "invoice",
        ["commitment_id"],
    )
    for column in (
        "action_id",
        "issued_at",
        "service_on",
        "due_on",
        "issuer_snapshot",
        "approved_by_user_id",
        "tax_treatment",
        "tax_rate_basis_points",
        "payment_reference",
    ):
        op.alter_column("invoice", column, nullable=False)

    op.execute(
        """
        CREATE FUNCTION protect_invoice_issue_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.action_id IS DISTINCT FROM OLD.action_id
               OR NEW.commitment_id IS DISTINCT FROM OLD.commitment_id
               OR NEW.number IS DISTINCT FROM OLD.number
               OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
               OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
               OR NEW.service_on IS DISTINCT FROM OLD.service_on
               OR NEW.due_on IS DISTINCT FROM OLD.due_on
               OR NEW.currency IS DISTINCT FROM OLD.currency
               OR NEW.net_minor IS DISTINCT FROM OLD.net_minor
               OR NEW.tax_minor IS DISTINCT FROM OLD.tax_minor
               OR NEW.gross_minor IS DISTINCT FROM OLD.gross_minor
               OR NEW.issuer_snapshot IS DISTINCT FROM OLD.issuer_snapshot
               OR NEW.recipient_snapshot IS DISTINCT FROM OLD.recipient_snapshot
               OR NEW.line_snapshot IS DISTINCT FROM OLD.line_snapshot
               OR NEW.tax_treatment IS DISTINCT FROM OLD.tax_treatment
               OR NEW.tax_rate_basis_points IS DISTINCT FROM OLD.tax_rate_basis_points
               OR NEW.tax_note IS DISTINCT FROM OLD.tax_note
               OR NEW.payment_reference IS DISTINCT FROM OLD.payment_reference
               OR NEW.approved_by_user_id IS DISTINCT FROM OLD.approved_by_user_id
            THEN
                RAISE EXCEPTION
                    'issued invoice snapshots are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER invoice_issue_snapshot_immutable
        BEFORE UPDATE ON invoice
        FOR EACH ROW
        EXECUTE FUNCTION protect_invoice_issue_snapshot();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER invoice_issue_snapshot_immutable ON invoice")
    op.execute("DROP FUNCTION protect_invoice_issue_snapshot()")
    op.drop_constraint("uq_invoice_commitment", "invoice", type_="unique")
    op.drop_constraint("ck_invoice_tax_rate", "invoice", type_="check")
    op.drop_constraint("ck_invoice_tax_treatment", "invoice", type_="check")
    op.drop_constraint("ck_invoice_status", "invoice", type_="check")
    op.execute("UPDATE invoice SET status = 'open' WHERE status IN ('issued', 'sent')")
    op.create_check_constraint(
        "ck_invoice_status",
        "invoice",
        "status IN ('draft', 'approved', 'open', 'paid', 'cancelled')",
    )
    for column in (
        "payment_reference",
        "tax_rate_basis_points",
        "tax_treatment",
        "approved_by_user_id",
        "issuer_snapshot",
        "service_on",
        "action_id",
    ):
        op.drop_column("invoice", column)
    op.alter_column("invoice", "due_on", nullable=True)
    op.alter_column("invoice", "issued_at", nullable=True)
    op.drop_table("invoice_profile")
