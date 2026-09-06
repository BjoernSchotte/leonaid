"""Add action-owned delivery configuration and order window snapshots."""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_delivery_windows"
down_revision: str | None = "0026_invoice_payment_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_MIGRATION_REFERENCE = (
    "Existing actions remain delivery-disabled. Historical orders retain NULL "
    "window selections; no delivery date or contact is inferred."
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
        INSERT INTO action_delivery_configuration (action_id)
        SELECT id FROM charity_action;

        CREATE TABLE delivery_window (
            id uuid PRIMARY KEY,
            action_id uuid NOT NULL REFERENCES action_delivery_configuration(action_id),
            delivery_on date NOT NULL,
            starts_at time NOT NULL,
            ends_at time NOT NULL,
            retired boolean NOT NULL DEFAULT false,
            UNIQUE (action_id, id),
            CHECK (ends_at > starts_at),
            CHECK (extract(second FROM starts_at) = 0),
            CHECK (extract(second FROM ends_at) = 0)
        );
        CREATE UNIQUE INDEX uq_delivery_window_active_range
        ON delivery_window(action_id, delivery_on, starts_at, ends_at)
        WHERE NOT retired;

        ALTER TABLE commitment
            ADD COLUMN delivery_window_id uuid,
            ADD COLUMN delivery_window_snapshot jsonb,
            ADD CONSTRAINT fk_commitment_delivery_window
                FOREIGN KEY (action_id, delivery_window_id)
                REFERENCES delivery_window(action_id, id),
            ADD CONSTRAINT ck_commitment_delivery_window_snapshot
                CHECK ((delivery_window_id IS NULL)
                    = (delivery_window_snapshot IS NULL));
        CREATE INDEX ix_commitment_delivery_window
            ON commitment(delivery_window_id) WHERE delivery_window_id IS NOT NULL;

        CREATE FUNCTION protect_booked_delivery_window() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.id, NEW.action_id, NEW.delivery_on, NEW.starts_at, NEW.ends_at)
                IS DISTINCT FROM
                (OLD.id, OLD.action_id, OLD.delivery_on, OLD.starts_at, OLD.ends_at)
                AND EXISTS (SELECT 1 FROM commitment
                            WHERE delivery_window_id = OLD.id) THEN
                RAISE EXCEPTION 'booked delivery windows cannot be rescheduled'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER protect_booked_delivery_window
            BEFORE UPDATE ON delivery_window FOR EACH ROW
            EXECUTE FUNCTION protect_booked_delivery_window();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TRIGGER protect_booked_delivery_window ON delivery_window;
        DROP FUNCTION protect_booked_delivery_window();
        ALTER TABLE commitment
            DROP CONSTRAINT fk_commitment_delivery_window,
            DROP CONSTRAINT ck_commitment_delivery_window_snapshot,
            DROP COLUMN delivery_window_id,
            DROP COLUMN delivery_window_snapshot;
        DROP TABLE delivery_window;
        DROP TABLE action_delivery_configuration;
    """)
