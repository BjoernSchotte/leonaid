"""Create the LeonAid PoC core schema.

Revision ID: 0001_core_schema
Revises:
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=False)
JSON = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("CURRENT_TIMESTAMP")


def timestamps() -> tuple[sa.Column[datetime], sa.Column[datetime]]:
    return (
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint("email = lower(email)", name="ck_user_email_lower"),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'archived')",
            name="ck_user_status",
        ),
    )
    op.create_index(
        "uq_user_email",
        "user_account",
        [sa.text("lower(email)")],
        unique=True,
    )
    op.create_table(
        "user_global_role",
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.Text(), primary_key=True),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.CheckConstraint(
            "role IN ('system_admin', 'finance_reader', 'finance_manager')",
            name="ck_user_global_role",
        ),
    )
    op.create_table(
        "charity_action",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("carrier_name", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("publication_starts_at", sa.DateTime(timezone=True)),
        sa.Column("publication_ends_at", sa.DateTime(timezone=True)),
        sa.Column("archive_slug", sa.Text(), nullable=False, unique=True),
        sa.Column("goal_value", sa.Numeric(precision=18, scale=4)),
        sa.Column(
            "actual_value",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column("goal_unit", sa.Text()),
        sa.Column("currency", sa.String(length=3)),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('draft', 'scheduled', 'active', 'completed', 'archived')",
            name="ck_charity_action_status",
        ),
        sa.CheckConstraint("starts_on <= ends_on", name="ck_charity_action_period"),
        sa.CheckConstraint(
            "publication_starts_at IS NULL OR publication_ends_at IS NULL "
            "OR publication_starts_at <= publication_ends_at",
            name="ck_charity_action_publication_period",
        ),
        sa.CheckConstraint(
            "goal_value IS NULL OR goal_value >= 0",
            name="ck_charity_action_goal_nonnegative",
        ),
        sa.CheckConstraint(
            "actual_value >= 0",
            name="ck_charity_action_actual_nonnegative",
        ),
        sa.CheckConstraint(
            "(goal_value IS NULL) = (goal_unit IS NULL)",
            name="ck_charity_action_goal_unit",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
            name="ck_charity_action_currency",
        ),
    )
    op.create_table(
        "charity_action_capability",
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("capability", sa.Text(), primary_key=True),
        sa.Column(
            "enabled_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.CheckConstraint(
            "capability IN ("
            "'acquisition', 'offerings', 'ordering', 'invoicing', "
            "'event_registration', 'tournament', 'booths', "
            "'volunteer_shifts', 'delivery')",
            name="ck_charity_action_capability",
        ),
    )
    op.create_table(
        "public_action_alias",
        sa.Column("alias", sa.Text(), primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "switched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.CheckConstraint(
            "alias ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'",
            name="ck_public_action_alias_slug",
        ),
    )
    op.create_table(
        "beneficiary",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("organization_name", sa.Text(), nullable=False),
        sa.Column("public_description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
        sa.UniqueConstraint(
            "action_id",
            "organization_name",
            name="uq_beneficiary_action_name",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_beneficiary_sort_order"),
    )
    op.create_table(
        "action_membership",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "active_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("active_until", sa.DateTime(timezone=True)),
        sa.Column(
            "delegate_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
        ),
        *timestamps(),
        sa.UniqueConstraint(
            "action_id",
            "user_id",
            "role",
            name="uq_action_membership_role",
        ),
        sa.CheckConstraint(
            "role IN ('charity_admin', 'acquirer', 'finance_reader', 'driver')",
            name="ck_action_membership_role",
        ),
        sa.CheckConstraint(
            "active_until IS NULL OR active_from < active_until",
            name="ck_action_membership_period",
        ),
        sa.CheckConstraint(
            "delegate_user_id IS NULL OR delegate_user_id <> user_id",
            name="ck_action_membership_delegate",
        ),
    )
    op.create_table(
        "action_invitation",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email_snapshot", sa.Text(), nullable=False),
        sa.Column("role_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'expired', 'revoked')",
            name="ck_action_invitation_status",
        ),
        sa.CheckConstraint(
            "role_snapshot IN ('charity_admin', 'acquirer', 'finance_reader', 'driver')",
            name="ck_action_invitation_role",
        ),
        sa.CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$'",
            name="ck_action_invitation_digest",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_action_invitation_expiry"
        ),
    )
    op.create_table(
        "user_session",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "fresh_login_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("device_hint", sa.Text()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$'",
            name="ck_user_session_digest",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_user_session_expiry"),
    )
    op.create_table(
        "acquisition_assignment",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("twenty_company_id", UUID),
        sa.Column("twenty_person_id", UUID),
        sa.Column(
            "acquirer_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("next_action", sa.Text()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "(twenty_company_id IS NULL) <> (twenty_person_id IS NULL)",
            name="ck_assignment_exactly_one_party",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'contacted', 'committed', 'declined', 'handed_over')",
            name="ck_assignment_status",
        ),
        sa.CheckConstraint("priority BETWEEN 0 AND 3", name="ck_assignment_priority"),
    )
    op.create_index(
        "uq_assignment_company_acquirer",
        "acquisition_assignment",
        ["action_id", "twenty_company_id", "acquirer_user_id"],
        unique=True,
        postgresql_where=sa.text("twenty_company_id IS NOT NULL"),
    )
    op.create_index(
        "uq_assignment_person_acquirer",
        "acquisition_assignment",
        ["action_id", "twenty_person_id", "acquirer_user_id"],
        unique=True,
        postgresql_where=sa.text("twenty_person_id IS NOT NULL"),
    )
    op.create_table(
        "acquisition_assignment_history",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "assignment_id",
            UUID,
            sa.ForeignKey("acquisition_assignment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "changed_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_state", JSON, nullable=False),
        sa.Column("new_state", JSON, nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
    )
    op.create_table(
        "offering",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("pieces_per_unit", sa.Integer()),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("available_from", sa.DateTime(timezone=True)),
        sa.Column("available_until", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.UniqueConstraint("action_id", "name", name="uq_offering_action_name"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'inactive')",
            name="ck_offering_status",
        ),
        sa.CheckConstraint(
            "unit IN ('box', 'piece', 'package', 'sponsoring')",
            name="ck_offering_unit",
        ),
        sa.CheckConstraint(
            "pieces_per_unit IS NULL OR pieces_per_unit > 0",
            name="ck_offering_pieces",
        ),
        sa.CheckConstraint("unit_price_minor >= 0", name="ck_offering_price"),
        sa.CheckConstraint(
            "available_from IS NULL OR available_until IS NULL "
            "OR available_from < available_until",
            name="ck_offering_availability",
        ),
    )
    op.create_table(
        "commitment",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("twenty_company_id", UUID),
        sa.Column("twenty_person_id", UUID),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("customer_snapshot", JSON, nullable=False),
        sa.Column("invoice_recipient_snapshot", JSON),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "(twenty_company_id IS NULL) <> (twenty_person_id IS NULL)",
            name="ck_commitment_exactly_one_party",
        ),
        sa.CheckConstraint(
            "source IN ('acquisition', 'public_form', 'admin')",
            name="ck_commitment_source",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'review_ready', 'confirmed', 'invoiced', 'cancelled')",
            name="ck_commitment_status",
        ),
        sa.CheckConstraint("total_minor >= 0", name="ck_commitment_total"),
    )
    op.create_table(
        "commitment_line",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "commitment_id",
            UUID,
            sa.ForeignKey("commitment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "offering_id",
            UUID,
            sa.ForeignKey("offering.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("description_snapshot", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_snapshot", sa.Text(), nullable=False),
        sa.Column("pieces_per_unit_snapshot", sa.Integer()),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("line_total_minor", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "commitment_id",
            "offering_id",
            name="uq_commitment_line_offering",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_commitment_line_quantity"),
        sa.CheckConstraint("unit_price_minor >= 0", name="ck_commitment_line_price"),
        sa.CheckConstraint(
            "line_total_minor = quantity * unit_price_minor",
            name="ck_commitment_line_total",
        ),
        sa.CheckConstraint(
            "pieces_per_unit_snapshot IS NULL OR pieces_per_unit_snapshot > 0",
            name="ck_commitment_line_pieces",
        ),
    )
    op.create_table(
        "acquisition_activity",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            UUID,
            sa.ForeignKey("acquisition_assignment.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "actor_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "commitment_id",
            UUID,
            sa.ForeignKey("commitment.id", ondelete="SET NULL"),
        ),
        sa.Column("twenty_company_id", UUID),
        sa.Column("twenty_person_id", UUID),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.CheckConstraint(
            "channel IN ('phone', 'email', 'in_person', 'public_form', 'system')",
            name="ck_acquisition_activity_channel",
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 4000",
            name="ck_acquisition_activity_note_length",
        ),
    )
    op.create_table(
        "invoice",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "commitment_id",
            UUID,
            sa.ForeignKey("commitment.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("number", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("due_on", sa.Date()),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("net_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("gross_minor", sa.BigInteger(), nullable=False),
        sa.Column("recipient_snapshot", JSON, nullable=False),
        sa.Column("line_snapshot", JSON, nullable=False),
        sa.Column("tax_note", sa.Text(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'open', 'paid', 'cancelled')",
            name="ck_invoice_status",
        ),
        sa.CheckConstraint(
            "net_minor >= 0 AND tax_minor >= 0 AND gross_minor = net_minor + tax_minor",
            name="ck_invoice_amounts",
        ),
        sa.CheckConstraint("document_version > 0", name="ck_invoice_document_version"),
    )
    op.create_table(
        "generated_document",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "commitment_id",
            UUID,
            sa.ForeignKey("commitment.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "invoice_id",
            UUID,
            sa.ForeignKey("invoice.id", ondelete="RESTRICT"),
        ),
        sa.Column("twenty_company_id", UUID),
        sa.Column("twenty_person_id", UUID),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False, unique=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.UniqueConstraint(
            "invoice_id",
            "document_type",
            "version",
            name="uq_generated_document_invoice_version",
        ),
        sa.CheckConstraint(
            "commitment_id IS NOT NULL OR invoice_id IS NOT NULL",
            name="ck_generated_document_owner",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_generated_document_sha256",
        ),
        sa.CheckConstraint("version > 0", name="ck_generated_document_version"),
    )
    op.create_table(
        "payment_record",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "invoice_id",
            UUID,
            sa.ForeignKey("invoice.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column(
            "recorded_by_user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_payment_amount"),
    )
    op.create_table(
        "consent_record",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("twenty_company_id", UUID),
        sa.Column("twenty_person_id", UUID),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("text_version", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.CheckConstraint(
            "(twenty_company_id IS NULL) <> (twenty_person_id IS NULL)",
            name="ck_consent_exactly_one_party",
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'phone', 'postal')",
            name="ck_consent_channel",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="ck_consent_revocation",
        ),
    )
    op.create_table(
        "suppression_entry",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("normalized_recipient", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.UniqueConstraint(
            "normalized_recipient",
            "channel",
            "purpose",
            name="uq_suppression_recipient_channel_purpose",
        ),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id", UUID, sa.ForeignKey("charity_action.id", ondelete="SET NULL")
        ),
        sa.Column(
            "actor_user_id", UUID, sa.ForeignKey("user_account.id", ondelete="SET NULL")
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
    )
    op.create_index(
        "ix_audit_event_entity",
        "audit_event",
        ["entity_type", "entity_id", "occurred_at"],
    )
    op.create_table(
        "activity_event",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "action_id",
            UUID,
            sa.ForeignKey("charity_action.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("twenty_company_id", UUID),
        sa.Column("twenty_person_id", UUID),
        sa.Column("payload", JSON, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
    )
    op.create_table(
        "activity_event_recipient",
        sa.Column(
            "activity_event_id",
            UUID,
            sa.ForeignKey("activity_event.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "outbox_event",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'dead_letter')",
            name="ck_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
    )
    op.create_index(
        "ix_outbox_claim",
        "outbox_event",
        ["status", "available_at", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION enforce_charity_action_status_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF NEW.status = OLD.status THEN
            RETURN NEW;
          END IF;
          IF (OLD.status = 'draft' AND NEW.status = 'scheduled')
             OR (OLD.status = 'scheduled' AND NEW.status IN ('draft', 'active'))
             OR (OLD.status = 'active' AND NEW.status = 'completed')
             OR (OLD.status = 'completed' AND NEW.status = 'archived') THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'invalid charity action transition: % -> %',
            OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_charity_action_status_transition
        BEFORE UPDATE OF status ON charity_action
        FOR EACH ROW
        EXECUTE FUNCTION enforce_charity_action_status_transition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_user_account_status_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF NEW.status = OLD.status THEN
            RETURN NEW;
          END IF;
          IF (OLD.status = 'invited' AND NEW.status = 'active')
             OR (OLD.status = 'active' AND NEW.status IN ('suspended', 'archived'))
             OR (OLD.status = 'suspended' AND NEW.status IN ('active', 'archived')) THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'invalid user account transition: % -> %',
            OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_user_account_status_transition
        BEFORE UPDATE OF status ON user_account
        FOR EACH ROW
        EXECUTE FUNCTION enforce_user_account_status_transition();
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION enforce_user_account_status_transition() CASCADE")
    op.execute("DROP FUNCTION enforce_charity_action_status_transition() CASCADE")
    for table in (
        "outbox_event",
        "activity_event_recipient",
        "activity_event",
        "audit_event",
        "suppression_entry",
        "consent_record",
        "payment_record",
        "generated_document",
        "invoice",
        "acquisition_activity",
        "commitment_line",
        "commitment",
        "offering",
        "acquisition_assignment_history",
        "acquisition_assignment",
        "user_session",
        "action_invitation",
        "action_membership",
        "beneficiary",
        "public_action_alias",
        "charity_action_capability",
        "charity_action",
        "user_global_role",
        "user_account",
    ):
        op.drop_table(table)
