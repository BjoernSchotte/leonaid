"""Durable timeout settings and worker-independent response classification."""

from alembic import op

revision = "0028_survey_timeouts"
down_revision = "0027_surveys"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = (
    "Additive settings operations and effective-status view; no answer data changes."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE survey_settings_operation (
        actor_id uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
        operation_id text NOT NULL CHECK (length(operation_id) BETWEEN 1 AND 128),
        request_hash text NOT NULL,
        response jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (actor_id, operation_id)
    );
    CREATE VIEW survey_participation_effective AS
        SELECT p.*, CASE
            WHEN status='in_progress' AND
                COALESCE(last_answer_changed_at,created_at)
                    + make_interval(secs => inactivity_timeout_seconds)
                    <= statement_timestamp()
            THEN 'partial' ELSE status END AS effective_status
        FROM survey_participation p;
    CREATE INDEX survey_participation_deadline ON survey_participation
        ((COALESCE(last_answer_changed_at,created_at)))
        WHERE status='in_progress';
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX survey_participation_deadline;
    DROP VIEW survey_participation_effective;
    DROP TABLE survey_settings_operation;
    """)
