#!/usr/bin/env python3
"""Inbox material references with real versioned storage and independent permissions."""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import httpx

from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.errors import Conflict, DependencyUnavailable, ResourceNotFound
from leonaid.bootstrap.api import build_inbox_service, build_material_service
from leonaid.configuration import Settings
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.modules.inbox.api import SetMaterialReference, SubmitCase, UpdateCase
from leonaid.modules.materials.api import (
    AddVersion,
    CreateMaterial,
    MaterialService,
    SetMaterialMember,
)
from leonaid.modules.materials.repository import AsyncpgMaterialRepository


async def main() -> None:
    settings = Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-http-proof-secret-only-32-characters",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-http-proof-encryption-32-characters",
            "LEONAID_PUBLIC_BASE_URL": "https://inbox.leonaid.invalid",
            "LEONAID_ALLOWED_ORIGINS": "https://inbox.leonaid.invalid",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=1
    )
    assert pool is not None
    storage = S3ObjectStorage(
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
        secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
        bucket=os.environ["OBJECT_STORAGE_BUCKET"],
    )
    await storage.ensure_private_versioned_bucket()
    inbox, materials = build_inbox_service(pool), build_material_service(pool, storage)
    users = [uuid4() for _ in range(3)]
    owner, assigned, outsider = [
        IdentityPrincipal(
            UserAccount(
                user,
                f"{user}@example.org",
                "Inbox material proof",
                AccountStatus.ACTIVE,
            ),
            frozenset(),
            (),
        )
        for user in users
    ]
    token = uuid4().hex + uuid4().hex
    commands = [
        SubmitCase(
            idempotency_key=uuid4(),
            subject="Linked file",
            message="Synthetic",
            given_name="Test",
            family_name="Person",
            email="test@example.org",
        )
        for _ in range(2)
    ]
    case_ids = []
    material_id = None
    try:
        async with pool.acquire() as conn:
            for user in users:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Inbox material proof','active')",
                    user,
                    f"{user}@example.org",
                )
            await conn.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                users[0],
            )
            now = datetime.now(timezone.utc)
            await conn.execute(
                "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,'Inbox materials',$5,$5)",
                uuid4(),
                users[0],
                session_token_digest(token),
                now + SESSION_LIFETIME,
                now,
            )
        for command in commands:
            receipt = await inbox.submit(command)
            async with pool.acquire() as conn:
                case_ids.append(
                    await conn.fetchval(
                        "SELECT id FROM inbox_case WHERE public_reference=$1",
                        receipt.reference,
                    )
                )
        case_id, second_case = case_ids
        current = await inbox.update_case(
            owner,
            case_id,
            UpdateCase(
                idempotency_key=uuid4(),
                expected_revision=1,
                status="in_progress",
                assignee_user_id=users[1],
            ),
        )
        material = await materials.create_material(
            owner,
            CreateMaterial(
                idempotency_key=uuid4(),
                title="Private material",
                filename="original.txt",
            ),
            b"original bytes",
        )
        material_id = material.id
        original = await materials.get_version(owner, material.id, 1)
        link = SetMaterialReference(
            idempotency_key=uuid4(),
            expected_revision=current.revision,
            material_id=material.id,
            material_version=1,
            present=True,
        )
        try:
            await inbox.set_material_reference(assigned, case_id, link)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Case access granted material access")
        async with asyncio.timeout(10):
            result, replay = await asyncio.gather(
                inbox.set_material_reference(owner, case_id, link),
                inbox.set_material_reference(owner, case_id, link),
            )
        assert result == replay and result.revision == current.revision + 1
        assert result.contact_revision == current.contact_revision
        await inbox.set_material_reference(
            owner,
            second_case,
            link.model_copy(
                update={"idempotency_key": uuid4(), "expected_revision": 1}
            ),
        )
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM material_version WHERE material_id=$1",
                    material.id,
                )
                == 1
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM inbox_case_material WHERE material_id=$1",
                    material.id,
                )
                == 2
            )
        await materials.add_version(
            owner,
            material.id,
            AddVersion(
                idempotency_key=uuid4(), expected_revision=1, filename="replacement.txt"
            ),
            b"new bytes",
        )
        for item in case_ids:
            refs = await inbox.list_material_references(owner, item)
            assert (
                refs.items[0].material_version == 1 and refs.items[0].file == original
            )
        assert (
            await materials.download(owner, material.id, 1)
        ).content == b"original bytes"
        assert (await materials.download(owner, material.id, 2)).content == b"new bytes"
        metadata_only = MaterialService(AsyncpgMaterialRepository(pool))
        assert await metadata_only.get_version(owner, material.id, 1) == original
        try:
            await metadata_only.download(owner, material.id, 1)
        except DependencyUnavailable as error:
            assert error.code == "material_storage_unavailable"
        else:
            raise AssertionError("Unconfigured storage accepted download")
        assert (await inbox.list_material_references(assigned, case_id)).items[
            0
        ].file is None
        try:
            await inbox.list_material_references(outsider, case_id)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Foreign case file reference leaked")
        try:
            await inbox.set_material_reference(
                owner,
                case_id,
                link.model_copy(
                    update={
                        "idempotency_key": uuid4(),
                        "expected_revision": result.revision,
                        "material_version": 3,
                    }
                ),
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Missing material version linked")
        access = await materials.set_material_member(
            owner,
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=1,
                user_id=users[1],
                access="viewer",
            ),
        )
        shared = link.model_copy(
            update={"idempotency_key": uuid4(), "expected_revision": result.revision}
        )
        assert (
            await inbox.set_material_reference(assigned, case_id, shared)
        ).revision == result.revision
        assert (await inbox.list_material_references(assigned, case_id)).items[
            0
        ].file == original
        await materials.set_material_member(
            owner,
            material.id,
            SetMaterialMember(
                idempotency_key=uuid4(),
                expected_access_revision=access.access_revision,
                user_id=users[1],
                access=None,
            ),
        )
        try:
            await inbox.set_material_reference(assigned, case_id, shared)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Replay bypassed material revocation")
        assert (await inbox.list_material_references(assigned, case_id)).items[
            0
        ].file is None
        removed = await inbox.set_material_reference(
            assigned,
            case_id,
            SetMaterialReference(
                idempotency_key=uuid4(),
                expected_revision=result.revision,
                material_id=material.id,
                material_version=1,
                present=False,
            ),
        )
        assert not (await inbox.list_material_references(owner, case_id)).items
        assert (
            await materials.download(owner, material.id, 1)
        ).content == b"original bytes"
        assert (
            len((await inbox.list_material_references(owner, second_case)).items) == 1
        )
        try:
            await inbox.set_material_reference(
                owner, case_id, link.model_copy(update={"idempotency_key": uuid4()})
            )
        except Conflict:
            pass
        else:
            raise AssertionError("Stale case linked material")
        failed = link.model_copy(
            update={"idempotency_key": uuid4(), "expected_revision": removed.revision}
        )
        key = f"inbox.material-reference:{users[0]}:{case_id}:{failed.idempotency_key}"
        constraint = f"material_link_proof_{uuid4().hex}"
        async with pool.acquire() as conn:
            await conn.execute(
                f"ALTER TABLE audit_event ADD CONSTRAINT {constraint} CHECK(request_id <> '{key}')"
            )
        try:
            try:
                await inbox.set_material_reference(owner, case_id, failed)
            except asyncpg.CheckViolationError:
                pass
            else:
                raise AssertionError("Expected actual audit failure")
            assert not (await inbox.list_material_references(owner, case_id)).items
            assert (await inbox.get_case(owner, case_id)).revision == removed.revision
            async with pool.acquire() as conn:
                assert not await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM command_receipt WHERE idempotency_key=$1)",
                    key,
                )
        finally:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"ALTER TABLE audit_event DROP CONSTRAINT {constraint}"
                )
        # Exercise the bound with real immutable versions, not invented file metadata.
        second_revision = (await inbox.get_case(owner, second_case)).revision
        for version in range(2, 102):
            if version > 2:
                await materials.add_version(
                    owner,
                    material.id,
                    AddVersion(
                        idempotency_key=uuid4(),
                        expected_revision=version - 1,
                        filename=f"version-{version}.txt",
                    ),
                    f"version {version}".encode(),
                )
            boundary = SetMaterialReference(
                idempotency_key=uuid4(),
                expected_revision=second_revision,
                material_id=material.id,
                material_version=version,
                present=True,
            )
            if version == 101:
                try:
                    await inbox.set_material_reference(owner, second_case, boundary)
                except Conflict as error:
                    assert error.code == "reference_limit"
                else:
                    raise AssertionError("Material reference limit bypassed")
            else:
                second_revision = (
                    await inbox.set_material_reference(owner, second_case, boundary)
                ).revision
        assert (
            len((await inbox.list_material_references(owner, second_case)).items) == 100
        )
        app = create_app(settings)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://inbox.leonaid.invalid",
            ) as client,
        ):
            path = f"/api/v1/inbox-cases/{case_id}/materials"
            headers = {
                "Cookie": f"{SESSION_COOKIE_NAME}={token}",
                "Origin": "https://inbox.leonaid.invalid",
            }
            payload = failed.model_dump(mode="json", by_alias=True)
            assert (await client.get(path)).status_code == 401
            assert (
                await client.put(
                    path,
                    headers={"Cookie": headers["Cookie"], "Sec-Fetch-Mode": "cors"},
                    json=payload,
                )
            ).status_code == 403
            response = await client.put(path, headers=headers, json=payload)
            assert response.status_code == 200, response.text
            response_refs = await client.get(path, headers=headers)
            assert (
                response_refs.status_code == 200
                and response_refs.headers["cache-control"] == "no-store"
            )
            assert response_refs.json()["items"][0]["file"]["sha256"] == original.sha256
            for invalid_version in (0, 2**63, "1"):
                assert (
                    await client.put(
                        path,
                        headers=headers,
                        json={**payload, "materialVersion": invalid_version},
                    )
                ).status_code == 422
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM user_global_role WHERE user_id=$1", users[0]
                )
            assert (await client.get(path, headers=headers)).status_code == 404
            assert (
                await client.put(path, headers=headers, json=payload)
            ).status_code == 404
        print(
            "PASS Inbox materials: real uploads, fixed versions, one-slot composition, shared files, independent ACL/revoked replay, storage guard, atomic rollback and production HTTP"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM inbox_case WHERE id=ANY($1::uuid[])", case_ids
            )
            await conn.execute(
                "DELETE FROM outbox_event WHERE aggregate_type='inbox_case' AND aggregate_id=ANY($1::uuid[])",
                case_ids,
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE entity_id=ANY($1::uuid[]) OR actor_user_id=ANY($2::uuid[])",
                case_ids,
                users,
            )
            await conn.execute(
                "DELETE FROM material_version WHERE material_id=$1", material_id
            )
            await conn.execute("DELETE FROM material WHERE id=$1", material_id)
            await conn.execute(
                "DELETE FROM command_receipt WHERE idempotency_key=ANY($1::text[]) OR idempotency_key LIKE ANY($2::text[])",
                [f"inbox.submit:{item.idempotency_key}" for item in commands],
                [
                    f"{prefix}:{user}:%"
                    for user in users
                    for prefix in (
                        "materials",
                        "inbox.update",
                        "inbox.material-reference",
                    )
                ],
            )
            await conn.execute(
                "DELETE FROM user_session WHERE user_id=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM user_global_role WHERE user_id=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM user_account WHERE id=ANY($1::uuid[])", users
            )
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
