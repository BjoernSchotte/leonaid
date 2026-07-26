"""Persist public-order snapshots, references and rate-limit attempts.

Revision ID: 0011_public_orders
Revises: 0010_offering_commitments
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0011_public_orders"
down_revision: str | None = "0010_offering_commitments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.add_column(
        "commitment",
        sa.Column("delivery_recipient_snapshot", JSONB),
    )
    op.add_column(
        "commitment",
        sa.Column("message_snapshot", sa.Text()),
    )
    op.add_column(
        "commitment",
        sa.Column("public_reference", sa.Text()),
    )
    op.execute(
        """
        UPDATE commitment
        SET public_reference = 'LA-' || upper(replace(id::text, '-', '')),
            delivery_recipient_snapshot = COALESCE(
                invoice_recipient_snapshot - 'email',
                jsonb_build_object(
                    'recipientName', customer_snapshot ->> 'displayName',
                    'streetLine1', 'Goldenweg 1',
                    'postalCode', '00000',
                    'city', 'Golden-Datensatz',
                    'countryCode', 'DE'
                )
            )
        WHERE source = 'public_form'
        """
    )
    op.create_unique_constraint(
        "uq_commitment_public_reference",
        "commitment",
        ["public_reference"],
    )
    op.create_check_constraint(
        "ck_commitment_public_reference",
        "commitment",
        "(source = 'public_form' AND public_reference IS NOT NULL) "
        "OR (source <> 'public_form' AND public_reference IS NULL)",
    )
    op.create_check_constraint(
        "ck_commitment_message_length",
        "commitment",
        "message_snapshot IS NULL OR char_length(message_snapshot) <= 1000",
    )
    op.create_check_constraint(
        "ck_commitment_public_delivery",
        "commitment",
        "source <> 'public_form' OR delivery_recipient_snapshot IS NOT NULL",
    )

    op.create_table(
        "public_submission_attempt",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("fingerprint_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "fingerprint_hash ~ '^[0-9a-f]{64}$'",
            name="ck_public_submission_fingerprint",
        ),
    )
    op.create_index(
        "ix_public_submission_rate_window",
        "public_submission_attempt",
        ["action_id", "fingerprint_hash", "attempted_at"],
    )

    _insert_krapfentaxi_template_v2()


def _insert_krapfentaxi_template_v2() -> None:
    template_version = sa.table(
        "action_template_version",
        sa.column("template_key", sa.Text()),
        sa.column("version", sa.Integer()),
        sa.column("display_name", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("is_available", sa.Boolean()),
    )
    op.bulk_insert(
        template_version,
        [
            {
                "template_key": "krapfentaxi",
                "version": 2,
                "display_name": "Krapfentaxi",
                "description": (
                    "Krapfenbox-Bestellung für Firmen und Privatpersonen mit "
                    "Sponsorakquise, öffentlichem Formular und Rechnungsfähigkeit."
                ),
                "is_available": True,
            }
        ],
    )
    template_capability = sa.table(
        "action_template_capability",
        sa.column("template_key", sa.Text()),
        sa.column("template_version", sa.Integer()),
        sa.column("capability", sa.Text()),
    )
    op.bulk_insert(
        template_capability,
        [
            {
                "template_key": "krapfentaxi",
                "template_version": 2,
                "capability": capability,
            }
            for capability in (
                "acquisition",
                "offerings",
                "ordering",
                "invoicing",
            )
        ],
    )
    template_offering = sa.table(
        "action_template_offering",
        sa.column("template_key", sa.Text()),
        sa.column("template_version", sa.Integer()),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("status", sa.Text()),
        sa.column("unit", sa.Text()),
        sa.column("pieces_per_unit", sa.Integer()),
        sa.column("unit_price_minor", sa.BigInteger()),
        sa.column("currency", sa.String(length=3)),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        template_offering,
        [
            {
                "template_key": "krapfentaxi",
                "template_version": 2,
                "code": "krapfenbox-24",
                "name": "Krapfenbox",
                "status": "active",
                "unit": "box",
                "pieces_per_unit": 24,
                "unit_price_minor": 3600,
                "currency": "EUR",
                "sort_order": 0,
            }
        ],
    )
    template_form = sa.table(
        "action_template_order_form",
        sa.column("template_key", sa.Text()),
        sa.column("template_version", sa.Integer()),
        sa.column("form_key", sa.Text()),
        sa.column("title", sa.Text()),
        sa.column("introduction", sa.Text()),
        sa.column("submit_label", sa.Text()),
        sa.column("require_company_name", sa.Boolean()),
        sa.column("require_contact_name", sa.Boolean()),
        sa.column("require_email", sa.Boolean()),
        sa.column("require_phone", sa.Boolean()),
        sa.column("require_delivery_address", sa.Boolean()),
        sa.column("require_billing_address", sa.Boolean()),
        sa.column("allow_message", sa.Boolean()),
    )
    op.bulk_insert(
        template_form,
        [
            {
                "template_key": "krapfentaxi",
                "template_version": 2,
                "form_key": "sponsor-bestellung",
                "title": "Krapfenboxen bestellen",
                "introduction": (
                    "Bestellen Sie Krapfenboxen und unterstützen Sie die "
                    "Begünstigten dieser Charity-Aktion."
                ),
                "submit_label": "Bestellung verbindlich absenden",
                "require_company_name": False,
                "require_contact_name": True,
                "require_email": True,
                "require_phone": False,
                "require_delivery_address": True,
                "require_billing_address": True,
                "allow_message": True,
            }
        ],
    )


def downgrade() -> None:
    template_tables = (
        "action_template_order_form",
        "action_template_offering",
        "action_template_capability",
        "action_template_version",
    )
    for table in template_tables:
        op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    op.execute(
        """
        DELETE FROM action_template_order_form
        WHERE template_key = 'krapfentaxi' AND template_version = 2
        """
    )
    op.execute(
        """
        DELETE FROM action_template_offering
        WHERE template_key = 'krapfentaxi' AND template_version = 2
        """
    )
    op.execute(
        """
        DELETE FROM action_template_capability
        WHERE template_key = 'krapfentaxi' AND template_version = 2
        """
    )
    op.execute(
        """
        DELETE FROM action_template_version
        WHERE template_key = 'krapfentaxi' AND version = 2
        """
    )
    for table in template_tables:
        op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    op.drop_index(
        "ix_public_submission_rate_window",
        table_name="public_submission_attempt",
    )
    op.drop_table("public_submission_attempt")
    op.drop_constraint(
        "ck_commitment_public_delivery",
        "commitment",
        type_="check",
    )
    op.drop_constraint(
        "ck_commitment_message_length",
        "commitment",
        type_="check",
    )
    op.drop_constraint(
        "ck_commitment_public_reference",
        "commitment",
        type_="check",
    )
    op.drop_constraint(
        "uq_commitment_public_reference",
        "commitment",
        type_="unique",
    )
    op.drop_column("commitment", "public_reference")
    op.drop_column("commitment", "message_snapshot")
    op.drop_column("commitment", "delivery_recipient_snapshot")
