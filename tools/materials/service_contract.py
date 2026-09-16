#!/usr/bin/env python3
"""Real PostgreSQL and private versioned S3 material operations; synthetic inputs only."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg

from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.errors import (
    Conflict,
    ResourceNotFound,
    AuthenticationRequired,
)
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.materials.api import (
    MaterialService,
    CreateMaterial,
    AddVersion,
    MaterialQuery,
)
from leonaid.modules.materials.repository import AsyncpgMaterialRepository


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2, command_timeout=30
    )
    assert pool is not None
    storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
    )
    await storage.ensure_private_versioned_bucket()
    service = MaterialService(AsyncpgMaterialRepository(pool, storage))
    actors = [
        IdentityPrincipal(
            UserAccount(
                identifier,
                f"{identifier}@example.org",
                "Material proof",
                AccountStatus.ACTIVE,
            ),
            frozenset(),
            (),
        )
        for identifier in (uuid4(), uuid4())
    ]
    owner, reader = actors
    try:
        async with pool.acquire() as conn:
            for actor in actors:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Material proof','active')",
                    actor.account.id,
                    actor.account.email,
                )
        # A real outer transaction rolls back DB state after S3 succeeded.
        # A retry must reuse that exact object version, not write another copy.
        recovery = CreateMaterial(
            idempotency_key=uuid4(), title="Recovery file", filename="recovery.txt"
        )
        rolled_material = None
        stored_version = None
        async with pool.acquire() as conn:
            try:
                async with conn.transaction():
                    bound = MaterialService(
                        AsyncpgMaterialRepository(pool, storage, connection=conn)
                    )
                    rolled_material = await bound.create_material(
                        owner, recovery, b"durable bytes"
                    )
                    stored_version = await conn.fetchval(
                        "SELECT storage_version_id FROM material_version WHERE material_id=$1",
                        rolled_material.id,
                    )
                    raise RuntimeError("Outer transaction rollback proof")
            except RuntimeError as error:
                assert str(error) == "Outer transaction rollback proof"
            assert rolled_material is not None
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM material WHERE id=$1", rolled_material.id
                )
                == 0
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_event WHERE entity_id=$1",
                    rolled_material.id,
                )
                == 0
            )
        recovered = await service.create_material(owner, recovery, b"durable bytes")
        assert recovered.id == rolled_material.id
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT storage_version_id FROM material_version WHERE material_id=$1",
                    recovered.id,
                )
                == stored_version
            )
        assert (
            await service.download(owner, recovered.id, 1)
        ).content == b"durable bytes"
        command = CreateMaterial(
            idempotency_key=uuid4(),
            title="Private preparation",
            filename="preparation.txt",
            media_type="text/plain",
        )
        first = bytes(range(256))
        material, replay = await asyncio.gather(
            service.create_material(owner, command, first),
            service.create_material(owner, command, first),
        )
        assert material == replay
        assert (await service.download(owner, material.id, 1)).content == first
        assert (
            len(
                (
                    await service.list_materials(
                        owner, MaterialQuery(search="preparation")
                    )
                ).items
            )
            == 1
        )
        assert not (await service.list_materials(reader, MaterialQuery())).items
        for operation in (
            service.get_material(reader, material.id),
            service.get_version(reader, material.id, 1),
            service.download(reader, material.id, 1),
        ):
            try:
                await operation
            except ResourceNotFound:
                pass
            else:
                raise AssertionError("Private material leaked")
        try:
            await service.create_material(owner, command, b"different bytes")
        except Conflict:
            pass
        else:
            raise AssertionError("Changed bytes accepted under same key")
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO material_member(material_id,user_id,access) VALUES ($1,$2,'viewer')",
                material.id,
                reader.account.id,
            )
        assert (await service.download(reader, material.id, 1)).content == first
        version = AddVersion(
            idempotency_key=uuid4(),
            expected_revision=1,
            filename="preparation.txt",
            media_type="text/plain",
        )
        try:
            await service.add_version(reader, material.id, version, b"viewer write")
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Viewer wrote version")
        outcomes = await asyncio.gather(
            service.add_version(owner, material.id, version, b"second version"),
            service.add_version(
                owner,
                material.id,
                AddVersion(
                    idempotency_key=uuid4(),
                    expected_revision=1,
                    filename="alternate.txt",
                ),
                b"parallel version",
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, Conflict) for result in outcomes) == 1, outcomes
        successful = next(
            result for result in outcomes if not isinstance(result, BaseException)
        )
        assert successful.current_version == 2 and successful.revision == 2
        assert (await service.download(owner, material.id, 1)).content == first
        assert (await service.get_version(owner, material.id, 2)).version == 2
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM material_version WHERE material_id=$1",
                    material.id,
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_event WHERE entity_type='material' AND entity_id=$1",
                    material.id,
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM command_receipt WHERE idempotency_key LIKE $1",
                    f"materials:{owner.account.id}:%",
                )
                == 3
            )
            await conn.execute(
                "DELETE FROM material_member WHERE material_id=$1 AND user_id=$2",
                material.id,
                reader.account.id,
            )
        try:
            await service.download(reader, material.id, 1)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Revoked member downloaded")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1",
                owner.account.id,
            )
        try:
            await service.create_material(owner, command, first)
        except AuthenticationRequired:
            pass
        else:
            raise AssertionError("Inactive actor replayed")
        print(
            "PASS real material concurrent upload/replay, byte-identical S3 download, version conflict, retained old bytes, ACL/search/revocation and atomic audit/receipts"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
