"""Buyer mails: an order number for every order and the action's mail switches.

Revision ID: 0062_buyer_mails
Revises: 0061_delivery_geo_regeocode

specs/mails-documents-donations-push §5.1 and §6.1.

`commitment.public_reference` was reserved for orders of the public form
(`ck_commitment_public_reference`). Every order gets a number now: the check
goes, older internal orders get theirs by the rule the application uses for
every new order (`LA-` plus eight characters a buyer can read out on the
phone, derived from the order id, `domain.commitments.order_number`) and the
column becomes NOT NULL. Orders of the public form keep the long number they
have (`LA-` plus the order id in hex): buyers hold it in their mails. The
unique constraint of 0011 stays.

`action_buyer_mail_configuration` is the settings row with the switches for
mails to buyers, one per action, all off. It is created for every existing
action; the application creates it with a new action. The row goes with its
action.

Two indexes serve the mail status of one order: the jobs of an order
(`outbox_event` by aggregate) and the ledger rows by key range
(`mail_delivery`, in byte order, which the database collation does not give).

The downgrade restores the old rule: internal orders lose their number (it
can be derived from the id again), the settings are dropped. An older
application cannot read orders written after this migration: it refuses an
internal order with a number and a public order with a short one. Roll the
database back before the application (infra/upgrade/README.md).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0062_buyer_mails"
down_revision: str | None = "0061_delivery_geo_regeocode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
DATA_MIGRATION_REFERENCE = (
    "Orders without an order number get a short one derived from their id; "
    "no existing number changes. Every action gets a buyer-mail settings row "
    "with all switches off. Two indexes are added."
)
BACKUP_REFERENCE = "infra/backup/README.md#schema-changing-migrations"

# `domain.commitments.order_number` in SQL: "LA-" plus eight characters of an
# alphabet without 0/O and 1/I/L, taken from sha256("<order id>:<attempt>").
# A number that an order already has is skipped by the next attempt, so the
# result does not depend on anything but the stored orders and their order.
BACKFILL = """
DO $backfill$
DECLARE
    item record;
    candidate text;
    attempt integer;
    digest bytea;
    alphabet CONSTANT text := '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
BEGIN
    FOR item IN
        SELECT id FROM commitment
        WHERE public_reference IS NULL
        ORDER BY created_at, id
    LOOP
        attempt := 0;
        LOOP
            digest := sha256(convert_to(item.id::text || ':' || attempt, 'UTF8'));
            candidate := 'LA-';
            FOR place IN 0..7 LOOP
                candidate := candidate
                    || substr(alphabet, mod(get_byte(digest, place), 31) + 1, 1);
            END LOOP;
            EXIT WHEN NOT EXISTS (
                SELECT 1 FROM commitment WHERE public_reference = candidate
            );
            attempt := attempt + 1;
        END LOOP;
        UPDATE commitment SET public_reference = candidate WHERE id = item.id;
    END LOOP;
END
$backfill$
"""

OLD_REFERENCE_RULE = (
    "(source = 'public_form' AND public_reference IS NOT NULL) "
    "OR (source <> 'public_form' AND public_reference IS NULL)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_commitment_public_reference", "commitment", type_="check")
    op.execute(BACKFILL)
    op.execute("ALTER TABLE commitment ALTER COLUMN public_reference SET NOT NULL")
    op.execute(
        """
        CREATE TABLE action_buyer_mail_configuration (
            action_id uuid PRIMARY KEY
                REFERENCES charity_action (id) ON DELETE CASCADE,
            internal_order_mails boolean NOT NULL DEFAULT false,
            delivery_day_mail boolean NOT NULL DEFAULT false,
            delivery_day_send_time time NOT NULL DEFAULT '07:00',
            revision integer NOT NULL DEFAULT 1,
            CONSTRAINT ck_action_buyer_mail_send_time CHECK (
                delivery_day_send_time BETWEEN '05:00' AND '12:00'
            ),
            CONSTRAINT ck_action_buyer_mail_revision CHECK (revision >= 1)
        )
        """
    )
    op.execute(
        """
        INSERT INTO action_buyer_mail_configuration (action_id)
        SELECT id FROM charity_action
        """
    )
    op.execute(
        "CREATE INDEX ix_outbox_event_aggregate "
        "ON outbox_event (aggregate_type, aggregate_id)"
    )
    op.execute(
        "CREATE INDEX ix_mail_delivery_key_c "
        'ON mail_delivery (idempotency_key COLLATE "C")'
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP INDEX ix_mail_delivery_key_c")
    op.execute("DROP INDEX ix_outbox_event_aggregate")
    op.execute("DROP TABLE action_buyer_mail_configuration")
    op.execute("ALTER TABLE commitment ALTER COLUMN public_reference DROP NOT NULL")
    op.execute(
        "UPDATE commitment SET public_reference = NULL WHERE source <> 'public_form'"
    )
    op.create_check_constraint(
        "ck_commitment_public_reference", "commitment", OLD_REFERENCE_RULE
    )
