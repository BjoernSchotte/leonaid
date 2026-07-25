#!/usr/bin/env python3
"""Write and verify real Golden Data through PostgreSQL and RustFS."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import asyncpg
import boto3
from botocore.exceptions import ClientError

OBJECT_KEY = "platform-proof/golden-v1/dataset.json"


def load_fixture(fixture: Path) -> tuple[str, bytes, dict[str, Any], str]:
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
    dataset_bytes = (fixture / "dataset.json").read_bytes()
    dataset = json.loads(dataset_bytes)
    digest = hashlib.sha256(dataset_bytes).hexdigest()
    return str(manifest["datasetVersion"]), dataset_bytes, dataset, digest


async def write_postgres(version: str, dataset: dict[str, Any], digest: str) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_golden_probe (
                dataset_version text PRIMARY KEY,
                dataset_sha256 char(64) NOT NULL,
                dataset_payload jsonb NOT NULL
            )
            """
        )
        await connection.execute(
            """
            INSERT INTO platform_golden_probe (
                dataset_version,
                dataset_sha256,
                dataset_payload
            )
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (dataset_version) DO UPDATE
            SET dataset_sha256 = EXCLUDED.dataset_sha256,
                dataset_payload = EXCLUDED.dataset_payload
            """,
            version,
            digest,
            json.dumps(dataset, separators=(",", ":"), sort_keys=True),
        )
    finally:
        await connection.close()


async def verify_postgres(version: str, dataset: dict[str, Any], digest: str) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        row = await connection.fetchrow(
            """
            SELECT dataset_sha256, dataset_payload::text
            FROM platform_golden_probe
            WHERE dataset_version = $1
            """,
            version,
        )
    finally:
        await connection.close()
    if row is None:
        raise RuntimeError("Golden Data row is missing from core PostgreSQL")
    if row["dataset_sha256"].strip() != digest:
        raise RuntimeError("Golden Data hash changed in core PostgreSQL")
    if json.loads(row["dataset_payload"]) != dataset:
        raise RuntimeError("Golden Data payload changed in core PostgreSQL")


def s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ["RUSTFS_ENDPOINT_URL"],
        aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
        region_name="us-east-1",
    )


def write_rustfs(dataset_bytes: bytes, digest: str) -> None:
    client = s3_client()
    bucket = os.environ["RUSTFS_BUCKET"]
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status_code != 404:
            raise
        client.create_bucket(Bucket=bucket)
    client.put_object(
        Bucket=bucket,
        Key=OBJECT_KEY,
        Body=dataset_bytes,
        ContentType="application/json",
        Metadata={"sha256": digest, "dataset-version": "1.0.0"},
    )


def verify_rustfs(dataset_bytes: bytes, digest: str) -> None:
    response = s3_client().get_object(
        Bucket=os.environ["RUSTFS_BUCKET"],
        Key=OBJECT_KEY,
    )
    stored = response["Body"].read()
    if stored != dataset_bytes:
        raise RuntimeError("Golden Data object changed in RustFS")
    if response.get("Metadata", {}).get("sha256") != digest:
        raise RuntimeError("Golden Data metadata hash changed in RustFS")


async def run(command: str, fixture: Path) -> None:
    version, dataset_bytes, dataset, digest = load_fixture(fixture)
    if command == "write":
        await write_postgres(version, dataset, digest)
        write_rustfs(dataset_bytes, digest)
    else:
        await verify_postgres(version, dataset, digest)
        verify_rustfs(dataset_bytes, digest)
    print(f"persistence-probe: OK: {command}: Golden Data {version} sha256={digest}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "verify"))
    parser.add_argument("fixture", type=Path)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.command, arguments.fixture))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
