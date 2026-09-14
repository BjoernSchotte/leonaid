#!/usr/bin/env python3
"""Actual PostgreSQL transaction races and exact S3 deletion; no I/O doubles."""

from __future__ import annotations

import asyncio
import os
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.object_storage import ObjectLocation
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.materials.api import CreateMaterial, CleanupUpload, MaterialService
from leonaid.modules.materials.repository import AsyncpgMaterialRepository


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4, command_timeout=10
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
    owner, admin = [
        IdentityPrincipal(
            UserAccount(
                uid, f"{uid}@example.org", "Cleanup proof", AccountStatus.ACTIVE
            ),
            frozenset(),
            (),
        )
        for uid in (uuid4(), uuid4())
    ]
    try:
        async with pool.acquire() as conn:
            for actor in (owner, admin):
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Cleanup proof','active')",
                    actor.account.id,
                    actor.account.email,
                )
            await conn.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES ($1,'system_admin')",
                admin.account.id,
            )
        # A cleanup started during an upload must wait for the OUTER transaction.
        for commit in (True, False):
            command = CreateMaterial(
                idempotency_key=uuid4(), title="Cleanup race", filename="race.txt"
            )
            async with pool.acquire() as conn:
                transaction = conn.transaction()
                await transaction.start()
                try:
                    bound = MaterialService(
                        AsyncpgMaterialRepository(pool, storage, connection=conn)
                    )
                    material = await bound.create_material(
                        owner, command, b"race bytes"
                    )
                    row = await conn.fetchrow(
                        "SELECT object_key,storage_version_id FROM material_version WHERE material_id=$1",
                        material.id,
                    )
                    assert row is not None
                    cleanup = CleanupUpload(
                        material_id=material.id,
                        upload_id=UUID(row["object_key"].split("/")[-1]),
                        storage_version_id=row["storage_version_id"],
                        reason="Synthetic rollback cleanup proof",
                        apply=True,
                    )
                    pending = asyncio.create_task(
                        service.cleanup_upload(admin, cleanup)
                    )
                    async with pool.acquire() as observer:
                        async with asyncio.timeout(5):
                            while not await observer.fetchval(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted)"
                            ):
                                await asyncio.sleep(0.01)
                        assert not pending.done()
                        assert (
                            await observer.fetchval(
                                "SELECT count(*) FROM audit_event WHERE entity_id=$1 AND event_type='material.upload_cleanup_requested'",
                                material.id,
                            )
                            == 1
                        )
                    if commit:
                        await transaction.commit()
                    else:
                        await transaction.rollback()
                except BaseException:
                    if conn.is_in_transaction():
                        await transaction.rollback()
                    raise
            if commit:
                try:
                    await pending
                except Conflict as error:
                    assert error.code == "material_upload_referenced"
                else:
                    raise AssertionError("Committed upload was removed")
                assert (
                    await service.download(owner, material.id, 1)
                ).content == b"race bytes"
            else:
                assert await pending
                assert (
                    await storage.head(
                        ObjectLocation(
                            storage.bucket, row["object_key"], row["storage_version_id"]
                        )
                    )
                    is None
                )
                assert not await service.cleanup_upload(admin, cleanup)
                recovered = await service.create_material(owner, command, b"race bytes")
                assert recovered.id == material.id
                assert (
                    await service.download(owner, recovered.id, 1)
                ).content == b"race bytes"
        # Dry-run leaves a rolled-back upload intact, apply removes only that version.
        async with pool.acquire() as conn:
            transaction = conn.transaction()
            await transaction.start()
            bound = MaterialService(
                AsyncpgMaterialRepository(pool, storage, connection=conn)
            )
            material = await bound.create_material(
                owner,
                CreateMaterial(
                    idempotency_key=uuid4(), title="Orphan", filename="orphan.txt"
                ),
                b"orphan bytes",
            )
            row = await conn.fetchrow(
                "SELECT object_key,storage_version_id FROM material_version WHERE material_id=$1",
                material.id,
            )
            assert row is not None
            await transaction.rollback()
        location = ObjectLocation(
            storage.bucket, row["object_key"], row["storage_version_id"]
        )
        preview = CleanupUpload(
            material_id=material.id,
            upload_id=UUID(row["object_key"].split("/")[-1]),
            storage_version_id=row["storage_version_id"],
            reason="Synthetic abandoned upload",
        )
        cli_env = {
            **os.environ,
            "LEONAID_ENV": "test",
            "LEONAID_SECRET_KEY": "synthetic-cleanup-proof-secret-32-characters",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-cleanup-proof-encryption-32-characters",
            "LEONAID_PUBLIC_BASE_URL": "https://cleanup.leonaid.invalid",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
        }

        async def cli(apply: bool) -> dict[str, str]:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(Path(__file__).with_name("cleanup.py")),
                "--actor",
                str(admin.account.id),
                "--material",
                str(preview.material_id),
                "--upload",
                str(preview.upload_id),
                "--storage-version",
                preview.storage_version_id,
                "--reason",
                preview.reason,
                *(["--apply"] if apply else []),
                env=cli_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            assert process.returncode == 0, stderr.decode()
            return dict(json.loads(stdout))

        assert await cli(False) == {"mode": "dry-run", "result": "would-delete"}
        assert await service.cleanup_upload(admin, preview)
        assert (await storage.get(location)).content == b"orphan bytes"
        try:
            await service.cleanup_upload(
                owner, preview.model_copy(update={"apply": True})
            )
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Non-admin cleanup accepted")
        assert await cli(True) == {"mode": "apply", "result": "deleted"}
        assert await storage.head(location) is None
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_event WHERE entity_id=$1 AND event_type='material.upload_cleanup_completed'",
                    material.id,
                )
                == 1
            )
            await conn.execute(
                "DELETE FROM user_global_role WHERE user_id=$1", admin.account.id
            )
        try:
            await service.cleanup_upload(admin, preview)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Stale administrator accepted")
        print(
            "PASS cleanup: dry-run, exact orphan removal, durable intention, live outer-transaction commit/rollback races, repeat, recovery and current admin"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
