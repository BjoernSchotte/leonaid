#!/usr/bin/env python3
"""Write secret-free metadata about real CI mail, storage and Golden Data."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import asyncpg
import boto3
import httpx

JsonObject = dict[str, Any]


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} fehlt")
    return value


async def database_diagnostic() -> JsonObject:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=5)
    try:
        async with connection.transaction(readonly=True):
            row = await connection.fetchrow(
                """
                SELECT dataset_version, dataset_sha256
                FROM golden_seed_snapshot
                ORDER BY dataset_version DESC
                LIMIT 1
                """
            )
            counts = await connection.fetchrow(
                """
                SELECT
                    (SELECT count(*) FROM user_account) AS users,
                    (SELECT count(*) FROM charity_action) AS actions,
                    (SELECT count(*) FROM acquisition_assignment) AS assignments
                """
            )
    finally:
        await connection.close()
    return {
        "status": "ready",
        "datasetVersion": None if row is None else row["dataset_version"],
        "datasetSha256": (None if row is None else str(row["dataset_sha256"]).strip()),
        "counts": {} if counts is None else dict(counts),
    }


async def mailpit_diagnostic() -> JsonObject:
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"),
        timeout=5,
    ) as client:
        response = await client.get("/api/v1/messages")
        response.raise_for_status()
        payload = response.json()
    messages = payload.get("messages", []) if isinstance(payload, dict) else []
    subjects = Counter(
        str(item.get("Subject", "(ohne Betreff)"))
        for item in messages
        if isinstance(item, dict)
    )
    return {
        "status": "ready",
        "total": len(messages),
        "subjectCounts": dict(sorted(subjects.items())),
    }


def storage_diagnostic() -> JsonObject:
    bucket = require_env("RUSTFS_BUCKET")
    client = boto3.client(
        "s3",
        endpoint_url=require_env("RUSTFS_ENDPOINT_URL"),
        aws_access_key_id=require_env("RUSTFS_ACCESS_KEY"),
        aws_secret_access_key=require_env("RUSTFS_SECRET_KEY"),
        region_name="us-east-1",
    )
    response = client.list_objects_v2(Bucket=bucket, MaxKeys=100)
    objects = response.get("Contents", [])
    return {
        "status": "ready",
        "objectCount": len(objects),
        "objects": [
            {
                "key": str(item.get("Key")),
                "size": int(item.get("Size", 0)),
            }
            for item in objects
            if isinstance(item, dict)
        ],
    }


async def run(output: Path) -> None:
    result: JsonObject = {}
    for label, probe in (
        ("database", database_diagnostic),
        ("mailpit", mailpit_diagnostic),
    ):
        try:
            result[label] = await probe()
        except Exception as error:  # noqa: BLE001 - diagnostics must continue
            result[label] = {"status": "unavailable", "errorType": type(error).__name__}
    try:
        result["rustfs"] = storage_diagnostic()
    except Exception as error:  # noqa: BLE001 - diagnostics must continue
        result["rustfs"] = {
            "status": "unavailable",
            "errorType": type(error).__name__,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.output))


if __name__ == "__main__":
    main()
