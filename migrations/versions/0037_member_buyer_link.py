"""Explicitly verified member-to-CRM-person references for self orders."""

from alembic import op

revision = "0037_member_buyer_link"
down_revision = "0036_delivery_windows"
branch_labels = None
depends_on = None

DATA_MIGRATION_REFERENCE = "No links are inferred for existing members."
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE member_buyer_link (
            user_id uuid PRIMARY KEY REFERENCES user_account(id),
            twenty_person_id uuid UNIQUE,
            revision integer NOT NULL CHECK (revision > 0),
            verified_by_user_id uuid REFERENCES user_account(id),
            verified_at timestamptz,
            CHECK ((twenty_person_id IS NULL) = (verified_by_user_id IS NULL)),
            CHECK ((twenty_person_id IS NULL) = (verified_at IS NULL))
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE member_buyer_link")
