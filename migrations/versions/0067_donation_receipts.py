"""Donation receipts ("Zuwendungsbestätigung").

Revision ID: 0067_donation_receipts
Revises: 0066_donations

ADR-0016, spec mails-documents-donations-push §8.5.

`donation_receipt` holds one row per issued receipt: its number from the
`donation_receipt` series (registered in `document_number`), the frozen
snapshot the PDF is rendered from, and, once it was declared void, the
reason and what happened to the donor's paper. A donation has at most one
receipt that is not void. A receipt is never changed: only the void fields
are written, once.

The downgrade refuses while receipts exist.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0067_donation_receipts"
down_revision: str | None = "0066_donations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "upgrade() adds one table with its triggers. No existing row is changed."
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE donation_receipt (
            id uuid PRIMARY KEY,
            action_id uuid NOT NULL
                REFERENCES charity_action (id) ON DELETE RESTRICT,
            donation_id uuid NOT NULL
                REFERENCES donation (id) ON DELETE RESTRICT,
            number text NOT NULL,
            -- Which receipt of the donation this is; the version of its PDF.
            document_version integer NOT NULL,
            issued_on date NOT NULL,
            issued_at timestamptz NOT NULL,
            issued_by_user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE RESTRICT,
            snapshot jsonb NOT NULL,
            legal_configuration_version_id uuid NOT NULL
                REFERENCES legal_configuration_version (id) ON DELETE RESTRICT,
            voided_at timestamptz,
            void_reason text,
            void_evidence text,
            voided_by_user_id uuid
                REFERENCES user_account (id) ON DELETE RESTRICT,
            idempotency_key text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_donation_receipt_number UNIQUE (number),
            CONSTRAINT uq_donation_receipt_idempotency_key
                UNIQUE (idempotency_key),
            CONSTRAINT uq_donation_receipt_version
                UNIQUE (donation_id, document_version),
            CONSTRAINT ck_donation_receipt_version CHECK (document_version >= 1),
            CONSTRAINT ck_donation_receipt_void CHECK (
                (
                    voided_at IS NULL
                    AND void_reason IS NULL
                    AND void_evidence IS NULL
                    AND voided_by_user_id IS NULL
                )
                OR (
                    voided_at IS NOT NULL
                    AND void_reason IS NOT NULL
                    AND length(btrim(void_reason)) BETWEEN 8 AND 500
                    AND void_evidence IS NOT NULL
                    AND void_evidence IN (
                        'original_returned', 'tax_office_informed'
                    )
                    AND voided_by_user_id IS NOT NULL
                )
            )
        );
        -- One receipt per donation that is not void.
        CREATE UNIQUE INDEX uq_donation_receipt_valid
            ON donation_receipt (donation_id)
            WHERE voided_at IS NULL;
        CREATE INDEX ix_donation_receipt_action_issued
            ON donation_receipt (action_id, issued_at);

        CREATE TRIGGER donation_receipt_document_number
        BEFORE INSERT OR UPDATE OF number OR DELETE ON donation_receipt
        FOR EACH ROW
        EXECUTE FUNCTION register_document_number('donation_receipt');

        -- An issued receipt is final. Declaring it void writes the four void
        -- fields once; nothing else ever changes.
        CREATE FUNCTION protect_donation_receipt()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.action_id IS DISTINCT FROM OLD.action_id
               OR NEW.donation_id IS DISTINCT FROM OLD.donation_id
               OR NEW.number IS DISTINCT FROM OLD.number
               OR NEW.document_version IS DISTINCT FROM OLD.document_version
               OR NEW.issued_on IS DISTINCT FROM OLD.issued_on
               OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
               OR NEW.issued_by_user_id IS DISTINCT FROM OLD.issued_by_user_id
               OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
               OR NEW.legal_configuration_version_id
                   IS DISTINCT FROM OLD.legal_configuration_version_id
            THEN
                RAISE EXCEPTION 'issued donation receipts are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.voided_at IS NOT NULL AND (
                NEW.voided_at IS DISTINCT FROM OLD.voided_at
                OR NEW.void_reason IS DISTINCT FROM OLD.void_reason
                OR NEW.void_evidence IS DISTINCT FROM OLD.void_evidence
                OR NEW.voided_by_user_id IS DISTINCT FROM OLD.voided_by_user_id
            ) THEN
                RAISE EXCEPTION 'a void donation receipt stays void'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER donation_receipt_immutable
        BEFORE UPDATE ON donation_receipt
        FOR EACH ROW
        EXECUTE FUNCTION protect_donation_receipt();
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM donation_receipt) THEN
                RAISE EXCEPTION
                    '0067 downgrade refused: donation receipts exist';
            END IF;
        END;
        $$;
        DROP TABLE donation_receipt;
        DROP FUNCTION protect_donation_receipt();
        """
    )
