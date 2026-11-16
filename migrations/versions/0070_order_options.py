"""Delivery area, optional consents and the withdrawal notice of an order form.

Revision ID: 0070_order_options
Revises: 0069_legal_imprint_email

- `action_delivery_configuration.postal_codes`: the postal codes a public
  order may be delivered to. Empty means no restriction, as before.
  `area_label` names the area on the form ("Stadt und Landkreis Würzburg").
- `order_form_configuration`: two optional consent checkboxes (newsletter,
  photos at the delivery) and a notice on the right of withdrawal. NULL
  means the form shows nothing, as before.
- `commitment.photo_consent_*`: the buyer agreed that photos of this
  delivery may be published, with the wording's version.
- `offering.donation_share_minor`: how much of the unit price goes to the
  beneficiaries; the public page shows it ("davon 1,00 € pro Stück").

The newsletter consent is a `consent_record` (purpose `club_newsletter`),
which needs no column. The downgrade refuses while any of the new values is
set: they are evidence of what a buyer agreed to.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0070_order_options"
down_revision: str | None = "0069_legal_imprint_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE action_delivery_configuration
            ADD COLUMN postal_codes text[] NOT NULL DEFAULT '{}',
            ADD COLUMN area_label text,
            ADD CONSTRAINT ck_delivery_postal_codes CHECK (
                array_position(postal_codes, NULL) IS NULL
                AND cardinality(postal_codes) <= 2000
            ),
            ADD CONSTRAINT ck_delivery_area_label CHECK (
                area_label IS NULL OR length(area_label) BETWEEN 2 AND 200
            )
        """
    )
    op.execute(
        """
        ALTER TABLE order_form_configuration
            ADD COLUMN newsletter_consent_text text,
            ADD COLUMN photo_consent_text text,
            ADD COLUMN withdrawal_notice text,
            ADD CONSTRAINT ck_order_form_newsletter_text CHECK (
                newsletter_consent_text IS NULL
                OR length(newsletter_consent_text) BETWEEN 10 AND 600
            ),
            ADD CONSTRAINT ck_order_form_photo_text CHECK (
                photo_consent_text IS NULL
                OR length(photo_consent_text) BETWEEN 10 AND 600
            ),
            ADD CONSTRAINT ck_order_form_withdrawal_notice CHECK (
                withdrawal_notice IS NULL
                OR length(withdrawal_notice) BETWEEN 10 AND 1000
            )
        """
    )
    op.execute(
        """
        ALTER TABLE offering
            ADD COLUMN donation_share_minor bigint,
            ADD CONSTRAINT ck_offering_donation_share CHECK (
                donation_share_minor IS NULL
                OR donation_share_minor BETWEEN 0 AND unit_price_minor
            )
        """
    )
    op.execute(
        """
        ALTER TABLE commitment
            ADD COLUMN photo_consent_at timestamptz,
            ADD COLUMN photo_consent_text_version text,
            ADD CONSTRAINT ck_commitment_photo_consent CHECK (
                (photo_consent_at IS NULL) = (photo_consent_text_version IS NULL)
            )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM commitment WHERE photo_consent_at IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM order_form_configuration
                WHERE newsletter_consent_text IS NOT NULL
                   OR photo_consent_text IS NOT NULL
                   OR withdrawal_notice IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM offering WHERE donation_share_minor IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM action_delivery_configuration
                WHERE cardinality(postal_codes) > 0 OR area_label IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    '0070 downgrade refused: order options are in use';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        """
        ALTER TABLE commitment
            DROP COLUMN photo_consent_text_version,
            DROP COLUMN photo_consent_at
        """
    )
    op.execute("ALTER TABLE offering DROP COLUMN donation_share_minor")
    op.execute(
        """
        ALTER TABLE order_form_configuration
            DROP COLUMN withdrawal_notice,
            DROP COLUMN photo_consent_text,
            DROP COLUMN newsletter_consent_text
        """
    )
    op.execute(
        """
        ALTER TABLE action_delivery_configuration
            DROP COLUMN area_label,
            DROP COLUMN postal_codes
        """
    )
