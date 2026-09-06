"""Real PostgreSQL upgrade, snapshot and constraint proof on disposable data."""

import os
import asyncio
from dataclasses import replace
from datetime import date, datetime, time, timezone
from uuid import UUID, uuid4

import psycopg
import asyncpg
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from leonaid.domain.commitments import DeliveryRecipientSnapshot
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.application.delivery import DeliveryService
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.delivery import DeliveryWindow
from leonaid.domain.errors import DomainInvariantError


async def repository_proof(action_id: UUID, other_id: UUID) -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=3
    )
    assert pool is not None
    try:
        repository = AsyncpgDeliveryRepository(pool)
        current = await repository.get(action_id)
        new_window = DeliveryWindow(
            uuid4(), action_id, date(2027, 2, 5), time(10), time(12)
        )
        updated = replace(current, enabled=True, windows=(*current.windows, new_window))
        results = await asyncio.gather(
            repository.save(updated), repository.save(updated), return_exceptions=True
        )
        assert sum(isinstance(result, Conflict) for result in results) == 1
        saved = await repository.get(action_id)
        assert saved.revision == current.revision + 1
        assert saved.windows[-1] == new_window
        for invalid in (
            replace(saved, timezone="UTC"),
            replace(saved, windows=(new_window,)),
        ):
            try:
                await repository.save(invalid)
            except Conflict:
                pass
            else:
                raise AssertionError("Booked schedule history was changed")
        foreign = await repository.get(other_id)
        try:
            await repository.save(
                replace(foreign, windows=(replace(new_window, action_id=other_id),))
            )
        except DomainInvariantError:
            pass
        else:
            raise AssertionError("Foreign window ID was accepted")
        assert (await repository.get(action_id)) == saved
        assert (await repository.get(other_id)) == foreign
        service = DeliveryService(repository)
        for role in (ActionRole.ACQUIRER, ActionRole.CHARITY_ADMIN, ActionRole.DRIVER):
            account = UserAccount(
                uuid4(), "test@example.invalid", "Test", AccountStatus.ACTIVE
            )
            actor = IdentityPrincipal(
                account,
                frozenset(),
                (
                    ActionMembership(
                        uuid4(),
                        action_id,
                        "Test",
                        account.id,
                        role,
                        datetime(2026, 1, 1, tzinfo=timezone.utc),
                    ),
                ),
            )
            if role == ActionRole.DRIVER:
                try:
                    await service.get(actor, action_id)
                except PermissionDenied:
                    pass
                else:
                    raise AssertionError("Driver could read delivery administration")
            else:
                assert (await service.get(actor, action_id)).action_id == action_id
            if role == ActionRole.CHARITY_ADMIN:
                assert (await service.save(actor, saved)).revision == saved.revision + 1
            else:
                try:
                    await service.save(actor, saved)
                except PermissionDenied:
                    pass
                else:
                    raise AssertionError("Non-admin could change delivery schedule")
        print(
            "delivery-repository: PASS: concurrent revisions, booked timezone/window protection, foreign ID rollback"
        )
    finally:
        await pool.close()


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
        asyncio.run(repository_proof(action, other))
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
