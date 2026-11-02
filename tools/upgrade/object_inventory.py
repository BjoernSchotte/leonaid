"""Write a byte-exact inventory of every object version in the RustFS store.

The upgrade test takes one inventory before and one after the RustFS image
swap and requires both files to be identical: same buckets, versioning state,
version ids, delete markers, sizes, ETags, metadata and SHA-256 of every
version's bytes. Usage: object_inventory.py OUTPUT_JSON
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config


def client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ["RUSTFS_ENDPOINT_URL"],
        aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def sha256_of(s3: Any, bucket: str, key: str, version_id: str) -> str:
    digest = hashlib.sha256()
    body = s3.get_object(Bucket=bucket, Key=key, VersionId=version_id)
    for chunk in iter(lambda: body["Body"].read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def bucket_inventory(s3: Any, bucket: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        for version in page.get("Versions", []):
            key, version_id = version["Key"], version["VersionId"]
            head = s3.head_object(Bucket=bucket, Key=key, VersionId=version_id)
            entries.append(
                {
                    "key": key,
                    "versionId": version_id,
                    "isLatest": version["IsLatest"],
                    "size": version["Size"],
                    "etag": version["ETag"],
                    "contentType": head.get("ContentType"),
                    "metadata": head.get("Metadata", {}),
                    "sha256": sha256_of(s3, bucket, key, version_id),
                }
            )
        for marker in page.get("DeleteMarkers", []):
            entries.append(
                {
                    "key": marker["Key"],
                    "versionId": marker["VersionId"],
                    "isLatest": marker["IsLatest"],
                    "deleteMarker": True,
                }
            )
    entries.sort(key=lambda entry: (entry["key"], entry["versionId"]))
    return {
        "versioning": s3.get_bucket_versioning(Bucket=bucket).get("Status"),
        "entries": entries,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: object_inventory.py OUTPUT_JSON")
    s3 = client()
    buckets = sorted(bucket["Name"] for bucket in s3.list_buckets()["Buckets"])
    inventory = {bucket: bucket_inventory(s3, bucket) for bucket in buckets}
    versions = sum(
        1
        for bucket in inventory.values()
        for entry in bucket["entries"]
        if not entry.get("deleteMarker")
    )
    if versions == 0:
        raise SystemExit("object-inventory: ERROR: the store holds no object versions")
    Path(sys.argv[1]).write_text(json.dumps(inventory, indent=1, sort_keys=True) + "\n")
    print(f"object-inventory: {len(buckets)} buckets, {versions} object versions hashed")


if __name__ == "__main__":
    main()
