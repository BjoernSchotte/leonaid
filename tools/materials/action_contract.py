#!/usr/bin/env python3
"""Current action roles, cross-action isolation and revocation on real PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from typing import Any
from uuid import uuid4

import asyncpg

from leonaid.adapters.storage.s3 import S3ObjectStorage

from leonaid.application.errors import ApplicationError
from leonaid.domain.identity import (
    AccountStatus,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.bootstrap.api import build_material_service
from leonaid.modules.materials.api import (
    CreateMaterial,
    AddVersion,
    MaterialQuery,
    SetMaterialMember,
    MemberQuery,
)


async def rejected(operation: Awaitable[Any], code: str) -> None:
    try:
        await operation
    except ApplicationError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"Expected {code}")


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
    )
    names = (
        "owner",
        "manager",
        "acquirer",
        "finance_reader",
        "driver",
        "expired",
        "future",
        "other",
        "global",
        "outsider",
    )
    actors = {
        name: IdentityPrincipal(
            UserAccount(
                uuid4(), f"{uuid4()}@leonaid.invalid", name, AccountStatus.ACTIVE
            ),
            frozenset(),
            (),
        )
        for name in names
    }
    # A forged/stale in-memory role must not grant access missing from PostgreSQL.
    outsider = actors["outsider"]
    actors["outsider"] = IdentityPrincipal(
        outsider.account, frozenset({GlobalRole.SYSTEM_ADMIN}), ()
    )
    actions = [uuid4(), uuid4()]
    await storage.ensure_private_versioned_bucket()
    service = build_material_service(pool, storage)
    try:
        async with pool.acquire() as conn:
            for actor in actors.values():
                await conn.execute(
                    "INSERT INTO user_account (id,email,display_name,status) VALUES ($1,$2,$3,'active')",
                    actor.account.id,
                    actor.account.email,
                    actor.account.display_name,
                )
            for action_id in actions:
                await conn.execute(
                    "INSERT INTO charity_action (id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug) VALUES ($1,'Synthetic','Material matrix','Proof','draft','2026-01-01','2026-12-31',$2)",
                    action_id,
                    f"materials-matrix-{action_id}",
                )
            for name in (
                "owner",
                "manager",
                "acquirer",
                "finance_reader",
                "driver",
                "other",
            ):
                role = (
                    "charity_admin" if name in ("owner", "manager", "other") else name
                )
                await conn.execute(
                    "INSERT INTO action_membership (id,action_id,user_id,role) VALUES ($1,$2,$3,$4)",
                    uuid4(),
                    actions[1] if name == "other" else actions[0],
                    actors[name].account.id,
                    role,
                )
            await conn.execute(
                "INSERT INTO action_membership (id,action_id,user_id,role,active_from,active_until) VALUES ($1,$2,$3,'acquirer',now()-interval '2 days',now()-interval '1 day')",
                uuid4(),
                actions[0],
                actors["expired"].account.id,
            )
            await conn.execute(
                "INSERT INTO action_membership (id,action_id,user_id,role,active_from) VALUES ($1,$2,$3,'acquirer',now()+interval '1 day')",
                uuid4(),
                actions[0],
                actors["future"].account.id,
            )
            await conn.execute(
                "INSERT INTO user_global_role (user_id,role) VALUES ($1,'system_admin')",
                actors["global"].account.id,
            )
        owner = actors["owner"]
        create = CreateMaterial(
            idempotency_key=uuid4(),
            title=f"Action material {actions[0]}",
            action_id=actions[0],
            filename="matrix.txt",
        )
        material = await service.create_material(owner, create, b"initial bytes")
        for name in (
            "owner",
            "manager",
            "acquirer",
            "finance_reader",
            "driver",
            "global",
        ):
            assert (
                await service.get_material(actors[name], material.id)
            ).id == material.id
            assert (
                await service.get_version(actors[name], material.id, 1)
            ).version == 1
            assert (
                await service.download(actors[name], material.id, 1)
            ).content == b"initial bytes"
            assert [
                item.id
                for item in (
                    await service.list_materials(
                        actors[name],
                        MaterialQuery(search=f"Action material {actions[0]}"),
                    )
                ).items
            ] == [material.id]
            rights = await service.get_permissions(actors[name], material.id)
            assert (
                rights.can_edit
                == rights.can_manage
                == (name in ("owner", "manager", "global"))
            )
            assert [
                p.id
                for p in (
                    await service.list_materials(
                        actors[name], MaterialQuery(action_id=actions[0])
                    )
                ).items
            ] == [material.id]
        for name in ("expired", "future", "other", "outsider"):
            await rejected(service.get_material(actors[name], material.id), "not_found")
            await rejected(
                service.get_version(actors[name], material.id, 1), "not_found"
            )
            await rejected(service.download(actors[name], material.id, 1), "not_found")
            assert not (
                await service.list_materials(
                    actors[name],
                    MaterialQuery(search=f"Action material {actions[0]}"),
                )
            ).items
            await rejected(
                service.get_permissions(actors[name], material.id), "not_found"
            )
            assert not (
                await service.list_materials(
                    actors[name], MaterialQuery(action_id=actions[0])
                )
            ).items
        for name in (
            "acquirer",
            "finance_reader",
            "driver",
            "expired",
            "future",
            "other",
            "outsider",
        ):
            await rejected(
                service.create_material(
                    actors[name],
                    CreateMaterial(
                        idempotency_key=uuid4(),
                        title="Denied",
                        action_id=actions[0],
                        filename="denied.txt",
                    ),
                    b"denied",
                ),
                "not_found",
            )
            await rejected(
                service.add_version(
                    actors[name],
                    material.id,
                    AddVersion(
                        idempotency_key=uuid4(),
                        expected_revision=1,
                        filename="denied.txt",
                    ),
                    b"denied",
                ),
                "not_found",
            )
        for name in (
            "acquirer",
            "finance_reader",
            "driver",
            "expired",
            "future",
            "other",
            "outsider",
        ):
            await rejected(
                service.list_members(actors[name], material.id, MemberQuery()),
                "not_found",
            )
            await rejected(
                service.set_material_member(
                    actors[name],
                    material.id,
                    SetMaterialMember(
                        idempotency_key=uuid4(),
                        expected_access_revision=1,
                        user_id=actors["driver"].account.id,
                        access="editor",
                    ),
                ),
                "not_found",
            )
        for name in ("manager", "global"):
            material = await service.add_version(
                actors[name],
                material.id,
                AddVersion(
                    idempotency_key=uuid4(),
                    expected_revision=material.revision,
                    filename=f"{name}.txt",
                ),
                name.encode(),
            )
        await rejected(
            service.set_material_member(
                actors["manager"],
                material.id,
                SetMaterialMember(
                    idempotency_key=uuid4(),
                    expected_access_revision=1,
                    user_id=actors["other"].account.id,
                    access="viewer",
                ),
            ),
            "material_member_invalid",
        )
        await rejected(
            service.set_material_member(
                actors["acquirer"],
                material.id,
                SetMaterialMember(
                    idempotency_key=uuid4(),
                    expected_access_revision=1,
                    user_id=actors["driver"].account.id,
                    access="viewer",
                ),
            ),
            "not_found",
        )
        access = await service.set_material_member(
            actors["manager"],
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=1,
                user_id=actors["driver"].account.id,
                access="viewer",
            ),
        )
        assert access.access_revision == 2
        assert (
            await service.list_members(actors["global"], material.id, MemberQuery())
        ).items[0].user_id == actors["driver"].account.id
        async with pool.acquire() as conn:
            # Direct database fixtures exercise read/write enforcement; no membership API is claimed.
            for name in ("acquirer", "outsider"):
                await conn.execute(
                    "INSERT INTO material_member(material_id,user_id,access) VALUES ($1,$2,'editor')",
                    material.id,
                    actors[name].account.id,
                )
        await rejected(
            service.get_material(actors["outsider"], material.id), "not_found"
        )
        await rejected(
            service.download(actors["outsider"], material.id, 1), "not_found"
        )
        edit = AddVersion(
            idempotency_key=uuid4(),
            expected_revision=material.revision,
            filename="editor.txt",
        )
        material = await service.add_version(
            actors["acquirer"], material.id, edit, b"editor bytes"
        )
        assert (
            await service.add_version(
                actors["acquirer"], material.id, edit, b"editor bytes"
            )
            == material
        )
        # Losing additional edit rights must reject replay even while action read access remains.
        await service.set_material_member(
            actors["manager"],
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=2,
                user_id=actors["acquirer"].account.id,
                access="viewer",
            ),
        )
        assert (
            await service.get_material(actors["acquirer"], material.id)
        ).id == material.id
        await rejected(
            service.add_version(actors["acquirer"], material.id, edit, b"editor bytes"),
            "not_found",
        )
        await service.set_material_member(
            actors["manager"],
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=3,
                user_id=actors["acquirer"].account.id,
                access="editor",
            ),
        )
        private = await service.create_material(
            owner,
            CreateMaterial(
                idempotency_key=uuid4(),
                title=f"Standalone {actions[0]}",
                filename="private.txt",
            ),
            b"private",
        )
        await rejected(service.get_material(actors["global"], private.id), "not_found")
        await rejected(
            service.get_version(actors["global"], private.id, 1), "not_found"
        )
        await rejected(service.download(actors["global"], private.id, 1), "not_found")
        assert not (
            await service.list_materials(
                actors["global"], MaterialQuery(search=f"Standalone {actions[0]}")
            )
        ).items
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE action_membership SET active_until=now() WHERE action_id=$1 AND user_id=ANY($2::uuid[])",
                actions[0],
                [owner.account.id, actors["acquirer"].account.id],
            )
            await conn.execute(
                "DELETE FROM user_global_role WHERE user_id=$1",
                actors["global"].account.id,
            )
        for name in ("owner", "acquirer", "global"):
            await rejected(service.get_material(actors[name], material.id), "not_found")
            await rejected(
                service.get_version(actors[name], material.id, 1), "not_found"
            )
            await rejected(service.download(actors[name], material.id, 1), "not_found")
            assert not (
                await service.list_materials(
                    actors[name],
                    MaterialQuery(search=f"Action material {actions[0]}"),
                )
            ).items
            await rejected(
                service.get_permissions(actors[name], material.id), "not_found"
            )
            assert not (
                await service.list_materials(
                    actors[name], MaterialQuery(action_id=actions[0])
                )
            ).items
        await rejected(
            service.create_material(owner, create, b"initial bytes"), "not_found"
        )
        await rejected(
            service.add_version(actors["acquirer"], material.id, edit, b"editor bytes"),
            "not_found",
        )
        assert (await service.get_material(owner, private.id)).id == private.id
        assert (
            await service.get_material(actors["manager"], material.id)
        ).revision == material.revision
        print(
            "PASS materials action roles, isolation, explicit editor, standalone privacy, stale global role and revoked owner/editor replay"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
