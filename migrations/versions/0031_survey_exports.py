"""Durable survey export jobs retaining object references for controlled deletion.

Revision ID: 0031_survey_exports
Revises: 0030_survey_analysis
"""

from alembic import op

revision = "0031_survey_exports"
down_revision = "0030_survey_analysis"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = (
    "Additive export jobs; existing surveys and answers are unchanged."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("""
    ALTER TABLE survey_analysis_snapshot ADD CONSTRAINT survey_analysis_identity UNIQUE(survey_id,id);
    CREATE TABLE survey_export_job (
      id uuid PRIMARY KEY,
      survey_id uuid NOT NULL REFERENCES survey(id),
      snapshot_id uuid NOT NULL,
      requested_by uuid NOT NULL REFERENCES user_account(id),
      operation_id text NOT NULL CHECK(length(operation_id) BETWEEN 1 AND 128),
      request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
      title text NOT NULL,
      product text NOT NULL CHECK(product IN ('responses_csv','responses_xlsx','analysis_xlsx','analysis_pdf')),
      event_id uuid NOT NULL UNIQUE REFERENCES outbox_event(id),
      status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','available','cancelled')),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      completed_at timestamptz,
      bucket text,
      object_key text,
      object_version text,
      sha256 text CHECK(sha256 ~ '^[0-9a-f]{64}$'),
      size_bytes bigint CHECK(size_bytes > 0),
      filename text,
      media_type text,
      render_version text,
      UNIQUE(survey_id,requested_by,operation_id),
      FOREIGN KEY(survey_id,snapshot_id) REFERENCES survey_analysis_snapshot(survey_id,id),
      CHECK(status <> 'available' OR (completed_at IS NOT NULL AND bucket IS NOT NULL
        AND object_key IS NOT NULL AND object_version IS NOT NULL AND object_version <> 'null'
        AND sha256 IS NOT NULL AND size_bytes IS NOT NULL AND filename IS NOT NULL
        AND media_type IS NOT NULL AND render_version IS NOT NULL))
    );
    CREATE INDEX survey_export_job_survey ON survey_export_job(survey_id,created_at);
    CREATE FUNCTION protect_survey_export_input() RETURNS trigger AS $$
    BEGIN
      IF ROW(NEW.id,NEW.survey_id,NEW.snapshot_id,NEW.requested_by,NEW.operation_id,
             NEW.request_hash,NEW.title,NEW.product,NEW.event_id,NEW.created_at)
         IS DISTINCT FROM
         ROW(OLD.id,OLD.survey_id,OLD.snapshot_id,OLD.requested_by,OLD.operation_id,
             OLD.request_hash,OLD.title,OLD.product,OLD.event_id,OLD.created_at) THEN
        RAISE EXCEPTION 'Survey export inputs are immutable' USING ERRCODE='23000';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER survey_export_input_immutable BEFORE UPDATE ON survey_export_job
      FOR EACH ROW EXECUTE FUNCTION protect_survey_export_input();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE survey_export_job;
    DROP FUNCTION protect_survey_export_input();
    ALTER TABLE survey_analysis_snapshot DROP CONSTRAINT survey_analysis_identity;
    """)
