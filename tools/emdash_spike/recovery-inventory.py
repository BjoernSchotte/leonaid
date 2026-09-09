"""Real SQL and object-byte proof; deliberately no restored-login claim."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

import asyncpg
import boto3
from botocore.config import Config

from tools.backup.inventory import database_inventory, file_inventory


async def main() -> None:
    mode, output = sys.argv[1:]
    assert mode in {"seed", "capture", "verify"}
    databases = {
        "core-fixture": (
            "core-postgres",
            "leonaid",
            "leonaid",
            "CORE_POSTGRES_PASSWORD",
        ),
        "twenty-fixture": (
            "twenty-postgres",
            "default",
            "twenty",
            "TWENTY_POSTGRES_PASSWORD",
        ),
        "cms": ("core-postgres", "emdash", "emdash", "CMS_POSTGRES_PASSWORD"),
    }
    snapshot = {}
    for label, (host, name, user, variable) in databases.items():
        url = (
            f"postgresql://{user}:{quote(os.environ[variable], safe='')}@{host}/{name}"
        )
        if mode == "seed" and label != "cms":
            database = await asyncpg.connect(url)
            try:
                await database.execute(
                    "CREATE TABLE recovery_proof (id integer PRIMARY KEY, value text NOT NULL)"
                )
                await database.execute(
                    "INSERT INTO recovery_proof VALUES (1, 'synthetic recovery data')"
                )
            finally:
                await database.close()
        snapshot[label] = await database_inventory(url, label=label)
    s3 = boto3.client(
        "s3",
        endpoint_url="http://rustfs:9000",
        aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    if mode == "seed":
        for bucket in ("emdash-media", "core-private"):
            s3.create_bucket(Bucket=bucket)
            s3.put_object(
                Bucket=bucket, Key="recovery.bin", Body=bytes(range(256)) * 1024
            )
    objects = {}
    for bucket in ("emdash-media", "core-private"):
        entries = {}
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                response = s3.get_object(Bucket=bucket, Key=item["Key"])
                with response["Body"] as body:
                    data = body.read()
                entries[item["Key"]] = {
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        assert entries
        objects[bucket] = entries
    snapshot["objects"] = objects
    snapshot["twenty-storage"] = file_inventory(Path("/twenty-storage"))
    assert snapshot["cms"]["tables"]["public.ec_campaign_pages"]["rows"] >= 2
    assert snapshot["cms"]["tables"]["public.revisions"]["rows"] >= 2
    path = Path(output)
    if mode == "verify":
        assert snapshot == json.loads(path.read_text())
        print(
            "recovery-inventory: SQL fixtures, actual CMS tables/revisions, CRM files and S3 object bytes match"
        )
    else:
        path.write_text(json.dumps(snapshot, sort_keys=True))
        path.chmod(0o600)
        print("recovery-inventory: synthetic recovery inventory captured")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print("recovery-inventory: failed; private state omitted", file=sys.stderr)
        raise SystemExit(1) from None
