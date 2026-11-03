#!/usr/bin/env python3
"""Real versioned uploads referenced by pages through a single-connection pool."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg

from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.errors import ResourceNotFound
from leonaid.bootstrap.api import build_knowledge_service, build_material_service
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.knowledge.api import CreatePage, UpdatePage
from leonaid.modules.materials.api import CreateMaterial, AddVersion, SetMaterialMember


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=1, command_timeout=10
    )
    assert pool is not None
    storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
    )
    await storage.ensure_private_versioned_bucket()
    knowledge = build_knowledge_service(pool, storage)
    materials = build_material_service(pool, storage)
    actors = [
        IdentityPrincipal(
            UserAccount(
                uid, f"{uid}@example.org", "Reference proof", AccountStatus.ACTIVE
            ),
            frozenset(),
            (),
        )
        for uid in (uuid4(), uuid4())
    ]
    owner, reader = actors
    try:
        async with pool.acquire() as conn:
            for actor in actors:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Reference proof','active')",
                    actor.account.id,
                    actor.account.email,
                )
        material = await materials.create_material(
            owner,
            CreateMaterial(
                idempotency_key=uuid4(), title="One upload", filename="reference.txt"
            ),
            b"original bytes",
        )
        node = {
            "type": "materialReference",
            "attrs": {"materialId": str(material.id), "version": 1},
        }
        content = {"type": "doc", "content": [node, node]}
        pages = [
            await knowledge.create_page(
                owner,
                CreatePage(
                    idempotency_key=uuid4(),
                    title=f"Reference page {i}",
                    content=content,
                ),
            )
            for i in range(2)
        ]
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM knowledge_page_material WHERE material_id=$1",
                    material.id,
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM material_version WHERE material_id=$1",
                    material.id,
                )
                == 1
            )
        await materials.add_version(
            owner,
            material.id,
            AddVersion(
                idempotency_key=uuid4(), expected_revision=1, filename="reference.txt"
            ),
            b"new bytes",
        )
        for page in pages:
            assert (await knowledge.get_page(owner, page.id)).content == content
        assert (
            await materials.download(owner, material.id, 1)
        ).content == b"original bytes"
        assert (await materials.download(owner, material.id, 2)).content == b"new bytes"
        # A readable page does not grant access to its referenced material.
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO knowledge_page_member(page_id,user_id,access) VALUES ($1,$2,'editor')",
                pages[0].id,
                reader.account.id,
            )
        assert (await knowledge.get_page(reader, pages[0].id)).content == content
        update = UpdatePage(
            idempotency_key=uuid4(),
            expected_revision=1,
            title="Updated",
            content=content,
        )
        for operation in (
            knowledge.update_page(reader, pages[0].id, update),
            knowledge.create_page(
                reader,
                CreatePage(idempotency_key=uuid4(), title="Forbidden", content=content),
            ),
            materials.download(reader, material.id, 1),
        ):
            try:
                await operation
            except ResourceNotFound:
                pass
            else:
                raise AssertionError("Reference granted unauthorized access")
        access = await materials.set_material_member(
            owner,
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=1,
                user_id=reader.account.id,
                access="viewer",
            ),
        )
        changed = await knowledge.update_page(reader, pages[0].id, update)
        assert changed.revision == 2
        assert await knowledge.update_page(reader, pages[0].id, update) == changed
        invalid = {
            "type": "doc",
            "content": [
                {
                    "type": "materialReference",
                    "attrs": {"materialId": str(material.id), "version": 3},
                }
            ],
        }
        try:
            await knowledge.update_page(
                reader,
                pages[0].id,
                UpdatePage(
                    idempotency_key=uuid4(),
                    expected_revision=2,
                    title="Missing version",
                    content=invalid,
                ),
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Missing version accepted")
        await materials.set_material_member(
            owner,
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=access.access_revision,
                user_id=reader.account.id,
                access=None,
            ),
        )
        try:
            await knowledge.update_page(
                reader,
                pages[0].id,
                UpdatePage(
                    idempotency_key=uuid4(),
                    expected_revision=2,
                    title="Revoked",
                    content=content,
                ),
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Revoked material embedded")
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT revision FROM knowledge_page WHERE id=$1", pages[0].id
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM knowledge_page_revision WHERE page_id=$1",
                    pages[0].id,
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM knowledge_page_material WHERE page_id=$1",
                    pages[0].id,
                )
                == 2
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_event WHERE entity_id=$1", pages[0].id
                )
                == 2
            )
            await conn.execute(
                "DELETE FROM knowledge_page WHERE id=ANY($1::uuid[])",
                [page.id for page in pages],
            )
        assert (
            await materials.download(owner, material.id, 1)
        ).content == b"original bytes"
        print(
            "Knowledge material references: exact versions, shared upload, current rights, rollback and independent lifetime passed"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
