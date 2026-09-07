"""Actual multi-alias migration and legacy repository/order compatibility."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import psycopg

from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.errors import Conflict
from leonaid.application.actions import CharityActionService, PublicActionAvailability
from leonaid.domain.actions import CharityActionStatus, PublicActionAlias

PREVIOUS = "0027_campaign_alias_namespaces"
CURRENT = "0028_multiple_campaign_aliases"
ACTION = UUID("20000000-0000-4000-8000-000000000001")
ACTOR = UUID("10000000-0000-4000-8000-000000000001")


def command(*args: str, denied: bool = False) -> None:
    result = subprocess.run(
        [sys.executable, *args], capture_output=True, timeout=120, check=False
    )
    if denied:
        assert result.returncode != 0
        assert (
            b"campaign alias downgrade requires extended alias resolution"
            in result.stderr
        )
    else:
        assert result.returncode == 0, "isolated multi-alias fixture command failed"


async def repositories() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    try:
        repo = AsyncpgCharityActionRepository(pool)
        state = await repo.get_management(ACTION)
        assert state is not None and state.public_alias == PublicActionAlias(
            "krapfentaxi"
        )
        assert await repo.get_by_public_alias(PublicActionAlias("extra-one")) is None
        assert await repo.get_alias_target(PublicActionAlias("extra-one")) == ACTION
        now = datetime.now(timezone.utc)
        service = CharityActionService(repo)
        redirect = await service.resolve_public_alias("extra-one", evaluated_at=now)
        assert redirect.redirect_path == "/campaigns/krapfentaxi-2026/"
        assert redirect.canonical_path == redirect.redirect_path
        assert not redirect.submissions_allowed
        assert not redirect.offerings and redirect.order_form is None
        assert redirect.order_alias is None
        primary = await service.resolve_public_alias("krapfentaxi", evaluated_at=now)
        assert primary.redirect_path is None and primary.submissions_allowed
        for alias, evaluated_at in (
            ("extra-two", now),
            ("unknown-alias", now),
            ("extra-one", now - timedelta(days=2)),
            ("extra-one", now + timedelta(days=2)),
        ):
            inactive = await service.resolve_public_alias(
                alias, evaluated_at=evaluated_at
            )
            assert inactive.availability is PublicActionAvailability.INACTIVE
            assert inactive.action is None and inactive.redirect_path is None
            assert inactive.canonical_path == f"/{alias}"
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE public_action_alias SET enabled=false WHERE alias='extra-one'"
            )
        disabled = await service.resolve_public_alias("extra-one", evaluated_at=now)
        assert disabled.action is None and disabled.redirect_path is None
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE public_action_alias SET enabled=true WHERE alias='extra-one'"
            )
        assert (
            await service.resolve_public_alias("extra-one", evaluated_at=now)
        ).redirect_path == redirect.redirect_path
        async with pool.acquire() as db:
            # Additional redirect rows must not multiply or randomly replace
            # the legacy primary-alias join used by real order processing.
            async with db.transaction():
                context = await AsyncpgPublicOrderRepository._context(
                    db, action_id=ACTION, public_alias="krapfentaxi", evaluated_at=now
                )
                assert context.action_id == ACTION
            try:
                async with db.transaction():
                    await AsyncpgPublicOrderRepository._context(
                        db, action_id=ACTION, public_alias="extra-one", evaluated_at=now
                    )
            except Conflict:
                pass
            else:
                raise AssertionError("redirect alias gained order authority")
            before = await db.fetch(
                "SELECT * FROM public_action_alias WHERE NOT is_primary ORDER BY alias"
            )
        # Legacy publication update may replace only the primary alias.
        updated = await repo.replace_publication(
            state.action,
            public_alias=PublicActionAlias("taxi-primary"),
            allowed_previous_target_id=None,
            actor_user_id=ACTOR,
            request_id="alias-persistence-primary",
            occurred_at=now,
        )
        assert updated.public_alias == PublicActionAlias("taxi-primary")
        async with pool.acquire() as db:
            assert (
                await db.fetch(
                    "SELECT * FROM public_action_alias WHERE NOT is_primary ORDER BY alias"
                )
                == before
            )
        # Legacy primary controls cannot silently consume even this action's
        # additional alias. The revision bump must roll back with the conflict.
        try:
            await repo.replace_publication(
                updated.action,
                public_alias=PublicActionAlias("extra-one"),
                allowed_previous_target_id=None,
                actor_user_id=ACTOR,
                request_id="alias-persistence-denied",
                occurred_at=now,
            )
        except Conflict:
            pass
        else:
            raise AssertionError("legacy mutation consumed redirect alias")
        assert await repo.get_management(ACTION) == updated

        # Concurrent claims share the existing global alias primary key.
        async def claim() -> bool:
            try:
                async with pool.acquire() as db:
                    await db.execute(
                        "INSERT INTO public_action_alias(alias,action_id,is_primary) VALUES ('race-alias',$1,false)",
                        ACTION,
                    )
                return True
            except asyncpg.UniqueViolationError:
                return False

        assert sorted(await asyncio.gather(claim(), claim())) == [False, True]
        # Existing completion releases all addresses; retain legacy audit field
        # plus a deterministic inventory of additional released names.
        await repo.transition(
            updated.action.transition_to(CharityActionStatus.COMPLETED),
            previous_status=updated.action.status,
            actor_user_id=ACTOR,
            request_id="alias-persistence-complete",
            occurred_at=now,
        )
        async with pool.acquire() as db:
            assert (
                await db.fetchval(
                    "SELECT count(*) FROM public_action_alias WHERE action_id=$1",
                    ACTION,
                )
                == 0
            )
            payload = await db.fetchval(
                "SELECT payload FROM audit_event WHERE request_id='alias-persistence-complete'"
            )
            data = json.loads(payload)
            assert data["releasedPublicAlias"] == "taxi-primary"
            assert data["releasedRedirectAliases"] == [
                "extra-one",
                "extra-two",
                "race-alias",
            ]
    finally:
        await pool.close()


def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    command("-m", "alembic", "upgrade", PREVIOUS)
    command("tools/seed/golden.py", "seed-core", "tests/fixtures/golden/v1")
    with psycopg.connect(os.environ["CORE_DATABASE_URL"], autocommit=True) as db:
        now = datetime.now(timezone.utc)
        db.execute(
            "UPDATE charity_action SET publication_starts_at=%s, publication_ends_at=%s WHERE id=%s",
            (now - timedelta(days=1), now + timedelta(days=1), ACTION),
        )

        def legacy_snapshot() -> tuple[object, object]:
            return (
                db.execute(
                    "SELECT alias,action_id,switched_at FROM public_action_alias ORDER BY alias"
                ).fetchall(),
                db.execute("SELECT * FROM charity_action ORDER BY id").fetchall(),
            )

        before = legacy_snapshot()
        command("-m", "alembic", "upgrade", CURRENT)
        assert legacy_snapshot() == before
        assert db.execute(
            "SELECT count(*) FROM public_action_alias WHERE NOT is_primary OR NOT enabled OR revision<>1 OR id IS NULL"
        ).fetchone() == (0,)
        command("-m", "alembic", "downgrade", PREVIOUS)
        assert legacy_snapshot() == before
        command("-m", "alembic", "upgrade", CURRENT)
        # At most one primary per action, but multiple redirects including a
        # disabled address are valid and still reserve their global names.
        try:
            db.execute(
                "INSERT INTO public_action_alias(alias,action_id) VALUES ('second-primary',%s)",
                (ACTION,),
            )
        except psycopg.errors.UniqueViolation:
            pass
        else:
            raise AssertionError("multiple primary aliases accepted")
        db.execute(
            "INSERT INTO public_action_alias(alias,action_id,is_primary,enabled) VALUES ('extra-one',%s,false,true),('extra-two',%s,false,false)",
            (ACTION, ACTION),
        )
        extended = db.execute(
            "SELECT * FROM public_action_alias ORDER BY alias"
        ).fetchall()
        command("-m", "alembic", "downgrade", PREVIOUS, denied=True)
        assert (
            db.execute("SELECT * FROM public_action_alias ORDER BY alias").fetchall()
            == extended
        )
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            CURRENT,
        )
    # Migration compatibility above intentionally exercises the historical
    # revision; current repositories require the current schema afterwards.
    command("-m", "alembic", "upgrade", "head")
    asyncio.run(repositories())
    print(
        "alias-persistence: migrated legacy aliases/windows unchanged; multiple redirects, one primary, fail-closed downgrade, legacy publication and order lookup, concurrent unique claim and complete release audit passed"
    )


if __name__ == "__main__":
    main()
