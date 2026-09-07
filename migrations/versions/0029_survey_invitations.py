"""Separate attributable survey invitations and encrypted mail delivery.

Revision ID: 0029_survey_invitations
Revises: 0028_survey_timeouts
"""

from alembic import op

revision = "0029_survey_invitations"
down_revision = "0028_survey_timeouts"
branch_labels = None
depends_on = None
DATA_MIGRATION_REFERENCE = (
    "Additive invitation relation; anonymous response rows remain unassociated."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("""
    ALTER TABLE survey_participation ADD CONSTRAINT survey_participation_survey_id_unique UNIQUE(survey_id,id);
    CREATE TABLE survey_invitation (
        id uuid PRIMARY KEY,
        survey_id uuid NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
        recipient_email text NOT NULL,
        recipient_name text NOT NULL DEFAULT '',
        token_digest text NOT NULL UNIQUE,
        participation_id uuid UNIQUE,
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        redeemed_at timestamptz,
        sent_at timestamptz,
        mail_payload text,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY(survey_id,participation_id) REFERENCES survey_participation(survey_id,id) ON DELETE CASCADE,
        CHECK ((participation_id IS NULL) = (redeemed_at IS NULL)),
        CHECK (length(recipient_email) BETWEEN 3 AND 254),
        CHECK (length(recipient_name) <= 160)
    );
    CREATE INDEX survey_invitation_survey ON survey_invitation(survey_id,created_at);
    """)


def downgrade() -> None:
    op.execute(
        "DROP TABLE survey_invitation; ALTER TABLE survey_participation DROP CONSTRAINT survey_participation_survey_id_unique;"
    )
