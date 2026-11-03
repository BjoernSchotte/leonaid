#!/usr/bin/env python3
"""Real PostgreSQL and private versioned S3 material operations; synthetic inputs only."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4
from typing import Literal

import asyncpg

from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.errors import (
    Conflict,
    ResourceNotFound,
)
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.materials.api import (
    MaterialService,
    CreateMaterial,
    AddVersion,
    SetMaterialMember,
    SetMaterialMemberByEmail,
    MemberQuery,
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
        material = await service.create_material(
            owner,
            CreateMaterial(
                idempotency_key=uuid4(), title="Shared material", filename="notes.txt"
            ),
            b"first version",
        )
        grant = SetMaterialMemberByEmail(
            idempotency_key=uuid4(),
            expected_access_revision=1,
            email=reader.account.email,
            access="viewer",
        )
        granted = await service.set_material_member_by_email(owner, material.id, grant)
        assert granted.access_revision == 2
        assert (
            await service.set_material_member_by_email(owner, material.id, grant)
            == granted
        )
        members = await service.list_members(
            owner, material.id, MemberQuery(search="Material", limit=1)
        )
        assert len(members.items) == 1 and members.items[0].user_id == reader.account.id
        assert not (await service.get_permissions(reader, material.id)).can_edit
        for operation in (
            service.list_members(reader, material.id, MemberQuery()),
            service.set_material_member(
                reader,
                material.id,
                SetMaterialMember(
                    idempotency_key=uuid4(),
                    expected_access_revision=2,
                    user_id=reader.account.id,
                    access="editor",
                ),
            ),
        ):
            try:
                await operation
            except ResourceNotFound:
                pass
            else:
                raise AssertionError("Viewer managed access")
        try:
            await service.set_material_member(
                owner,
                material.id,
                SetMaterialMember(
                    idempotency_key=uuid4(),
                    expected_access_revision=2,
                    user_id=owner.account.id,
                    access=None,
                ),
            )
        except Conflict as error:
            assert error.code == "material_owner_protected"
        else:
            raise AssertionError("Owner removed")
        accesses: tuple[Literal["editor", "viewer"], ...] = ("editor", "viewer")
        outcomes = await asyncio.gather(
            *(
                service.set_material_member(
                    owner,
                    material.id,
                    SetMaterialMember(
                        idempotency_key=uuid4(),
                        expected_access_revision=2,
                        user_id=reader.account.id,
                        access=access,
                    ),
                )
                for access in accesses
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, Conflict) for result in outcomes) == 1, outcomes
        await service.set_material_member(
            owner,
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=3,
                user_id=reader.account.id,
                access="editor",
            ),
        )
        assert (await service.get_permissions(reader, material.id)).can_edit
        assert not (await service.get_permissions(reader, material.id)).can_manage
        updated = await service.add_version(
            reader,
            material.id,
            AddVersion(
                idempotency_key=uuid4(), expected_revision=1, filename="new.txt"
            ),
            b"editor version",
        )
        assert updated.revision == 2
        assert (
            await service.list_members(owner, material.id, MemberQuery())
        ).access_revision == 4
        await service.set_material_member(
            owner,
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=4,
                user_id=reader.account.id,
                access=None,
            ),
        )
        assert (await service.get_material(owner, material.id)).revision == 2
        try:
            await service.download(reader, material.id, 1)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Revoked member downloaded")
        action = uuid4()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug) VALUES ($1,'Synthetic','Materials','Proof','draft','2026-01-01','2026-12-31',$2)",
                action,
                f"materials-{action}",
            )
            await conn.execute(
                "INSERT INTO action_membership(id,action_id,user_id,role) VALUES ($1,$2,$3,'charity_admin')",
                uuid4(),
                action,
                owner.account.id,
            )
        scoped = await service.create_material(
            owner,
            CreateMaterial(
                idempotency_key=uuid4(),
                title="Action material",
                action_id=action,
                filename="action.txt",
            ),
            b"scoped",
        )
        try:
            await service.set_material_member(
                owner,
                scoped.id,
                SetMaterialMember(
                    idempotency_key=uuid4(),
                    expected_access_revision=1,
                    user_id=reader.account.id,
                    access="editor",
                ),
            )
        except Conflict as error:
            assert error.code == "material_member_invalid"
        else:
            raise AssertionError("Outsider received action access")
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO action_membership(id,action_id,user_id,role) VALUES ($1,$2,$3,'acquirer')",
                uuid4(),
                action,
                reader.account.id,
            )
        await service.set_material_member(
            owner,
            scoped.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=1,
                user_id=reader.account.id,
                access="editor",
            ),
        )
        assert (await service.get_permissions(reader, scoped.id)).can_edit
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE action_membership SET active_from=now()-interval '2 days',active_until=now()-interval '1 day' WHERE action_id=$1",
                action,
            )
        for identity in (owner, reader):
            try:
                await service.get_permissions(identity, scoped.id)
            except ResourceNotFound:
                pass
            else:
                raise AssertionError("Expired membership bypassed by owner/editor")
        print(
            "PASS material email grants, owner protection, concurrent access revision, editor upload, separate counters, revocation and current action boundary"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
