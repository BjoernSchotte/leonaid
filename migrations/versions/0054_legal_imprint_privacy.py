"""Impressum details (§ 5 DDG, § 18 Abs. 2 MStV) and the privacy policy.

Revision ID: 0054_legal_imprint_privacy
Revises: 0053_activity_occurred_at_bound

Legal configuration versions gain the Impressum fields that were missing
(authorised representatives, telephone, register entry, VAT ID, person
responsible for editorial content) and the texts of the public privacy page:
the privacy policy and the members' privacy notice. All columns are nullable:
versions saved before this revision have none of them, and production
activation (not the schema) requires the mandatory ones.

The carrier's legal form is now an explicit field (it decides which register
§ 5 Abs. 1 Nr. 4 DDG requires). Existing versions whose name says "e. V." or
"eingetragener Verein" are set to `registered_association`; all others stay
NULL and must be chosen before a production activation.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0054_legal_imprint_privacy"
down_revision: str | None = "0053_activity_occurred_at_bound"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGAL_FORMS = (
    "registered_association",
    "unregistered_association",
    "ggmbh",
    "gmbh",
    "cooperative",
    "foundation",
    "other",
)
# Published content the old schema cannot hold; legal_form is not listed: it
# is either backfilled from the name or a setting, not published text.
COLUMNS = (
    "imprint_representatives",
    "imprint_phone",
    "imprint_register_court",
    "imprint_register_number",
    "imprint_vat_id",
    "imprint_content_responsible_name",
    "imprint_content_responsible_address",
    "privacy_policy_text",
    "member_privacy_notice_text",
)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE legal_configuration_version
            ADD COLUMN legal_form text,
            ADD COLUMN imprint_representatives text,
            ADD COLUMN imprint_phone text,
            ADD COLUMN imprint_register_court text,
            ADD COLUMN imprint_register_number text,
            ADD COLUMN imprint_vat_id text,
            ADD COLUMN imprint_content_responsible_name text,
            ADD COLUMN imprint_content_responsible_address text,
            ADD COLUMN privacy_policy_text text,
            ADD COLUMN member_privacy_notice_text text,
            ADD CONSTRAINT ck_legal_configuration_imprint_text CHECK (
                (imprint_representatives IS NULL
                    OR length(btrim(imprint_representatives)) BETWEEN 3 AND 1000)
                AND (imprint_phone IS NULL
                    OR imprint_phone ~ '^[+(]?[0-9][0-9 ()/.-]{4,28}[0-9]$')
                AND (imprint_vat_id IS NULL
                    OR imprint_vat_id ~ '^[A-Z]{2}[A-Z0-9]{2,12}$')
            ),
            ADD CONSTRAINT ck_legal_configuration_imprint_register CHECK (
                (imprint_register_court IS NULL)
                    = (imprint_register_number IS NULL)
            ),
            ADD CONSTRAINT ck_legal_configuration_imprint_responsible CHECK (
                (imprint_content_responsible_name IS NULL)
                    = (imprint_content_responsible_address IS NULL)
            ),
            ADD CONSTRAINT ck_legal_configuration_privacy_texts CHECK (
                (privacy_policy_text IS NULL
                    OR length(privacy_policy_text) BETWEEN 200 AND 60000)
                AND (member_privacy_notice_text IS NULL
                    OR length(member_privacy_notice_text) BETWEEN 100 AND 30000)
            )
        """
    )
    forms = ", ".join(f"'{form}'" for form in LEGAL_FORMS)
    op.execute(
        f"""
        ALTER TABLE legal_configuration_version
            ADD CONSTRAINT ck_legal_configuration_legal_form CHECK (
                legal_form IS NULL OR legal_form IN ({forms})
            )
        """
    )
    op.execute(
        r"""
        UPDATE legal_configuration_version
        SET legal_form = 'registered_association'
        WHERE legal_name ~* '(^|[^[:alnum:]])e\.\s*v\.?($|[\s,;)])'
           OR legal_name ~* 'eingetragener\s+verein'
        """
    )


def downgrade() -> None:
    # Versions are immutable evidence of what was published. The old schema
    # cannot hold these values, so the downgrade refuses instead of dropping
    # a published Impressum or privacy policy.
    filled = " OR ".join(f"{column} IS NOT NULL" for column in COLUMNS)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM legal_configuration_version WHERE {filled}
            ) THEN
                RAISE EXCEPTION
                    'Impressum or privacy texts exist; downgrade refused';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "ALTER TABLE legal_configuration_version "
        + ", ".join(f"DROP COLUMN {column}" for column in (*COLUMNS, "legal_form"))
    )
