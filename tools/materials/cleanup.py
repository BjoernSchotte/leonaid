#!/usr/bin/env python3
"""Inspect or remove one unreferenced material upload version. Dry-run by default."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

import asyncpg

from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.bootstrap.api import build_material_service
from leonaid.configuration import load_settings
from leonaid.domain.identity import IdentityPrincipal, UserAccount, AccountStatus
from leonaid.modules.materials.api import CleanupUpload


async def run(args: argparse.Namespace) -> None:
    settings = load_settings()
    pool = await asyncpg.create_pool(
        settings.core_database_url.get_secret_value(), min_size=1, max_size=1
    )
    assert pool is not None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id,email,display_name,status FROM user_account WHERE id=$1",
                args.actor,
            )
        if row is None:
            raise ValueError("Administratives Konto nicht gefunden.")
        actor = IdentityPrincipal(
            UserAccount(
                row["id"],
                row["email"],
                row["display_name"],
                AccountStatus(row["status"]),
            ),
            frozenset(),
            (),
        )
        storage = S3ObjectStorage(
            endpoint_url=str(settings.object_storage_endpoint_url),
            access_key=settings.object_storage_access_key.get_secret_value(),
            secret_key=settings.object_storage_secret_key.get_secret_value(),
            bucket=settings.object_storage_bucket,
            region=settings.object_storage_region,
            path_style=settings.object_storage_path_style,
        )
        affected = await build_material_service(pool, storage).cleanup_upload(
            actor,
            CleanupUpload(
                material_id=args.material,
                upload_id=args.upload,
                storage_version_id=args.storage_version,
                reason=args.reason,
                apply=args.apply,
            ),
        )
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "result": ("deleted" if args.apply else "would-delete")
                    if affected
                    else "already-absent",
                }
            )
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", type=UUID, required=True)
    parser.add_argument("--material", type=UUID, required=True)
    parser.add_argument("--upload", type=UUID, required=True)
    parser.add_argument("--storage-version", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))
