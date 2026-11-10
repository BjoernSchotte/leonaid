"""Extra donation in the order forms.

Revision ID: 0068_order_donations
Revises: 0067_donation_receipts

ADR-0016, spec mails-documents-donations-push §8.6.

- `allow_donation` on the order form of an action and of a template
  (default false): the form offers an optional extra donation.
- `commitment.donation_pledge_minor`: the amount the buyer added, kept on
  the order. The donation itself is created when the order becomes
  binding.
- Krapfentaxi template version 3: version 2 plus the capability `donations`
  and `allow_donation`. Existing actions keep their copy.
- `invoice_delivery.requested_by_user_id` may be empty for the pledge mail
  that follows a public order by itself: nobody of the club asked for it.

The downgrade refuses while an order carries a donation amount, a form
offers one, an action was created from template version 3 or a mail
without a requester exists.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0068_order_donations"
down_revision: str | None = "0067_donation_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "upgrade() adds nullable or defaulted columns, one check, and inserts "
    "Krapfentaxi template version 3 as a copy of version 2. No existing row "
    "is changed; relaxing NOT NULL keeps every existing row valid."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

TEMPLATE_TABLES = (
    "action_template_order_form",
    "action_template_offering",
    "action_template_capability",
    "action_template_version",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        ALTER TABLE action_template_order_form
            ADD COLUMN allow_donation boolean NOT NULL DEFAULT false;
        ALTER TABLE order_form_configuration
            ADD COLUMN allow_donation boolean NOT NULL DEFAULT false;
        ALTER TABLE commitment
            ADD COLUMN donation_pledge_minor bigint,
            ADD CONSTRAINT ck_commitment_donation_pledge CHECK (
                donation_pledge_minor IS NULL
                OR donation_pledge_minor BETWEEN 100 AND 1000000
            );
        ALTER TABLE invoice_delivery
            ALTER COLUMN requested_by_user_id DROP NOT NULL,
            ADD CONSTRAINT ck_invoice_delivery_requester CHECK (
                requested_by_user_id IS NOT NULL OR donation_id IS NOT NULL
            );

        INSERT INTO action_template_version (
            template_key, version, display_name, description, is_available,
            presentation_theme
        )
        SELECT template_key, 3, display_name,
               'Krapfenbox-Bestellung für Firmen und Privatpersonen mit '
               'Sponsorakquise, öffentlichem Formular, Rechnungsfähigkeit und '
               'freiwilliger Zusatzspende.',
               is_available, presentation_theme
        FROM action_template_version
        WHERE template_key = 'krapfentaxi' AND version = 2;

        INSERT INTO action_template_capability (
            template_key, template_version, capability
        )
        SELECT template_key, 3, capability
        FROM action_template_capability
        WHERE template_key = 'krapfentaxi' AND template_version = 2
        UNION ALL
        SELECT 'krapfentaxi', 3, 'donations';

        INSERT INTO action_template_offering (
            template_key, template_version, code, name, status, unit,
            pieces_per_unit, unit_price_minor, currency, sort_order
        )
        SELECT template_key, 3, code, name, status, unit, pieces_per_unit,
               unit_price_minor, currency, sort_order
        FROM action_template_offering
        WHERE template_key = 'krapfentaxi' AND template_version = 2;

        INSERT INTO action_template_order_form (
            template_key, template_version, form_key, title, introduction,
            submit_label, require_company_name, require_contact_name,
            require_email, require_phone, require_delivery_address,
            require_billing_address, allow_message, allow_donation
        )
        SELECT template_key, 3, form_key, title, introduction, submit_label,
               require_company_name, require_contact_name, require_email,
               require_phone, require_delivery_address,
               require_billing_address, allow_message, true
        FROM action_template_order_form
        WHERE template_key = 'krapfentaxi' AND template_version = 2;
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                   SELECT 1 FROM commitment
                   WHERE donation_pledge_minor IS NOT NULL
               )
               OR EXISTS (
                   SELECT 1 FROM order_form_configuration WHERE allow_donation
               )
               OR EXISTS (
                   SELECT 1 FROM action_template_snapshot
                   WHERE template_key = 'krapfentaxi' AND template_version = 3
               )
               OR EXISTS (
                   SELECT 1 FROM invoice_delivery
                   WHERE requested_by_user_id IS NULL
               )
            THEN
                RAISE EXCEPTION
                    '0068 downgrade refused: orders, forms, actions or mails '
                    'use the extra donation';
            END IF;
        END;
        $$;
        """
    )
    # Published template versions are immutable; removing version 3 again is
    # the one exception, and only while no action was created from it.
    for table in TEMPLATE_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER trg_{table}_immutable")
    op.execute(
        """
        DELETE FROM action_template_order_form
        WHERE template_key = 'krapfentaxi' AND template_version = 3;
        DELETE FROM action_template_offering
        WHERE template_key = 'krapfentaxi' AND template_version = 3;
        DELETE FROM action_template_capability
        WHERE template_key = 'krapfentaxi' AND template_version = 3;
        DELETE FROM action_template_version
        WHERE template_key = 'krapfentaxi' AND version = 3;
        """
    )
    for table in TEMPLATE_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER trg_{table}_immutable")
    op.execute(
        """
        ALTER TABLE invoice_delivery
            DROP CONSTRAINT ck_invoice_delivery_requester,
            ALTER COLUMN requested_by_user_id SET NOT NULL;
        ALTER TABLE commitment
            DROP CONSTRAINT ck_commitment_donation_pledge,
            DROP COLUMN donation_pledge_minor;
        ALTER TABLE order_form_configuration DROP COLUMN allow_donation;
        ALTER TABLE action_template_order_form DROP COLUMN allow_donation;
        """
    )
