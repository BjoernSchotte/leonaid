"""Real database redirect mutation, authority and idempotency contract."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.campaign_aliases import AsyncpgCampaignAliasRepository
from leonaid.application.campaign_aliases import (
    CampaignAliasCommand,
    CampaignAliasResult,
)
from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from tools.emdash_spike.alias_persistence_proof import command

A = UUID("20000000-0000-4000-8000-000000000001")
B = UUID("20000000-0000-4000-8000-000000000003")
SYSTEM = UUID("10000000-0000-4000-8000-000000000001")
CHARITY = UUID("10000000-0000-4000-8000-000000000002")
ACQUIRER = UUID("10000000-0000-4000-8000-000000000004")


async def proof() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=5
    )
    assert pool is not None
    repo = AsyncpgCampaignAliasRepository(pool)

    async def mutate(
        cmd: CampaignAliasCommand, actor: UUID = CHARITY
    ) -> CampaignAliasResult:
        return await repo.mutate(actor, cmd, request_id="synthetic-alias-command")

    async def snapshot() -> list[list[asyncpg.Record]]:
        async with pool.acquire() as db:
            return [
                await db.fetch(f"SELECT * FROM {table} ORDER BY {key}")
                for table, key in (
                    ("public_action_alias", "id"),
                    ("command_receipt", "idempotency_key"),
                    ("audit_event", "id"),
                )
            ]

    async def denied(
        cmd: CampaignAliasCommand, actor: UUID, error: type[Exception]
    ) -> None:
        before = await snapshot()
        try:
            await mutate(cmd, actor)
        except error:
            pass
        else:
            raise AssertionError("unauthorized/conflicting alias command succeeded")
        assert await snapshot() == before

    try:
        # Fixture explicitly grants only A: moving aliases requires both scopes.
        async with pool.acquire() as db:
            await db.execute(
                "DELETE FROM action_membership WHERE user_id=$1 AND action_id=$2",
                CHARITY,
                B,
            )
            assert await db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM action_membership WHERE user_id=$1 AND action_id=$2 AND role='charity_admin')",
                CHARITY,
                A,
            )
        create = CampaignAliasCommand(
            uuid4(), uuid4(), A, A, "create", 0, "charity-extra"
        )
        await denied(create, ACQUIRER, PermissionDenied)
        result = await mutate(create)
        assert result.revision == 1 and not result.removed and result.enabled
        before = await snapshot()
        assert await mutate(create) == result
        assert await snapshot() == before
        await denied(replace(create, alias="changed-command"), CHARITY, Conflict)
        await denied(
            replace(create, command_id=uuid4(), alias_id=uuid4()), SYSTEM, Conflict
        )
        update = replace(
            create, command_id=uuid4(), operation="update", revision=1, enabled=False
        )
        disabled = await mutate(update)
        assert disabled.revision == 2 and not disabled.enabled
        await denied(replace(update, command_id=uuid4()), CHARITY, Conflict)
        move = replace(
            update, command_id=uuid4(), revision=2, target_action_id=B, enabled=True
        )
        await denied(move, CHARITY, PermissionDenied)
        moved = await mutate(move, SYSTEM)
        assert moved.action_id == B and moved.revision == 3
        assert await mutate(move, SYSTEM) == moved
        await denied(
            replace(update, command_id=uuid4(), revision=3), CHARITY, ResourceNotFound
        )
        # The original create receipt cannot disclose current moved content to
        # a former owner who lacks authority over its current action.
        await denied(create, CHARITY, PermissionDenied)
        remove = CampaignAliasCommand(uuid4(), create.alias_id, B, B, "remove", 3)
        deleted = await mutate(remove, SYSTEM)
        assert deleted.removed
        before = await snapshot()
        assert await mutate(remove, SYSTEM) == deleted
        assert await snapshot() == before
        # Real membership withdrawal denies even a previously authorized actor.
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE action_membership SET active_until=clock_timestamp() WHERE user_id=$1 AND action_id=$2",
                CHARITY,
                A,
            )
        await denied(
            replace(
                create, command_id=uuid4(), alias_id=uuid4(), alias="after-revocation"
            ),
            CHARITY,
            PermissionDenied,
        )
        race = replace(
            create, command_id=uuid4(), alias_id=uuid4(), alias="simultaneous"
        )
        outcomes = await asyncio.gather(
            mutate(race, SYSTEM),
            mutate(replace(race, command_id=uuid4(), alias_id=uuid4()), SYSTEM),
            return_exceptions=True,
        )
        assert sum(isinstance(item, Conflict) for item in outcomes) == 1
        assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
        # A real trigger failure after alias mutation rolls back alias, audit
        # and receipt; retrying the identical command succeeds after repair.
        async with pool.acquire() as db:
            await db.execute(
                "CREATE FUNCTION reject_alias_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.event_type='campaign_alias.changed' THEN RAISE EXCEPTION 'synthetic audit failure'; END IF; RETURN NEW; END $$"
            )
            await db.execute(
                "CREATE TRIGGER reject_alias_audit BEFORE INSERT ON audit_event FOR EACH ROW EXECUTE FUNCTION reject_alias_audit()"
            )
        retry = replace(
            create, command_id=uuid4(), alias_id=uuid4(), alias="atomic-retry"
        )
        await denied(retry, SYSTEM, asyncpg.RaiseError)
        async with pool.acquire() as db:
            await db.execute("DROP TRIGGER reject_alias_audit ON audit_event")
            await db.execute("DROP FUNCTION reject_alias_audit()")
        assert (await mutate(retry, SYSTEM)).alias == "atomic-retry"
        async with pool.acquire() as db:
            audits = [
                json.loads(row["payload"])
                for row in await db.fetch(
                    "SELECT payload FROM audit_event WHERE entity_id=$1 AND event_type='campaign_alias.changed' ORDER BY occurred_at",
                    create.alias_id,
                )
            ]
            assert len(audits) == 4
            assert audits[2]["previousTarget"] == str(A) and audits[2][
                "newTarget"
            ] == str(B)
            assert audits[3]["newTarget"] is None
            primary = await db.fetchrow(
                "SELECT id,revision FROM public_action_alias WHERE action_id=$1 AND is_primary",
                A,
            )
        assert primary is not None
        await denied(
            CampaignAliasCommand(
                uuid4(), primary["id"], A, A, "remove", primary["revision"]
            ),
            SYSTEM,
            Conflict,
        )
    finally:
        await pool.close()
    print(
        "alias-commands: actual Core authority, cross-action denial/move, revision and name conflicts, disabled aliases, durable replay, revocation, concurrent claims, atomic audit failure/retry and legacy-primary protection passed"
    )


if __name__ == "__main__":
    assert os.environ["LEONAID_ENV"] == "test"
    command("-m", "alembic", "upgrade", "head")
    command("tools/seed/golden.py", "seed-core", "tests/fixtures/golden/v1")
    asyncio.run(proof())
