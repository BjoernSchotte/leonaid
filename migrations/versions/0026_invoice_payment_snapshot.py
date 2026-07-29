"""Freeze payment details into issued invoice snapshots.

Revision ID: 0026_invoice_payment_snapshot
Revises: 0025_privacy_retention_policy
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0026_invoice_payment_snapshot"
down_revision: str | None = "0025_privacy_retention_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Rechnungsprofile übernehmen Bankdaten aus ihrer gebundenen "
    "Rechtskonfiguration. Bestehende Rechnungen werden nur aus einer solchen "
    "Version oder der aktiven Rechtskonfiguration migriert. Bereits in 0012 "
    "explizit quarantänisierte Altbelege behalten einen ebenso expliziten "
    "Migrationsmarker; alle anderen unaufgelösten Belege brechen das Upgrade "
    "fail-closed ab."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"

SNAPSHOT_PROTECTION = """
CREATE OR REPLACE FUNCTION protect_invoice_issue_snapshot()
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
       OR NEW.payment_details_snapshot IS DISTINCT FROM OLD.payment_details_snapshot
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
"""

SNAPSHOT_PROTECTION_WITHOUT_PAYMENT = SNAPSHOT_PROTECTION.replace(
    "       OR NEW.payment_details_snapshot IS DISTINCT FROM "
    "OLD.payment_details_snapshot\n",
    "",
)


def upgrade() -> None:
    op.add_column("invoice_profile", sa.Column("bank_account_holder", sa.Text()))
    op.add_column("invoice_profile", sa.Column("iban", sa.Text()))
    op.add_column("invoice_profile", sa.Column("bic", sa.Text()))
    op.add_column("invoice", sa.Column("payment_details_snapshot", JSONB))

    op.execute(
        """
        UPDATE invoice_profile AS profile
        SET bank_account_holder = version.bank_account_holder,
            iban = version.iban,
            bic = version.bic
        FROM legal_configuration_version AS version
        WHERE version.id = profile.legal_configuration_version_id
        """
    )
    op.execute(
        """
        UPDATE invoice AS issued
        SET payment_details_snapshot = jsonb_build_object(
            'accountHolder', version.bank_account_holder,
            'iban', version.iban,
            'bic', version.bic
        )
        FROM legal_configuration_version AS version
        WHERE issued.payment_details_snapshot IS NULL
          AND version.id = COALESCE(
              (
                  SELECT profile.legal_configuration_version_id
                  FROM invoice_profile AS profile
                  WHERE profile.action_id = issued.action_id
              ),
              (
                  SELECT state.active_version_id
                  FROM legal_configuration_state AS state
                  LIMIT 1
              )
          )
        """
    )
    op.execute(
        """
        UPDATE invoice
        SET payment_details_snapshot = jsonb_build_object(
            'accountHolder', 'MIGRATION_REVIEW_REQUIRED',
            'iban', 'MIGRATION_REVIEW_REQUIRED',
            'bic', NULL
        )
        WHERE payment_details_snapshot IS NULL
          AND issuer_snapshot ->> 'taxIdentifier' = 'REVIEW-REQUIRED'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM invoice
                WHERE payment_details_snapshot IS NULL
            ) THEN
                RAISE EXCEPTION
                    'invoice payment snapshot migration requires an active '
                    'or profile-bound legal configuration';
            END IF;
        END;
        $$;
        """
    )
    op.alter_column("invoice", "payment_details_snapshot", nullable=False)
    op.create_check_constraint(
        "ck_invoice_profile_payment_details",
        "invoice_profile",
        "(bank_account_holder IS NULL AND iban IS NULL AND bic IS NULL) "
        "OR (bank_account_holder IS NOT NULL AND iban IS NOT NULL)",
    )
    op.execute(SNAPSHOT_PROTECTION)


def downgrade() -> None:
    op.execute(SNAPSHOT_PROTECTION_WITHOUT_PAYMENT)
    op.drop_constraint(
        "ck_invoice_profile_payment_details",
        "invoice_profile",
        type_="check",
    )
    op.drop_column("invoice", "payment_details_snapshot")
    op.drop_column("invoice_profile", "bic")
    op.drop_column("invoice_profile", "iban")
    op.drop_column("invoice_profile", "bank_account_holder")
