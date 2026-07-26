"""Add immutable action-template versions and typed instantiated configuration.

Revision ID: 0005_action_templates
Revises: 0004_passwordless_sessions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0005_action_templates"
down_revision: str | None = "0004_passwordless_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "action_template_version",
        sa.Column("template_key", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "template_key IN ('blank', 'krapfentaxi')",
            name="ck_action_template_key",
        ),
        sa.CheckConstraint("version > 0", name="ck_action_template_version"),
    )
    op.create_table(
        "action_template_capability",
        sa.Column("template_key", sa.Text(), primary_key=True),
        sa.Column("template_version", sa.Integer(), primary_key=True),
        sa.Column("capability", sa.Text(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["template_key", "template_version"],
            ["action_template_version.template_key", "action_template_version.version"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "capability IN ("
            "'acquisition', 'offerings', 'ordering', 'invoicing', "
            "'event_registration', 'tournament', 'booths', "
            "'volunteer_shifts', 'delivery')",
            name="ck_action_template_capability",
        ),
    )
    op.create_table(
        "action_template_offering",
        sa.Column("template_key", sa.Text(), primary_key=True),
        sa.Column("template_version", sa.Integer(), primary_key=True),
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("pieces_per_unit", sa.Integer()),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["template_key", "template_version"],
            ["action_template_version.template_key", "action_template_version.version"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'",
            name="ck_action_template_offering_code",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'inactive')",
            name="ck_action_template_offering_status",
        ),
        sa.CheckConstraint(
            "unit IN ('box', 'piece', 'package', 'sponsoring')",
            name="ck_action_template_offering_unit",
        ),
        sa.CheckConstraint(
            "pieces_per_unit IS NULL OR pieces_per_unit > 0",
            name="ck_action_template_offering_pieces",
        ),
        sa.CheckConstraint(
            "unit <> 'box' OR pieces_per_unit IS NOT NULL",
            name="ck_action_template_box_pieces",
        ),
        sa.CheckConstraint(
            "unit_price_minor >= 0",
            name="ck_action_template_offering_price",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_action_template_offering_currency",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_action_template_offering_sort_order",
        ),
    )
    op.create_table(
        "action_template_order_form",
        sa.Column("template_key", sa.Text(), primary_key=True),
        sa.Column("template_version", sa.Integer(), primary_key=True),
        sa.Column("form_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("introduction", sa.Text(), nullable=False),
        sa.Column("submit_label", sa.Text(), nullable=False),
        sa.Column(
            "require_company_name",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "require_contact_name",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "require_email",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "require_phone",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "require_delivery_address",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "require_billing_address",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "allow_message",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.ForeignKeyConstraint(
            ["template_key", "template_version"],
            ["action_template_version.template_key", "action_template_version.version"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "form_key ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'",
            name="ck_action_template_order_form_key",
        ),
        sa.CheckConstraint(
            "require_contact_name AND require_email",
            name="ck_action_template_order_form_contact",
        ),
    )

    op.add_column("offering", sa.Column("code", sa.Text()))
    op.execute(
        """
        UPDATE offering
        SET code = 'legacy-' || substring(id::text, 1, 8)
        WHERE code IS NULL
        """
    )
    op.alter_column(
        "offering",
        "code",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_offering_action_code",
        "offering",
        ["action_id", "code"],
    )
    op.create_check_constraint(
        "ck_offering_code",
        "offering",
        "code ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'",
    )

    op.create_table(
        "order_form_configuration",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("form_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("introduction", sa.Text(), nullable=False),
        sa.Column("submit_label", sa.Text(), nullable=False),
        sa.Column("require_company_name", sa.Boolean(), nullable=False),
        sa.Column("require_contact_name", sa.Boolean(), nullable=False),
        sa.Column("require_email", sa.Boolean(), nullable=False),
        sa.Column("require_phone", sa.Boolean(), nullable=False),
        sa.Column("require_delivery_address", sa.Boolean(), nullable=False),
        sa.Column("require_billing_address", sa.Boolean(), nullable=False),
        sa.Column("allow_message", sa.Boolean(), nullable=False),
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
            "form_key ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'",
            name="ck_order_form_configuration_key",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'inactive')",
            name="ck_order_form_configuration_status",
        ),
        sa.CheckConstraint(
            "require_contact_name AND require_email",
            name="ck_order_form_configuration_contact",
        ),
    )
    op.create_table(
        "action_template_snapshot",
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "copied_from_action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="RESTRICT"),
        ),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.ForeignKeyConstraint(
            ["template_key", "template_version"],
            ["action_template_version.template_key", "action_template_version.version"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(configuration) = 'object'",
            name="ck_action_template_snapshot_object",
        ),
    )

    _insert_builtin_templates()

    op.execute(
        """
        CREATE FUNCTION reject_action_template_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'published action template versions are immutable';
        END;
        $$
        """
    )
    for table in (
        "action_template_version",
        "action_template_capability",
        "action_template_offering",
        "action_template_order_form",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION reject_action_template_mutation()
            """
        )
    op.execute(
        """
        CREATE FUNCTION reject_action_template_snapshot_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'action template snapshots are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_template_snapshot_immutable
        BEFORE UPDATE ON action_template_snapshot
        FOR EACH ROW
        EXECUTE FUNCTION reject_action_template_snapshot_update()
        """
    )


def _insert_builtin_templates() -> None:
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
                "template_key": "blank",
                "version": 1,
                "display_name": "Leere Charity-Aktion",
                "description": (
                    "Technisch neutrale Ausgangsbasis ohne aktivierte "
                    "Capability-Module."
                ),
                "is_available": True,
            },
            {
                "template_key": "krapfentaxi",
                "version": 1,
                "display_name": "Krapfentaxi",
                "description": (
                    "Krapfenbox-Bestellung mit Sponsorakquise, öffentlichem "
                    "Bestellformular und Rechnungsfähigkeit."
                ),
                "is_available": True,
            },
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
                "template_version": 1,
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
                "template_version": 1,
                "code": "krapfenbox-24",
                "name": "Krapfenbox",
                "status": "draft",
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
                "template_version": 1,
                "form_key": "sponsor-bestellung",
                "title": "Krapfenboxen bestellen",
                "introduction": (
                    "Bestellen Sie Krapfenboxen und unterstützen Sie die "
                    "Begünstigten dieser Charity-Aktion."
                ),
                "submit_label": "Bestellung absenden",
                "require_company_name": True,
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
    op.execute("DROP FUNCTION reject_action_template_snapshot_update() CASCADE")
    op.execute("DROP FUNCTION reject_action_template_mutation() CASCADE")
    op.drop_table("action_template_snapshot")
    op.drop_table("order_form_configuration")
    op.drop_constraint("ck_offering_code", "offering", type_="check")
    op.drop_constraint("uq_offering_action_code", "offering", type_="unique")
    op.drop_column("offering", "code")
    op.drop_table("action_template_order_form")
    op.drop_table("action_template_offering")
    op.drop_table("action_template_capability")
    op.drop_table("action_template_version")
