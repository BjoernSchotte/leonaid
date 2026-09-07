"""Stable installation identity for external erasure checkpoints.

Revision ID: 0034_survey_recovery_identity
Revises: 0033_survey_retention
"""

from alembic import op

revision = "0034_survey_recovery_identity"
down_revision = "0033_survey_retention"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = (
    "Add one opaque installation ID; no survey content is changed."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade():
    op.execute("""
    CREATE TABLE survey_recovery_identity (
      singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
      installation_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid()
    );
    INSERT INTO survey_recovery_identity(singleton) VALUES(true);
    """)


def downgrade():
    raise RuntimeError("Recovery identity must be preserved with erasure checkpoints.")
