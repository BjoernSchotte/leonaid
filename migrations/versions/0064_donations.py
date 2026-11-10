"""Donations: capability, receiving body, donations and their pledge document.

Revision ID: 0064_donations
Revises: 0063_document_series

ADR-0016, spec mails-documents-donations-push §8.1 to §8.4.

- The capability `donations` joins the allowed values of actions and
  templates. No action and no template gets it here.
- `legal_configuration_version.donations` holds the receiving body (the part
  "Spenden" of the legal configuration) as one JSON object, NULL when the club
  takes no donations.
- `donation` with its number from the `donation` series (registered in
  `document_number` like every numbered document), one payment, and the
  frozen snapshot of its pledge document. `donation_payment_withdrawal` keeps
  every payment that was taken back; it is append-only.
- `generated_document` and `invoice_delivery` can belong to a donation.

The downgrade refuses while donations exist or an action or a legal
configuration uses the new parts.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0064_donations"
down_revision: str | None = "0063_document_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "upgrade() adds tables and nullable columns and replaces four checks by "
    "wider ones (capability values, document owner, delivery owner). No "
    "existing row is changed and every existing row satisfies the new checks."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

OLD_CAPABILITIES = (
    "capability IN ('acquisition', 'offerings', 'ordering', 'invoicing', "
    "'event_registration', 'tournament', 'booths', 'volunteer_shifts', 'delivery')"
)
NEW_CAPABILITIES = (
    "capability IN ('acquisition', 'offerings', 'ordering', 'invoicing', "
    "'event_registration', 'tournament', 'booths', 'volunteer_shifts', "
    "'delivery', 'donations')"
)
CAPABILITY_CHECKS = (
    ("ck_charity_action_capability", "charity_action_capability"),
    ("ck_action_template_capability", "action_template_capability"),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for name, table in CAPABILITY_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, NEW_CAPABILITIES)
    op.execute(
        """
        ALTER TABLE legal_configuration_version ADD COLUMN donations jsonb;

        CREATE TABLE donation (
            id uuid PRIMARY KEY,
            action_id uuid NOT NULL
                REFERENCES charity_action (id) ON DELETE RESTRICT,
            number text NOT NULL,
            donor_snapshot jsonb NOT NULL,
            pledged_minor bigint NOT NULL,
            currency text NOT NULL,
            source text NOT NULL,
            commitment_id uuid REFERENCES commitment (id) ON DELETE RESTRICT,
            status text NOT NULL,
            note text,
            pledge_snapshot jsonb NOT NULL,
            legal_configuration_version_id uuid NOT NULL
                REFERENCES legal_configuration_version (id) ON DELETE RESTRICT,
            received_minor bigint,
            received_on date,
            payment_note text,
            payment_recorded_by_user_id uuid
                REFERENCES user_account (id) ON DELETE RESTRICT,
            payment_recorded_at timestamptz,
            cancel_reason text,
            cancelled_by_user_id uuid
                REFERENCES user_account (id) ON DELETE RESTRICT,
            cancelled_at timestamptz,
            pledged_at timestamptz NOT NULL,
            created_by_user_id uuid
                REFERENCES user_account (id) ON DELETE RESTRICT,
            idempotency_key text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_donation_number UNIQUE (number),
            CONSTRAINT uq_donation_idempotency_key UNIQUE (idempotency_key),
            CONSTRAINT ck_donation_amount CHECK (
                currency = 'EUR' AND pledged_minor BETWEEN 100 AND 100000000
            ),
            CONSTRAINT ck_donation_source
                CHECK (source IN ('public_form', 'admin', 'acquisition')),
            CONSTRAINT ck_donation_status
                CHECK (status IN ('pledged', 'paid', 'cancelled')),
            CONSTRAINT ck_donation_note
                CHECK (note IS NULL OR length(btrim(note)) BETWEEN 1 AND 500),
            CONSTRAINT ck_donation_payment CHECK (
                (
                    status = 'paid'
                    AND received_minor > 0
                    AND received_on IS NOT NULL
                    AND payment_recorded_by_user_id IS NOT NULL
                    AND payment_recorded_at IS NOT NULL
                )
                OR (
                    status <> 'paid'
                    AND received_minor IS NULL
                    AND received_on IS NULL
                    AND payment_note IS NULL
                    AND payment_recorded_by_user_id IS NULL
                    AND payment_recorded_at IS NULL
                )
            ),
            CONSTRAINT ck_donation_cancellation CHECK (
                (
                    status = 'cancelled'
                    AND length(btrim(cancel_reason)) BETWEEN 8 AND 500
                    AND cancelled_by_user_id IS NOT NULL
                    AND cancelled_at IS NOT NULL
                )
                OR (
                    status <> 'cancelled'
                    AND cancel_reason IS NULL
                    AND cancelled_by_user_id IS NULL
                    AND cancelled_at IS NULL
                )
            )
        );
        CREATE INDEX ix_donation_action_pledged
            ON donation (action_id, pledged_at);
        CREATE INDEX ix_donation_commitment ON donation (commitment_id)
            WHERE commitment_id IS NOT NULL;

        CREATE TRIGGER donation_document_number
        BEFORE INSERT OR UPDATE OF number OR DELETE ON donation
        FOR EACH ROW
        EXECUTE FUNCTION register_document_number('donation');

        -- What the pledge document says is final; a cancelled donation is
        -- closed. Payment and cancellation fields move with the status.
        CREATE FUNCTION protect_donation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.action_id IS DISTINCT FROM OLD.action_id
               OR NEW.pledged_minor IS DISTINCT FROM OLD.pledged_minor
               OR NEW.currency IS DISTINCT FROM OLD.currency
               OR NEW.source IS DISTINCT FROM OLD.source
               OR NEW.commitment_id IS DISTINCT FROM OLD.commitment_id
               OR NEW.pledge_snapshot IS DISTINCT FROM OLD.pledge_snapshot
               OR NEW.legal_configuration_version_id
                   IS DISTINCT FROM OLD.legal_configuration_version_id
               OR NEW.pledged_at IS DISTINCT FROM OLD.pledged_at
               OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
            THEN
                RAISE EXCEPTION 'issued donation pledges are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status = 'cancelled' AND NEW.status <> 'cancelled' THEN
                RAISE EXCEPTION 'a cancelled donation is final'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER donation_immutable
        BEFORE UPDATE ON donation
        FOR EACH ROW
        EXECUTE FUNCTION protect_donation();

        CREATE TABLE donation_payment_withdrawal (
            id uuid PRIMARY KEY,
            action_id uuid NOT NULL
                REFERENCES charity_action (id) ON DELETE RESTRICT,
            donation_id uuid NOT NULL
                REFERENCES donation (id) ON DELETE CASCADE,
            received_minor bigint NOT NULL,
            received_on date NOT NULL,
            payment_note text,
            payment_recorded_by_user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE RESTRICT,
            payment_recorded_at timestamptz NOT NULL,
            reason_snapshot text NOT NULL,
            withdrawn_by_user_id uuid NOT NULL
                REFERENCES user_account (id) ON DELETE RESTRICT,
            withdrawn_at timestamptz NOT NULL,
            CONSTRAINT ck_donation_payment_withdrawal_reason
                CHECK (length(btrim(reason_snapshot)) BETWEEN 8 AND 500)
        );
        CREATE INDEX ix_donation_payment_withdrawal_donation
            ON donation_payment_withdrawal (donation_id, withdrawn_at);

        -- Append-only; a row only goes with its donation (seed and test
        -- data; no command deletes a donation).
        CREATE FUNCTION protect_donation_payment_withdrawal()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM donation WHERE id = OLD.donation_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'donation payment withdrawals are append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$;

        CREATE TRIGGER donation_payment_withdrawal_append_only
        BEFORE UPDATE OR DELETE ON donation_payment_withdrawal
        FOR EACH ROW
        EXECUTE FUNCTION protect_donation_payment_withdrawal();

        ALTER TABLE generated_document
            ADD COLUMN donation_id uuid
                REFERENCES donation (id) ON DELETE RESTRICT,
            ADD CONSTRAINT uq_generated_document_donation_version
                UNIQUE (donation_id, document_type, version);
        CREATE INDEX ix_generated_document_donation_created
            ON generated_document (donation_id, created_at);

        CREATE FUNCTION protect_generated_document_donation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.donation_id IS DISTINCT FROM OLD.donation_id THEN
                RAISE EXCEPTION 'a generated document keeps its donation'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER generated_document_donation_immutable
        BEFORE UPDATE ON generated_document
        FOR EACH ROW
        EXECUTE FUNCTION protect_generated_document_donation();

        ALTER TABLE invoice_delivery
            ADD COLUMN donation_id uuid
                REFERENCES donation (id) ON DELETE RESTRICT,
            ALTER COLUMN invoice_id DROP NOT NULL;
        CREATE INDEX ix_invoice_delivery_donation_requested
            ON invoice_delivery (donation_id, requested_at)
            WHERE donation_id IS NOT NULL;
        """
    )
    op.drop_constraint(
        "ck_generated_document_owner", "generated_document", type_="check"
    )
    op.create_check_constraint(
        "ck_generated_document_owner",
        "generated_document",
        "commitment_id IS NOT NULL OR invoice_id IS NOT NULL "
        "OR donation_id IS NOT NULL",
    )
    # A delivery carries a document of an invoice or of a donation.
    op.create_check_constraint(
        "ck_invoice_delivery_owner",
        "invoice_delivery",
        "(invoice_id IS NOT NULL) <> (donation_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM donation)
               OR EXISTS (
                   SELECT 1 FROM charity_action_capability
                   WHERE capability = 'donations'
               )
               OR EXISTS (
                   SELECT 1 FROM action_template_capability
                   WHERE capability = 'donations'
               )
               OR EXISTS (
                   SELECT 1 FROM legal_configuration_version
                   WHERE donations IS NOT NULL
               )
            THEN
                RAISE EXCEPTION
                    '0064 downgrade refused: donations, the donations '
                    'capability or a receiving body exist and the old schema '
                    'cannot hold them';
            END IF;
        END;
        $$;

        ALTER TABLE invoice_delivery
            DROP CONSTRAINT ck_invoice_delivery_owner,
            DROP COLUMN donation_id,
            ALTER COLUMN invoice_id SET NOT NULL;
        DROP TRIGGER generated_document_donation_immutable ON generated_document;
        DROP FUNCTION protect_generated_document_donation();
        ALTER TABLE generated_document
            DROP CONSTRAINT ck_generated_document_owner,
            DROP CONSTRAINT uq_generated_document_donation_version,
            DROP COLUMN donation_id,
            ADD CONSTRAINT ck_generated_document_owner
                CHECK (commitment_id IS NOT NULL OR invoice_id IS NOT NULL);
        DROP TABLE donation_payment_withdrawal;
        DROP FUNCTION protect_donation_payment_withdrawal();
        DROP TABLE donation;
        DROP FUNCTION protect_donation();
        ALTER TABLE legal_configuration_version DROP COLUMN donations;
        """
    )
    for name, table in CAPABILITY_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, OLD_CAPABILITIES)
