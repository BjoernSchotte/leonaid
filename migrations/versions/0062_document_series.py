"""Document series for the installation and the cancellation invoice.

Revision ID: 0062_document_series
Revises: 0061_delivery_geo_regeocode

ADR-0015. Until now every action counted its own invoice numbers
(`invoice_profile.next_number`) while the prefix was one for the installation
and `invoice.number` was unique for the installation: the first invoice of a
second action took a number the first action had already issued.

- `document_series(kind, prefix)` is the one counter per document kind and
  prefix. The migration creates the `invoice` row of every prefix in use. Its
  next number is the highest counter of the profiles with that prefix and
  never below the highest issued number of that prefix + 1.
- `document_number(number)` holds every issued number of every numbered
  document. Triggers on the document tables register the number, so two
  documents of different tables can never share one.
- `invoice_cancellation` gets the columns of the cancellation invoice
  ("Stornorechnung") and of the refund marker; `invoice_refund_withdrawal`
  keeps every marker that was taken back. Cancellations recorded before
  this migration keep NULL: no document is invented for them.
- Every action with the `invoicing` capability and without a profile gets one
  from the active legal configuration, if there is one.

`invoice_profile.next_number` stays for one release. Nothing reads or writes it
any more; the downgrade writes the series counters back into it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0062_document_series"
down_revision: str | None = "0061_delivery_geo_regeocode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "upgrade() only adds: two tables, nullable columns on invoice_cancellation "
    "and triggers. It copies every invoice number into document_number, "
    "creates one invoice series per prefix in use (highest profile counter, "
    "never below the highest issued number + 1) and a profile for actions "
    "with invoicing that have none. No existing row is changed."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

# The numeric tail of a number of one prefix, or NULL when it has none.
SERIAL_OF = """
    CASE
        WHEN left({number}, char_length({prefix})) = {prefix}
         AND substring({number} FROM char_length({prefix}) + 1) ~ '^[0-9]{{1,18}}$'
        THEN substring({number} FROM char_length({prefix}) + 1)::bigint
    END
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # No invoice may be written between the backfill of the registry and the
    # trigger that keeps it: a release runs this under the maintenance write
    # lock anyway (infra/upgrade/README.md), this holds also without it.
    op.execute("LOCK TABLE invoice, invoice_cancellation IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        CREATE TABLE document_series (
            kind text NOT NULL,
            prefix text NOT NULL,
            next_number bigint NOT NULL,
            width smallint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (kind, prefix),
            CONSTRAINT ck_document_series_kind
                CHECK (kind IN ('invoice', 'donation', 'donation_receipt')),
            CONSTRAINT ck_document_series_prefix
                CHECK (prefix ~ '^[A-Z0-9][A-Z0-9-]{0,23}$'),
            CONSTRAINT ck_document_series_sequence
                CHECK (next_number > 0 AND width BETWEEN 3 AND 8)
        );

        CREATE TABLE document_number (
            number text PRIMARY KEY,
            kind text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_document_number_kind CHECK (
                kind IN (
                    'invoice', 'invoice_cancellation',
                    'donation', 'donation_receipt'
                )
            )
        );

        -- Registers the number of a numbered document. The kind is the
        -- trigger argument. A number is set once and never changed; deleting
        -- the document (seed and test data only) frees its entry, the series
        -- counter never goes back.
        CREATE FUNCTION register_document_number()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.number IS NOT NULL THEN
                    DELETE FROM document_number
                    WHERE number = OLD.number AND kind = TG_ARGV[0];
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF NEW.number IS NOT DISTINCT FROM OLD.number THEN
                    RETURN NEW;
                END IF;
                IF OLD.number IS NOT NULL THEN
                    RAISE EXCEPTION 'issued document numbers are immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.number IS NOT NULL THEN
                INSERT INTO document_number (number, kind)
                VALUES (NEW.number, TG_ARGV[0]);
            END IF;
            RETURN NEW;
        END;
        $$;

        INSERT INTO document_number (number, kind, created_at)
        SELECT number, 'invoice', issued_at FROM invoice;

        CREATE TRIGGER invoice_document_number
        BEFORE INSERT OR UPDATE OF number OR DELETE ON invoice
        FOR EACH ROW
        EXECUTE FUNCTION register_document_number('invoice');

        ALTER TABLE invoice_cancellation
            ADD COLUMN number text,
            ADD COLUMN issued_on date,
            ADD COLUMN issued_at timestamptz,
            ADD COLUMN issued_by_user_id uuid
                REFERENCES user_account (id) ON DELETE RESTRICT,
            ADD COLUMN snapshot jsonb,
            ADD COLUMN document_version integer,
            ADD COLUMN refund_settled_on date,
            ADD COLUMN refund_note text,
            ADD COLUMN refund_settled_by_user_id uuid
                REFERENCES user_account (id) ON DELETE RESTRICT,
            ADD COLUMN refund_settled_at timestamptz,
            ADD CONSTRAINT uq_invoice_cancellation_number UNIQUE (number),
            ADD CONSTRAINT ck_invoice_cancellation_document CHECK (
                (
                    number IS NULL
                    AND issued_on IS NULL
                    AND issued_at IS NULL
                    AND issued_by_user_id IS NULL
                    AND snapshot IS NULL
                    AND document_version IS NULL
                )
                OR (
                    number IS NOT NULL
                    AND issued_on IS NOT NULL
                    AND issued_at IS NOT NULL
                    AND issued_by_user_id IS NOT NULL
                    AND snapshot IS NOT NULL
                    AND document_version > 0
                )
            ),
            ADD CONSTRAINT ck_invoice_cancellation_refund CHECK (
                (
                    refund_settled_on IS NULL
                    AND refund_note IS NULL
                    AND refund_settled_by_user_id IS NULL
                    AND refund_settled_at IS NULL
                )
                OR (
                    refund_settled_on IS NOT NULL
                    AND refund_settled_by_user_id IS NOT NULL
                    AND refund_settled_at IS NOT NULL
                    AND (
                        refund_note IS NULL
                        OR length(btrim(refund_note)) BETWEEN 1 AND 500
                    )
                )
            );

        CREATE TRIGGER invoice_cancellation_document_number
        BEFORE INSERT OR UPDATE OF number OR DELETE ON invoice_cancellation
        FOR EACH ROW
        EXECUTE FUNCTION register_document_number('invoice_cancellation');

        -- The issued cancellation invoice is final. The refund marker is
        -- not: a manager may withdraw it, and the withdrawal keeps who set
        -- it and who took it back.
        CREATE FUNCTION protect_invoice_cancellation_document()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.number IS NOT NULL AND (
                NEW.issued_on IS DISTINCT FROM OLD.issued_on
                OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
                OR NEW.issued_by_user_id IS DISTINCT FROM OLD.issued_by_user_id
                OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
                OR NEW.document_version IS DISTINCT FROM OLD.document_version
            ) THEN
                RAISE EXCEPTION 'issued cancellation invoices are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER invoice_cancellation_document_immutable
        BEFORE UPDATE ON invoice_cancellation
        FOR EACH ROW
        EXECUTE FUNCTION protect_invoice_cancellation_document();

        -- A refund marker that was taken back: what it said, who set it,
        -- who withdrew it and why.
        CREATE TABLE invoice_refund_withdrawal (
            id uuid PRIMARY KEY,
            action_id uuid NOT NULL
                REFERENCES charity_action (id) ON DELETE RESTRICT,
            invoice_cancellation_id uuid NOT NULL
                REFERENCES invoice_cancellation (id) ON DELETE CASCADE,
            settled_on date NOT NULL,
            note text,
            settled_by_user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE RESTRICT,
            settled_at timestamptz NOT NULL,
            reason_snapshot text NOT NULL,
            withdrawn_by_user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE RESTRICT,
            withdrawn_at timestamptz NOT NULL,
            CONSTRAINT ck_invoice_refund_withdrawal_reason
                CHECK (length(btrim(reason_snapshot)) BETWEEN 8 AND 500)
        );
        CREATE INDEX ix_invoice_refund_withdrawal_cancellation
            ON invoice_refund_withdrawal (invoice_cancellation_id, withdrawn_at);
        """
    )
    # A profile for every action with invoicing (spec §5.3). It copies the
    # active legal configuration, as its activation does for existing rows.
    op.execute(
        """
        INSERT INTO invoice_profile (
            id, action_id, legal_configuration_version_id, legal_name,
            street_line_1, postal_code, city, country_code, tax_identifier,
            email, tax_treatment, tax_rate_basis_points, tax_note,
            number_prefix, next_number, number_width, payment_terms_days,
            bank_account_holder, iban, bic, confirmed_at
        )
        SELECT
            gen_random_uuid(), capability.action_id, version.id,
            version.legal_name, version.street_line_1, version.postal_code,
            version.city, version.country_code, version.tax_identifier,
            version.issuer_email, version.tax_treatment,
            version.tax_rate_basis_points, version.tax_note,
            version.number_prefix, 1, version.number_width,
            version.payment_terms_days, version.bank_account_holder,
            version.iban, version.bic, state.updated_at
        FROM charity_action_capability AS capability
        CROSS JOIN legal_configuration_state AS state
        JOIN legal_configuration_version AS version
          ON version.id = state.active_version_id
        WHERE capability.capability = 'invoicing'
        ON CONFLICT (action_id) DO NOTHING
        """
    )
    serial = SERIAL_OF.format(number="invoice.number", prefix="profile.number_prefix")
    op.execute(
        f"""
        INSERT INTO document_series (kind, prefix, next_number, width)
        SELECT
            'invoice',
            profile.number_prefix,
            GREATEST(
                max(profile.next_number),
                COALESCE(
                    (SELECT max({serial}) FROM invoice),
                    0
                ) + 1
            ),
            max(profile.number_width)
        FROM invoice_profile AS profile
        GROUP BY profile.number_prefix
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM invoice_cancellation
                WHERE number IS NOT NULL OR refund_settled_on IS NOT NULL
            ) OR EXISTS (SELECT 1 FROM invoice_refund_withdrawal) THEN
                RAISE EXCEPTION
                    '0062 downgrade refused: issued cancellation invoices or '
                    'recorded refunds exist and the old schema cannot hold them';
            END IF;
        END;
        $$;

        -- The old code counts per profile again: give every profile the
        -- counter of its series, so no number is issued twice.
        UPDATE invoice_profile AS profile
        SET next_number = series.next_number
        FROM document_series AS series
        WHERE series.kind = 'invoice'
          AND series.prefix = profile.number_prefix
          AND series.next_number > profile.next_number;

        DROP TABLE invoice_refund_withdrawal;
        DROP TRIGGER invoice_cancellation_document_immutable
            ON invoice_cancellation;
        DROP FUNCTION protect_invoice_cancellation_document();
        DROP TRIGGER invoice_cancellation_document_number ON invoice_cancellation;
        DROP TRIGGER invoice_document_number ON invoice;
        DROP FUNCTION register_document_number();
        ALTER TABLE invoice_cancellation
            DROP CONSTRAINT ck_invoice_cancellation_refund,
            DROP CONSTRAINT ck_invoice_cancellation_document,
            DROP CONSTRAINT uq_invoice_cancellation_number,
            DROP COLUMN refund_settled_at,
            DROP COLUMN refund_settled_by_user_id,
            DROP COLUMN refund_note,
            DROP COLUMN refund_settled_on,
            DROP COLUMN document_version,
            DROP COLUMN snapshot,
            DROP COLUMN issued_by_user_id,
            DROP COLUMN issued_at,
            DROP COLUMN issued_on,
            DROP COLUMN number;
        DROP TABLE document_number;
        DROP TABLE document_series;
        """
    )
