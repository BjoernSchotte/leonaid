"""Survey lifecycle, immutable definitions and resumable response snapshots.

Revision ID: 0027_surveys
Revises: 0026_invoice_payment_snapshot
"""

from __future__ import annotations

from alembic import op

revision = "0027_surveys"
down_revision = "0026_invoice_payment_snapshot"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = (
    "Additive survey tables; no existing product data is transformed."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE survey (
        id uuid PRIMARY KEY,
        title text NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 240),
        status text NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft','active','ended','archived','deleted')),
        revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
        owner_user_id uuid NOT NULL REFERENCES user_account(id),
        action_id uuid REFERENCES charity_action(id),
        access_mode text NOT NULL DEFAULT 'anonymous'
            CHECK (access_mode IN ('anonymous','invitation')),
        inactivity_timeout_seconds integer
            CHECK (inactivity_timeout_seconds BETWEEN 1 AND 604800),
        published_version_id uuid,
        ends_at timestamptz,
        deleted_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
    );
    CREATE TABLE survey_grant (
        survey_id uuid NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
        capability text NOT NULL CHECK (capability IN (
            'design','publish','archive','view_aggregates','read_responses',
            'export_raw','export_reports','manage_invitations','delete')),
        PRIMARY KEY (survey_id, user_id, capability)
    );
    CREATE TABLE survey_draft (
        survey_id uuid PRIMARY KEY REFERENCES survey(id) ON DELETE CASCADE,
        revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
        definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE survey_version (
        id uuid PRIMARY KEY,
        survey_id uuid NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
        number integer NOT NULL CHECK (number > 0),
        definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
        schema_hash text NOT NULL,
        renderer_version text NOT NULL,
        capability_profile text NOT NULL,
        published_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (survey_id, number),
        UNIQUE (survey_id, id)
    );
    ALTER TABLE survey ADD CONSTRAINT survey_published_version_fk
        FOREIGN KEY (id, published_version_id)
        REFERENCES survey_version(survey_id, id) DEFERRABLE INITIALLY DEFERRED;
    CREATE FUNCTION protect_survey_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'published survey versions are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END;
    $$;
    CREATE TRIGGER survey_version_immutable BEFORE UPDATE ON survey_version
        FOR EACH ROW EXECUTE FUNCTION protect_survey_version();
    CREATE TABLE survey_participation (
        id uuid PRIMARY KEY,
        survey_id uuid NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
        version_id uuid NOT NULL,
        resume_digest text NOT NULL UNIQUE,
        status text NOT NULL DEFAULT 'in_progress'
            CHECK (status IN ('in_progress','partial','completed')),
        revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
        answers jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(answers) = 'object'),
        current_page text,
        inactivity_timeout_seconds integer NOT NULL
            CHECK (inactivity_timeout_seconds BETWEEN 1 AND 604800),
        last_answer_changed_at timestamptz,
        completed_at timestamptz,
        expires_at timestamptz,
        revoked_at timestamptz,
        is_test boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (survey_id, version_id)
            REFERENCES survey_version(survey_id, id) ON DELETE CASCADE,
        CHECK ((status = 'completed') = (completed_at IS NOT NULL))
    );
    CREATE INDEX survey_participation_timeout ON survey_participation
        (last_answer_changed_at) WHERE status = 'in_progress';
    CREATE INDEX survey_participation_analysis ON survey_participation
        (survey_id, version_id, status);
    CREATE TABLE survey_operation (
        survey_id uuid NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
        scope text NOT NULL,
        operation_id text NOT NULL CHECK (length(operation_id) BETWEEN 1 AND 128),
        request_hash text NOT NULL,
        response jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (survey_id, scope, operation_id)
    );
    CREATE TABLE survey_settings (
        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
        inactivity_timeout_seconds integer NOT NULL DEFAULT 1800
            CHECK (inactivity_timeout_seconds BETWEEN 1 AND 604800),
        revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)
    );
    INSERT INTO survey_settings(singleton) VALUES (true);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE survey_settings;
    DROP TABLE survey_operation;
    DROP TABLE survey_participation;
    ALTER TABLE survey DROP CONSTRAINT survey_published_version_fk;
    DROP TABLE survey_version;
    DROP FUNCTION protect_survey_version();
    DROP TABLE survey_draft;
    DROP TABLE survey_grant;
    DROP TABLE survey;
    """)
