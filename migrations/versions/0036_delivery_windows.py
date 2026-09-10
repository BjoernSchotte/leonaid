"""Action-owned delivery schedules and immutable order selections."""

from alembic import op

revision = "0036_delivery_windows"
down_revision = "0035_merge_campaign_surveys"
branch_labels = None
depends_on = None

DATA_MIGRATION_REFERENCE = (
    "Existing actions remain delivery-disabled. Existing orders retain NULL "
    "window and contact snapshots; no historical delivery details are inferred."
)
BACKUP_REFERENCE = "infra/backup/README.md#schemaändernde-migrationen"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE action_delivery_configuration (
            action_id uuid PRIMARY KEY REFERENCES charity_action(id),
            enabled boolean NOT NULL DEFAULT false,
            timezone text NOT NULL DEFAULT 'Europe/Berlin',
            revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)
        );
        INSERT INTO action_delivery_configuration(action_id) SELECT id FROM charity_action;
        CREATE TABLE action_delivery_window (
            id uuid PRIMARY KEY,
            action_id uuid NOT NULL REFERENCES action_delivery_configuration(action_id),
            starts_at timestamptz NOT NULL,
            ends_at timestamptz NOT NULL,
            retired boolean NOT NULL DEFAULT false,
            UNIQUE (action_id, id),
            CHECK (starts_at < ends_at)
        );
        CREATE INDEX ix_delivery_window_action ON action_delivery_window(action_id, starts_at);
        ALTER TABLE commitment
            ADD COLUMN delivery_window_id uuid,
            ADD COLUMN delivery_window_snapshot jsonb,
            ADD COLUMN delivery_contact_snapshot jsonb,
            ADD CONSTRAINT fk_commitment_delivery_window
                FOREIGN KEY (action_id, delivery_window_id)
                REFERENCES action_delivery_window(action_id, id),
            ADD CONSTRAINT ck_commitment_delivery_window_snapshot
                CHECK ((delivery_window_id IS NULL) = (delivery_window_snapshot IS NULL));
        CREATE INDEX ix_commitment_delivery_window ON commitment(delivery_window_id)
            WHERE delivery_window_id IS NOT NULL;
        CREATE FUNCTION protect_delivery_window() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'delivery windows must be retired, not deleted' USING ERRCODE = '23514';
            END IF;
            IF (NEW.id, NEW.action_id, NEW.starts_at, NEW.ends_at) IS DISTINCT FROM
                (OLD.id, OLD.action_id, OLD.starts_at, OLD.ends_at)
                OR (OLD.retired AND NOT NEW.retired) THEN
                RAISE EXCEPTION 'delivery window identity and retirement are permanent' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER protect_delivery_window BEFORE UPDATE OR DELETE
            ON action_delivery_window FOR EACH ROW EXECUTE FUNCTION protect_delivery_window();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TRIGGER protect_delivery_window ON action_delivery_window;
        DROP FUNCTION protect_delivery_window();
        ALTER TABLE commitment
            DROP CONSTRAINT fk_commitment_delivery_window,
            DROP CONSTRAINT ck_commitment_delivery_window_snapshot,
            DROP COLUMN delivery_window_id,
            DROP COLUMN delivery_window_snapshot,
            DROP COLUMN delivery_contact_snapshot;
        DROP TABLE action_delivery_window;
        DROP TABLE action_delivery_configuration;
    """)
