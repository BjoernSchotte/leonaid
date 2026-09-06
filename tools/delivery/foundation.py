"""Real PostgreSQL upgrade, snapshot and constraint proof on disposable data."""

import os
from uuid import uuid4

import psycopg
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from leonaid.domain.commitments import DeliveryRecipientSnapshot


def main() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "0026_invoice_payment_snapshot")
    action, other, historical, window = uuid4(), uuid4(), uuid4(), uuid4()
    with psycopg.connect(os.environ["CORE_DATABASE_URL"], autocommit=True) as db:
        for identifier in (action, other):
            db.execute(
                """INSERT INTO charity_action
                (id, carrier_name, name, purpose, status, starts_on, ends_on, archive_slug)
                VALUES (%s, 'Test', 'Test', 'Test', 'draft', '2027-02-01',
                        '2027-02-28', %s)""",
                (identifier, str(identifier)),
            )
        db.execute(
            """INSERT INTO commitment
            (id, action_id, twenty_company_id, source, status,
             customer_snapshot, currency, total_minor)
            VALUES (%s, %s, %s, 'acquisition', 'confirmed', '{}', 'EUR', 0)""",
            (historical, action, uuid4()),
        )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert db.execute(
            "SELECT enabled FROM action_delivery_configuration WHERE action_id = %s",
            (action,),
        ).fetchone() == (False,)
        assert db.execute(
            """SELECT status, delivery_window_id, delivery_window_snapshot
               FROM commitment WHERE id = %s""",
            (historical,),
        ).fetchone() == ("confirmed", None, None)
        db.execute(
            """INSERT INTO delivery_window
            (id, action_id, delivery_on, starts_at, ends_at)
            VALUES (%s, %s, '2027-02-04', '08:00', '10:00')""",
            (window, action),
        )
        recipient = DeliveryRecipientSnapshot(
            "Test",
            "Testweg 1",
            "00000",
            "Teststadt",
            contact_name="Testkontakt",
            instructions="Abteilung A\n4. Stock",
        )
        db.execute(
            """UPDATE commitment SET delivery_window_id = %s,
            delivery_window_snapshot = %s, delivery_recipient_snapshot = %s
            WHERE id = %s""",
            (
                window,
                Jsonb({"windowId": str(window)}),
                Jsonb(recipient.payload()),
                historical,
            ),
        )
        row = db.execute(
            "SELECT delivery_recipient_snapshot FROM commitment WHERE id = %s",
            (historical,),
        ).fetchone()
        assert row is not None
        assert DeliveryRecipientSnapshot.from_payload(row[0]) == recipient
        for sql, params in (
            ("UPDATE delivery_window SET starts_at = '09:00' WHERE id = %s", (window,)),
            ("DELETE FROM delivery_window WHERE id = %s", (window,)),
            ("UPDATE commitment SET action_id = %s WHERE id = %s", (other, historical)),
            (
                "UPDATE commitment SET delivery_window_snapshot = NULL WHERE id = %s",
                (historical,),
            ),
        ):
            try:
                with db.transaction():
                    db.execute(sql, params)
            except psycopg.IntegrityError:
                pass
            else:
                raise AssertionError("Database allowed invalid delivery mutation")
        db.execute("UPDATE delivery_window SET retired = true WHERE id = %s", (window,))
        assert db.execute(
            "SELECT delivery_window_id FROM commitment WHERE id = %s", (historical,)
        ).fetchone() == (window,)
        command.downgrade(config, "0026_invoice_payment_snapshot")
        command.upgrade(config, "head")
        assert db.execute(
            "SELECT count(*) FROM commitment WHERE id = %s", (historical,)
        ).fetchone() == (1,)
    print(
        "delivery-foundation: PASS: migration, historical compatibility, snapshots, references, retirement, downgrade/re-upgrade"
    )


if __name__ == "__main__":
    main()
