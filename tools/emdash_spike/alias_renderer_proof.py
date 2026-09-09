"""Real Core renderer commands and order-route invariants on isolated SQL."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import psycopg

from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.adapters.postgres.campaign_aliases import AsyncpgCampaignAliasRepository
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.actions import CharityActionService
from leonaid.application.campaign_aliases import CampaignAliasCommand
from leonaid.application.campaign_renderer import (
    CampaignRendererCommand,
    CampaignRendererResult,
)
from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.domain.actions import PublicActionAlias
from tools.emdash_spike.alias_persistence_proof import command

A = UUID("20000000-0000-4000-8000-000000000001")
B = UUID("20000000-0000-4000-8000-000000000003")
SYSTEM = UUID("10000000-0000-4000-8000-000000000001")
CHARITY = UUID("10000000-0000-4000-8000-000000000002")


def migration_baseline() -> None:
    command("-m", "alembic", "upgrade", "0028_multiple_campaign_aliases")
    command("tools/seed/golden.py", "seed-core", "tests/fixtures/golden/v1")
    with psycopg.connect(os.environ["CORE_DATABASE_URL"], autocommit=True) as db:
        before = db.execute(
            "SELECT to_jsonb(a) FROM public_action_alias a ORDER BY alias"
        ).fetchall()
        command("-m", "alembic", "upgrade", "head")
        assert (
            db.execute(
                "SELECT to_jsonb(a)-'campaign_redirect' FROM public_action_alias a ORDER BY alias"
            ).fetchall()
            == before
        )
        assert db.execute(
            "SELECT count(*) FROM public_action_alias WHERE campaign_redirect"
        ).fetchone() == (0,)
        command("-m", "alembic", "downgrade", "0028_multiple_campaign_aliases")
        assert (
            db.execute(
                "SELECT to_jsonb(a) FROM public_action_alias a ORDER BY alias"
            ).fetchall()
            == before
        )
        command("-m", "alembic", "upgrade", "head")
        now = datetime.now(timezone.utc)
        db.execute(
            "UPDATE charity_action SET publication_starts_at=%s,publication_ends_at=%s WHERE id=%s",
            (now - timedelta(days=1), now + timedelta(days=1), A),
        )


async def proof() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=5
    )
    assert pool is not None
    repo = AsyncpgCampaignAliasRepository(pool)
    actions = AsyncpgCharityActionRepository(pool)
    service = CharityActionService(actions)
    now = datetime.now(timezone.utc)

    async def snapshot() -> list[list[Any]]:
        async with pool.acquire() as db:
            return [
                await db.fetch(f"SELECT to_jsonb(t) FROM {table} t ORDER BY {key}")
                for table, key in (
                    ("public_action_alias", "id"),
                    ("charity_action", "id"),
                    ("command_receipt", "idempotency_key"),
                    ("audit_event", "id"),
                    ("commitment", "id"),
                    ("commitment_line", "id"),
                )
            ]

    async def select(
        cmd: CampaignRendererCommand, actor: UUID = SYSTEM
    ) -> CampaignRendererResult:
        return await repo.select_renderer(actor, cmd, request_id="synthetic-renderer")

    async def denied(
        cmd: CampaignRendererCommand, error: type[Exception], actor: UUID = SYSTEM
    ) -> None:
        before = await snapshot()
        try:
            await select(cmd, actor)
        except error:
            pass
        else:
            raise AssertionError("invalid renderer command accepted")
        assert await snapshot() == before

    try:
        primary = (await repo.list_for_action(SYSTEM, A)).items[0]
        assert primary.is_primary and primary.alias == "krapfentaxi"
        extra_command = CampaignAliasCommand(
            uuid4(), uuid4(), A, A, "create", 0, "renderer-extra"
        )
        extra = await repo.mutate(SYSTEM, extra_command, request_id="renderer-extra")
        canonical_before = await service.resolve_public_campaign(
            "krapfentaxi-2026", evaluated_at=now
        )
        assert canonical_before.submissions_allowed
        assert canonical_before.order_alias == "krapfentaxi"
        archive_before = await service.resolve_public_archive("krapfentaxi-2025")
        primary_before = await actions.get_by_public_alias(
            PublicActionAlias("krapfentaxi")
        )
        async with pool.acquire() as db:
            alias_before = dict(
                await db.fetchrow(
                    "SELECT * FROM public_action_alias WHERE id=$1", primary.alias_id
                )
            )
            async with db.transaction():
                order_before = await AsyncpgPublicOrderRepository._context(
                    db, action_id=A, public_alias="krapfentaxi", evaluated_at=now
                )
        cutover = CampaignRendererCommand(
            uuid4(), primary.alias_id, A, primary.revision, "campaign"
        )
        await denied(cutover, PermissionDenied, CHARITY)
        await denied(replace(cutover, action_id=B), ResourceNotFound)
        await denied(replace(cutover, alias_id=extra.alias_id), Conflict)
        result = await select(cutover)
        assert result.renderer == "campaign" and result.revision == primary.revision + 1
        before = await snapshot()
        assert await select(cutover) == result
        assert await snapshot() == before
        await denied(replace(cutover, renderer="legacy"), Conflict)
        await denied(replace(cutover, command_id=uuid4()), Conflict)
        redirect = await service.resolve_public_alias("krapfentaxi", evaluated_at=now)
        assert redirect.redirect_path == "/campaigns/krapfentaxi-2026/"
        assert not redirect.submissions_allowed and redirect.order_form is None
        assert not redirect.offerings and redirect.order_alias is None
        assert (
            await service.resolve_public_campaign("krapfentaxi-2026", evaluated_at=now)
            == canonical_before
        )
        assert (
            await service.resolve_public_archive("krapfentaxi-2025") == archive_before
        )
        assert (
            await actions.get_by_public_alias(PublicActionAlias("krapfentaxi"))
            == primary_before
        )
        async with pool.acquire() as db:
            alias_after = dict(
                await db.fetchrow(
                    "SELECT * FROM public_action_alias WHERE id=$1", primary.alias_id
                )
            )
            assert {
                **alias_after,
                "campaign_redirect": False,
                "revision": primary.revision,
            } == alias_before
            async with db.transaction():
                assert (
                    await AsyncpgPublicOrderRepository._context(
                        db, action_id=A, public_alias="krapfentaxi", evaluated_at=now
                    )
                    == order_before
                )
            # The database itself forbids assigning a second renderer to an
            # additional alias, which already has canonical redirect semantics.
            try:
                await db.execute(
                    "UPDATE public_action_alias SET campaign_redirect=true WHERE id=$1",
                    extra.alias_id,
                )
            except asyncpg.CheckViolationError:
                pass
            else:
                raise AssertionError("secondary renderer constraint absent")
        failed_downgrade = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "downgrade",
                "0028_multiple_campaign_aliases",
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        assert failed_downgrade.returncode != 0
        assert (
            b"campaign renderer downgrade requires explicit legacy selection"
            in failed_downgrade.stderr
        )
        assert await snapshot() == before
        # New-UUID rollback changes only renderer/revision, not the alias,
        # immutable canonical/archive identity or authoritative order context.
        rollback = replace(
            cutover, command_id=uuid4(), revision=result.revision, renderer="legacy"
        )
        rolled_back = await select(rollback)
        assert (
            await service.resolve_public_alias("krapfentaxi", evaluated_at=now)
        ).submissions_allowed
        before = await snapshot()
        assert await select(cutover) == result  # stale success must not re-activate
        assert await select(rollback) == rolled_back
        assert (
            await repo.mutate(SYSTEM, extra_command, request_id="renderer-extra-replay")
            == extra
        )
        assert await snapshot() == before
        # Different commands claiming one revision have exactly one winner.
        race = replace(cutover, command_id=uuid4(), revision=rolled_back.revision)
        outcomes = await asyncio.gather(
            select(race),
            select(replace(race, command_id=uuid4(), renderer="legacy")),
            return_exceptions=True,
        )
        assert sum(isinstance(item, CampaignRendererResult) for item in outcomes) == 1
        assert sum(isinstance(item, Conflict) for item in outcomes) == 1
        current = (await repo.list_for_action(SYSTEM, A)).items[0]
        retry = replace(cutover, command_id=uuid4(), revision=current.revision)
        async with pool.acquire() as db:
            await db.execute(
                "CREATE FUNCTION reject_renderer_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.event_type='campaign_renderer.changed' THEN RAISE EXCEPTION 'synthetic renderer failure'; END IF; RETURN NEW; END $$"
            )
            await db.execute(
                "CREATE TRIGGER reject_renderer_audit BEFORE INSERT ON audit_event FOR EACH ROW EXECUTE FUNCTION reject_renderer_audit()"
            )
        await denied(retry, asyncpg.RaiseError)
        async with pool.acquire() as db:
            await db.execute("DROP TRIGGER reject_renderer_audit ON audit_event")
            await db.execute("DROP FUNCTION reject_renderer_audit()")
        accepted = await select(retry)
        # Revocation while waiting for the publication lock must be observed
        # after acquiring it, not authorized by an earlier principal snapshot.
        async with pool.acquire() as blocker:
            async with blocker.transaction():
                await blocker.execute("SELECT pg_advisory_xact_lock(527052)")
                task = asyncio.create_task(
                    select(
                        replace(retry, command_id=uuid4(), revision=accepted.revision)
                    )
                )
                await asyncio.sleep(0.05)
                async with pool.acquire() as db:
                    await db.execute(
                        "DELETE FROM user_global_role WHERE user_id=$1 AND role='system_admin'",
                        SYSTEM,
                    )
            try:
                await task
            except PermissionDenied:
                pass
            else:
                raise AssertionError("revoked system role accepted")
        await denied(cutover, PermissionDenied)
        async with pool.acquire() as db:
            await db.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                SYSTEM,
            )
            audits = [
                json.loads(row["payload"])
                for row in await db.fetch(
                    "SELECT payload FROM audit_event WHERE event_type='campaign_renderer.changed' ORDER BY occurred_at"
                )
            ]
            assert len(audits) == 4
            assert (
                audits[0]["previousRenderer"] == "legacy"
                and audits[0]["newRenderer"] == "campaign"
            )
            await db.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1", SYSTEM
            )
        await denied(cutover, PermissionDenied)
    finally:
        await pool.close()
    print(
        "alias-renderer: actual migration/defaults, protected primary selection, canonical order configuration, unchanged order context/archive/alias identity, durable replay after rollback, revision race, audit failure rollback/retry, current role revocation and suspension passed; no CMS-data rollback or browser cutover claimed"
    )


if __name__ == "__main__":
    assert os.environ["LEONAID_ENV"] == "test"
    migration_baseline()
    asyncio.run(proof())
