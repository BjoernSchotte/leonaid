"""Real PostgreSQL migration, authorization and schedule lifecycle proof."""

import asyncio
import os
from dataclasses import replace
from datetime import date, datetime, time, timezone
from uuid import uuid4
from decimal import Decimal

import asyncpg
import psycopg
from alembic import command
from alembic.config import Config

from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.adapters.postgres.delivery import (
    AsyncpgDeliveryRepository,
    lock_configuration,
)
from leonaid.application.delivery import DeliveryService
from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.domain.action_templates import ActionTemplateKey
from leonaid.domain.actions import (
    ActionGoal,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
)
from leonaid.domain.delivery import DeliveryWindow
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)


async def prove() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    try:
        actions = AsyncpgCharityActionRepository(pool)
        repo = AsyncpgDeliveryRepository(pool)
        admin_id = uuid4()
        now = datetime.now(timezone.utc)
        await pool.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,'admin@example.invalid','Test','active')",
            admin_id,
        )

        async def create(key: ActionTemplateKey) -> CharityAction:
            template = await actions.get_template(key, 1)
            assert template is not None
            identifier = uuid4()
            action = CharityAction(
                identifier,
                "Test",
                "Test",
                "Test",
                CharityActionStatus.DRAFT,
                date(2037, 12, 1),
                date(2037, 12, 31),
                f"proof-{identifier}",
                template.capabilities,
                (Beneficiary(uuid4(), identifier, "Test", "Test", 0),),
                ActionGoal(None, Decimal(0), None),
            )
            return await actions.create(
                action,
                responsible_admin_user_id=admin_id,
                request_id="delivery-proof",
                occurred_at=now,
                configuration=template.configure(identifier),
            )

        action = await create(ActionTemplateKey.KRAPFENTAXI)
        other = await create(ActionTemplateKey.KRAPFENTAXI)
        blank = await create(ActionTemplateKey.BLANK)
        initial = await repo.get(action.id)
        assert initial.enabled and not initial.windows
        assert not (await repo.get(blank.id)).enabled
        try:
            await actions.transition(
                action.transition_to(CharityActionStatus.SCHEDULED),
                previous_status=action.status,
                actor_user_id=admin_id,
                request_id="delivery-proof",
                occurred_at=now,
            )
        except Conflict as error:
            assert error.code == "delivery_windows_required"
        else:
            raise AssertionError("Action activated without windows")
        assert (await actions.get(action.id)).status is CharityActionStatus.DRAFT
        windows = tuple(
            DeliveryWindow(
                uuid4(), action.id, date(2037, 12, day), time(hour), time(hour + 2)
            )
            for day in (4, 5)
            for hour in (8, 10, 12)
        )
        planned = replace(initial, windows=windows)
        results = await asyncio.gather(
            repo.save(planned), repo.save(planned), return_exceptions=True
        )
        assert sum(isinstance(value, Conflict) for value in results) == 1
        saved = await repo.get(action.id)
        assert saved.revision == 2 and saved.windows == windows
        assert await pool.fetchval(
            "SELECT starts_at FROM action_delivery_window WHERE id = $1", windows[0].id
        ) == datetime(2037, 12, 4, 7, tzinfo=timezone.utc)
        for invalid in (
            replace(saved, windows=windows[1:]),
            replace(
                saved, windows=(replace(windows[0], starts_at=time(7)), *windows[1:])
            ),
            replace(saved, timezone="UTC"),
        ):
            try:
                await repo.save(invalid)
            except Conflict:
                pass
            else:
                raise AssertionError("Window identity changed")
        try:
            await repo.save(replace(await repo.get(blank.id), enabled=True))
        except DomainInvariantError as error:
            assert error.code == "delivery_not_supported"
        else:
            raise AssertionError("Non-Krapfentaxi delivery accepted")
        try:
            await repo.save(
                replace(
                    await repo.get(other.id),
                    windows=(replace(windows[0], action_id=other.id),),
                )
            )
        except DomainInvariantError as error:
            assert error.code == "delivery_window_action_mismatch"
        else:
            raise AssertionError("Foreign ID accepted")
        assert (await repo.get(other.id)).revision == 1
        active = await actions.transition(
            action.transition_to(CharityActionStatus.SCHEDULED),
            previous_status=action.status,
            actor_user_id=admin_id,
            request_id="delivery-proof",
            occurred_at=now,
        )
        try:
            await actions.update_details(
                replace(active, starts_on=date(2037, 12, 5)),
                actor_user_id=admin_id,
                request_id="delivery-proof",
                occurred_at=now,
            )
        except DomainInvariantError:
            pass
        else:
            raise AssertionError("Action period cut off active delivery day")
        assert (await actions.get(action.id)).starts_on == date(2037, 12, 1)
        # Copying the template configuration cannot copy live delivery dates.
        source_configuration = await actions.get_configuration(action.id)
        assert source_configuration is not None
        copied_id = uuid4()
        copied_action = replace(
            action,
            id=copied_id,
            archive_slug=f"proof-{copied_id}",
            beneficiaries=(Beneficiary(uuid4(), copied_id, "Test", "Test", 0),),
        )
        await actions.create(
            copied_action,
            responsible_admin_user_id=admin_id,
            request_id="delivery-proof",
            occurred_at=now,
            configuration=source_configuration.copy_for(
                copied_id, source_action_id=action.id, capabilities=action.capabilities
            ),
        )
        assert not (await repo.get(copied_id)).windows

        service = DeliveryService(repo)
        for role in (ActionRole.CHARITY_ADMIN, ActionRole.ACQUIRER, ActionRole.DRIVER):
            user = UserAccount(
                admin_id, "admin@example.invalid", "Test", AccountStatus.ACTIVE
            )
            actor = IdentityPrincipal(
                user,
                frozenset(),
                (ActionMembership(uuid4(), action.id, "Test", user.id, role, now),),
            )
            if role is ActionRole.CHARITY_ADMIN:
                assert await service.get(actor, action.id) == saved
            else:
                for operation in (
                    service.get(actor, action.id),
                    service.save(actor, saved),
                ):
                    try:
                        await operation
                    except PermissionDenied:
                        pass
                    else:
                        raise AssertionError("Unauthorized configuration access")

        from tools.delivery.http_configuration import prove_http_configuration

        await prove_http_configuration(service, other.id, admin_id)

        # A waiting SERIALIZABLE booking must not continue with a stale schedule.
        async with pool.acquire() as booking, pool.acquire() as editing:
            async with editing.transaction():
                await editing.fetchval(
                    "SELECT id FROM charity_action WHERE id = $1 FOR UPDATE", action.id
                )
                transaction = booking.transaction(isolation="serializable")
                await transaction.start()
                await booking.fetchval(
                    "SELECT revision FROM action_delivery_configuration WHERE action_id = $1",
                    action.id,
                )
                waiting = asyncio.create_task(
                    booking.fetchval(
                        "SELECT id FROM charity_action WHERE id = $1 FOR UPDATE",
                        action.id,
                    )
                )
                await editing.execute(
                    "UPDATE action_delivery_configuration SET revision=revision+1 WHERE action_id=$1",
                    action.id,
                )
            await waiting
            try:
                await lock_configuration(booking, action.id)
            except asyncpg.SerializationError:
                pass
            else:
                raise AssertionError(
                    "Stale booking transaction survived schedule revision"
                )
            finally:
                await transaction.rollback()

        from tools.delivery.orders import prove_orders

        await prove_orders(pool, action.id, admin_id)
        saved = await repo.get(action.id)
        retired = await repo.save(
            replace(saved, windows=tuple(replace(w, retired=True) for w in windows))
        )
        try:
            await repo.save(replace(retired, windows=windows))
        except Conflict:
            pass
        else:
            raise AssertionError("Retired window reactivated")
        for sql in (
            "DELETE FROM action_delivery_window WHERE id=$1",
            "UPDATE action_delivery_window SET retired=false WHERE id=$1",
            "UPDATE action_delivery_window SET starts_at=starts_at - interval '1 hour' WHERE id=$1",
        ):
            try:
                await pool.execute(sql, windows[0].id)
            except asyncpg.CheckViolationError:
                pass
            else:
                raise AssertionError("Database allowed immutable window mutation")
        print(
            "KLF-020 PASS: new/blank/copied actions, UTC, six windows, revision race, authorization, foreign IDs, activation, period rollback, retirement, stale booking serialization"
        )
    finally:
        await pool.close()


def main() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "0035_merge_campaign_surveys")
    historical_action = uuid4()
    with psycopg.connect(os.environ["CORE_DATABASE_URL"], autocommit=True) as db:
        db.execute(
            "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug) VALUES (%s,'Test','Historical','Test','draft','2037-12-01','2037-12-31',%s)",
            (historical_action, f"historical-{historical_action}"),
        )
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with psycopg.connect(os.environ["CORE_DATABASE_URL"]) as db:
        assert db.execute(
            "SELECT enabled FROM action_delivery_configuration WHERE action_id=%s",
            (historical_action,),
        ).fetchone() == (False,)
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("0036_delivery_windows",)
        ]
    asyncio.run(prove())


if __name__ == "__main__":
    main()
