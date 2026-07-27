#!/usr/bin/env python3
"""Provider-neutral contract against two real S3-compatible servers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import httpx

from leonaid.adapters.storage import S3ObjectStorage
from leonaid.adapters.typst import TypstInvoiceRenderer
from leonaid.application.invoice_documents import InvoiceDocumentSnapshot
from leonaid.application.object_storage import (
    ObjectDeletionAuthorization,
    ObjectLocation,
    ObjectStorageConflict,
    ObjectWrite,
)

OPERATOR_ID = UUID("10000000-0000-4000-8000-000000000001")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def storage_credential(name: str, fallback: str) -> str:
    value = os.environ.get(name) or os.environ.get(fallback)
    if not value:
        raise ContractFailure(f"Storage-Zugang fehlt: {name}/{fallback}")
    return value


def load_snapshot(path: Path) -> InvoiceDocumentSnapshot:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractFailure("Golden-Rechnung ist kein JSON-Objekt")
    return InvoiceDocumentSnapshot.from_payload(value)


async def exercise(
    *,
    provider: str,
    endpoint_url: str,
    bucket: str,
    content: bytes,
    media_type: str,
    sha256: str,
) -> None:
    storage = S3ObjectStorage(
        endpoint_url=endpoint_url,
        access_key=storage_credential(
            "STORAGE_ACCESS_KEY", "OBJECT_STORAGE_ACCESS_KEY"
        ),
        secret_key=storage_credential(
            "STORAGE_SECRET_KEY", "OBJECT_STORAGE_SECRET_KEY"
        ),
        bucket=bucket,
    )
    await storage.ensure_private_versioned_bucket()
    key = f"contracts/poc092/{provider}/{sha256}.pdf"
    write = ObjectWrite(
        location=ObjectLocation(bucket=bucket, key=key),
        content=content,
        media_type=media_type,
        sha256=sha256,
        metadata={
            "contract": "poc092",
            "provider": provider,
        },
    )
    stored = await storage.put_immutable(write)
    if not stored.location.version_id:
        raise ContractFailure(f"{provider}: Version-ID fehlt")
    if await storage.put_immutable(write) != stored:
        raise ContractFailure(f"{provider}: idempotentes Put änderte die Version")
    headed = await storage.head(stored.location)
    if headed != stored:
        raise ContractFailure(f"{provider}: Head bewahrt Metadaten nicht")
    retrieved = await storage.get(stored.location)
    if retrieved.content != content or retrieved.stored != stored:
        raise ContractFailure(f"{provider}: Get bewahrt Bytes/Metadaten nicht")

    signed_url = await storage.protected_download_url(
        stored.location,
        expires_in=timedelta(seconds=60),
    )
    if "X-Amz-Signature=" not in signed_url or "versionId=" not in signed_url:
        raise ContractFailure(
            f"{provider}: geschützte URL ist nicht signiert/versioniert"
        )
    async with httpx.AsyncClient(timeout=30) as client:
        signed = await client.get(signed_url)
        if signed.status_code != 200 or signed.content != content:
            raise ContractFailure(
                f"{provider}: signierter Download ist nicht byteidentisch"
            )
        anonymous = await client.get(
            f"{endpoint_url.rstrip('/')}/{quote(bucket)}/{quote(key, safe='/')}"
        )
        if anonymous.status_code not in {401, 403, 404} or anonymous.content == content:
            raise ContractFailure(f"{provider}: Bucket/Object ist öffentlich lesbar")

    changed = content + b"\n% forbidden replacement\n"
    try:
        await storage.put_immutable(
            ObjectWrite(
                location=write.location,
                content=changed,
                media_type=media_type,
                sha256=hashlib.sha256(changed).hexdigest(),
                metadata=write.metadata,
            )
        )
    except ObjectStorageConflict:
        pass
    else:
        raise ContractFailure(f"{provider}: unveränderlicher Key wurde überschrieben")
    if (await storage.get(stored.location)).content != content:
        raise ContractFailure(f"{provider}: Kollision veränderte Originalversion")

    try:
        await storage.head(
            ObjectLocation(
                bucket=f"{bucket}-foreign",
                key=key,
                version_id=stored.location.version_id,
            )
        )
    except ObjectStorageConflict:
        pass
    else:
        raise ContractFailure(f"{provider}: Zugriff auf fremden Bucket wurde erlaubt")

    delete_key = f"contracts/poc092/{provider}/controlled-delete-{sha256}.pdf"
    deletable = await storage.put_immutable(
        ObjectWrite(
            location=ObjectLocation(bucket=bucket, key=delete_key),
            content=content,
            media_type=media_type,
            sha256=sha256,
            metadata=write.metadata,
        )
    )
    await storage.delete(
        deletable.location,
        authorization=ObjectDeletionAuthorization(
            actor_user_id=OPERATOR_ID,
            reason="POC-092 Vertragsobjekt nach erfolgreicher Prüfung entfernen",
        ),
    )
    if await storage.head(deletable.location) is not None:
        raise ContractFailure(f"{provider}: kontrollierte Löschung blieb sichtbar")
    print(
        f"storage-contract: {provider}: Put/Head/Get/Version/Signatur/"
        "Privatheit/Immutabilität/Löschung OK"
    )


async def main(arguments: argparse.Namespace) -> None:
    rendered = TypstInvoiceRenderer().render(load_snapshot(arguments.snapshot))
    providers = (
        (
            "rustfs",
            require_env("RUSTFS_CONTRACT_ENDPOINT_URL"),
            require_env("RUSTFS_CONTRACT_BUCKET"),
        ),
        (
            "seaweedfs",
            require_env("SEAWEEDFS_CONTRACT_ENDPOINT_URL"),
            require_env("SEAWEEDFS_CONTRACT_BUCKET"),
        ),
    )
    for provider, endpoint, bucket in providers:
        await exercise(
            provider=provider,
            endpoint_url=endpoint,
            bucket=bucket,
            content=rendered.content,
            media_type=rendered.media_type,
            sha256=rendered.sha256,
        )
    print("storage-contract: OK: zwei echte S3-kompatible Implementierungen")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("snapshot", type=Path)
    return value


if __name__ == "__main__":
    asyncio.run(main(parser().parse_args()))
