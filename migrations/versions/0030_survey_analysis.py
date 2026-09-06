"""Immutable selected-version analysis snapshots, with separately stored raw data.

Revision ID: 0030_survey_analysis
Revises: 0029_survey_invitations
"""

from alembic import op

revision = "0030_survey_analysis"
down_revision = "0029_survey_invitations"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = (
    "Additive immutable analysis storage; no response rows are rewritten."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade():
    op.execute("""
    CREATE TABLE survey_analysis_snapshot (
        id uuid PRIMARY KEY,
        survey_id uuid NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
        version_id uuid NOT NULL,
        payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
        private_responses jsonb NOT NULL CHECK(jsonb_typeof(private_responses)='array'),
        created_at timestamptz NOT NULL,
        FOREIGN KEY(survey_id,version_id) REFERENCES survey_version(survey_id,id) ON DELETE CASCADE,
        CHECK(payload ?& ARRAY['id','surveyId','filter']),
        CHECK(payload->>'id' IS NOT NULL AND payload->>'surveyId' IS NOT NULL AND payload->'filter'->>'versionId' IS NOT NULL),
        CHECK(payload->>'id'=id::text AND payload->>'surveyId'=survey_id::text),
        CHECK(payload->'filter'->>'versionId'=version_id::text)
    );
    CREATE INDEX survey_analysis_snapshot_survey ON survey_analysis_snapshot(survey_id,created_at);
    CREATE FUNCTION protect_survey_analysis_snapshot() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'Published analysis snapshots are immutable' USING ERRCODE='23000';
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER survey_analysis_snapshot_immutable BEFORE UPDATE ON survey_analysis_snapshot
      FOR EACH ROW EXECUTE FUNCTION protect_survey_analysis_snapshot();
    """)


def downgrade():
    op.execute(
        "DROP TABLE survey_analysis_snapshot; DROP FUNCTION protect_survey_analysis_snapshot();"
    )
