"""Explicit, disabled-by-default survey retention policy and lifecycle clock.

Revision ID: 0033_survey_retention
Revises: 0032_survey_deletion
"""

from alembic import op

revision = "0033_survey_retention"
down_revision = "0032_survey_deletion"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = "Retention defaults to disabled. Existing closed surveys start their retention clock at migration time."
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade():
    op.execute("""
    ALTER TABLE survey_settings
      ADD COLUMN ended_retention_seconds integer CHECK(ended_retention_seconds BETWEEN 1 AND 315360000),
      ADD COLUMN trash_retention_seconds integer CHECK(trash_retention_seconds BETWEEN 1 AND 315360000),
      ADD COLUMN retention_configured_by uuid,
      ADD CONSTRAINT survey_retention_actor CHECK(
        (ended_retention_seconds IS NULL AND trash_retention_seconds IS NULL)
        OR retention_configured_by IS NOT NULL);
    ALTER TABLE survey ADD COLUMN retention_started_at timestamptz;
    UPDATE survey SET retention_started_at=clock_timestamp()
      WHERE status IN ('ended','archived');
    CREATE FUNCTION survey_retention_clock() RETURNS trigger AS $$
    BEGIN
      IF NEW.status IN ('active','draft') THEN
        NEW.retention_started_at := NULL;
      ELSIF NEW.status IN ('ended','archived') THEN
        IF TG_OP='INSERT' THEN
          NEW.retention_started_at := clock_timestamp();
        ELSIF OLD.status NOT IN ('ended','archived') THEN
          NEW.retention_started_at := clock_timestamp();
        ELSE
          NEW.retention_started_at := OLD.retention_started_at;
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER survey_retention_clock BEFORE INSERT OR UPDATE OF status ON survey
      FOR EACH ROW EXECUTE FUNCTION survey_retention_clock();
    """)


def downgrade():
    op.execute("""
    DROP TRIGGER survey_retention_clock ON survey;
    DROP FUNCTION survey_retention_clock();
    ALTER TABLE survey DROP COLUMN retention_started_at;
    ALTER TABLE survey_settings DROP CONSTRAINT survey_retention_actor,
      DROP COLUMN ended_retention_seconds, DROP COLUMN trash_retention_seconds,
      DROP COLUMN retention_configured_by;
    """)
