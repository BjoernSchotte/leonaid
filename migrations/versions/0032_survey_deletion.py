"""Content-free, durable survey erasure records.

Revision ID: 0032_survey_deletion
Revises: 0031_survey_exports
"""

from alembic import op

revision = "0032_survey_deletion"
down_revision = "0031_survey_exports"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = "Additive erasure ledger; no existing survey is deleted."
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE survey_deletion (
      survey_id uuid PRIMARY KEY,
      requested_by uuid NOT NULL,
      operation_hash text NOT NULL CHECK(operation_hash ~ '^[0-9a-f]{64}$'),
      expected_revision bigint NOT NULL CHECK(expected_revision > 0),
      event_id uuid NOT NULL UNIQUE,
      requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      completed_at timestamptz
    );
    CREATE FUNCTION prevent_erased_survey_write() RETURNS trigger AS $$
    BEGIN
      IF EXISTS(SELECT 1 FROM survey_deletion WHERE survey_id=NEW.id) THEN
        RAISE EXCEPTION 'Survey erasure has been requested' USING ERRCODE='23000';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER survey_erasure_guard BEFORE INSERT OR UPDATE ON survey
      FOR EACH ROW EXECUTE FUNCTION prevent_erased_survey_write();
    """)


def downgrade() -> None:
    # Dropping the ledger would allow erased IDs to be recreated. Restore only
    # after an explicit recovery procedure, never through an automatic downgrade.
    raise RuntimeError("Survey erasure records must be preserved during recovery.")
