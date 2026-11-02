"""Let retention delete the outbox jobs of sent mail.

Revision ID: 0040_mail_delivery_set_null
Revises: 0039_retention_indexes

``mail_delivery`` is the evidence of a sent mail and deduplicates re-delivery
through its own ``idempotency_key``. Its link to the outbox job kept every
sent-mail job, encrypted payload included, forever. The link now becomes NULL
when retention deletes the job; the delivery row itself stays. Invoice mail is
unaffected: ``invoice_delivery`` still keeps its outbox jobs.
"""

from alembic import op

revision = "0040_mail_delivery_set_null"
down_revision = "0039_retention_indexes"
branch_labels = None
depends_on = None

DATA_MIGRATION_REFERENCE = (
    "No rows change: the foreign key is replaced with the same columns and "
    "ON DELETE SET NULL, and outbox_event_id only becomes nullable."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

CONSTRAINT = "mail_delivery_outbox_event_id_fkey"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "mail_delivery", type_="foreignkey")
    op.alter_column("mail_delivery", "outbox_event_id", nullable=True)
    op.create_foreign_key(
        CONSTRAINT,
        "mail_delivery",
        "outbox_event",
        ["outbox_event_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Detached deliveries cannot be linked again; refuse instead of guessing.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM mail_delivery WHERE outbox_event_id IS NULL) THEN
            RAISE EXCEPTION
              'mail_delivery rows without outbox job exist; restore a backup instead';
          END IF;
        END $$
        """
    )
    op.drop_constraint(CONSTRAINT, "mail_delivery", type_="foreignkey")
    op.alter_column("mail_delivery", "outbox_event_id", nullable=False)
    op.create_foreign_key(
        CONSTRAINT,
        "mail_delivery",
        "outbox_event",
        ["outbox_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
