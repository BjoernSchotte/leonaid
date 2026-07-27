#!/usr/bin/env python3
"""Real invoice-render/upload/retry/authorization contract for POC-092."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.adapters.storage import S3ObjectStorage
from leonaid.application.object_storage import (
    ObjectLocation,
    ObjectStorageConflict,
    ObjectWrite,
)
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMITMENT_ID = UUID("80000000-0000-4000-8000-000000000002")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
ACQUIRER_ID = UUID("10000000-0000-4000-8000-000000000004")
FINANCE_ID = UUID("10000000-0000-4000-8000-000000000007")
SESSION_NAMESPACE = UUID("3795b5b9-89ad-47ea-8104-038271f5d8bd")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc092-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(value["error"].get("code"))


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    users = (
        ("admin", ADMIN_ID),
        ("acquirer", ACQUIRER_ID),
        ("finance", FINANCE_ID),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [user_id for _label, user_id in users],
    )
    tokens: dict[str, str] = {}
    for label, user_id in users:
        token = token_for(label, user_id)
        tokens[label] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, device_hint,
                created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $5, 'POC-092 Storage Contract',
                $5, $5
            )
            """,
            uuid5(SESSION_NAMESPACE, label),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    return tokens


async def prepare(connection: asyncpg.Connection[Any], state_path: Path) -> None:
    tokens = await seed_sessions(connection)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        response = await api.post(
            f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ID}/invoice",
            headers={
                **session_headers(tokens["admin"]),
                "Idempotency-Key": "poc092:invoice:render-storage",
                "X-Request-ID": "poc092:invoice:render-storage",
            },
            json={"serviceOn": "2026-11-15"},
        )
        response.raise_for_status()
        invoice = response.json()
        if invoice.get("number") != "KT26-0004":
            raise ContractFailure("POC-092 erhielt nicht die nächste Rechnungsnummer")
        invoice_id = UUID(str(invoice["id"]))
        row = await connection.fetchrow(
            """
            SELECT
                document.*,
                event.id AS outbox_id,
                event.status AS outbox_status,
                event.attempts AS outbox_attempts
            FROM generated_document AS document
            JOIN outbox_event AS event
              ON event.aggregate_type = 'generated_document'
             AND event.aggregate_id = document.id
             AND event.event_type = 'invoice.document.render.requested.v1'
            WHERE document.invoice_id = $1
            """,
            invoice_id,
        )
        if row is None:
            raise ContractFailure(
                "Rechnung, Pending-Dokument und Outbox sind nicht atomar"
            )
        if (
            row["status"] != "pending"
            or row["outbox_status"] != "pending"
            or row["outbox_attempts"] != 0
            or any(
                row[column] is not None
                for column in (
                    "filename",
                    "storage_bucket",
                    "object_key",
                    "storage_version_id",
                    "size_bytes",
                    "sha256",
                    "render_version",
                    "available_at",
                )
            )
        ):
            raise ContractFailure(
                "Vor dem Worker-Erfolg besitzt das Dokument bereits Speicher-Metadaten"
            )
        document_id = row["id"]
        finance_pending = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
            headers=session_headers(tokens["finance"]),
        )
        if (
            finance_pending.status_code != 404
            or error_code(finance_pending) != "generated_document_not_found"
        ):
            raise ContractFailure("Pending-Dokument wurde als Download ausgeliefert")
        acquirer_pending = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
            headers=session_headers(tokens["acquirer"]),
        )
        if (
            acquirer_pending.status_code != 403
            or error_code(acquirer_pending) != "document_download_required"
        ):
            raise ContractFailure("Akquisiteur erhielt Finanzdokument-Zugriff")

    state = {
        "invoiceId": str(invoice_id),
        "documentId": str(document_id),
        "outboxId": str(row["outbox_id"]),
        "tokens": tokens,
    }
    state_path.write_text(
        json.dumps(state, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    state_path.chmod(0o600)
    print(
        "storage-workflow: PREPARED: Rechnung, Pending-Dokument und Outbox "
        "atomar; Rollen vor Verarbeitung geprüft"
    )


def read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("tokens"), dict):
        raise ContractFailure("POC-092-Zustandsdatei ist ungültig")
    return value


async def assert_failed(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    state = read_state(state_path)
    row = await connection.fetchrow(
        """
        SELECT
            document.*,
            event.status AS outbox_status,
            event.attempts AS outbox_attempts,
            event.last_error_code,
            event.last_error_detail,
            event.available_at AS outbox_available_at
        FROM generated_document AS document
        JOIN outbox_event AS event ON event.id = $2
        WHERE document.id = $1
        """,
        UUID(str(state["documentId"])),
        UUID(str(state["outboxId"])),
    )
    if row is None:
        raise ContractFailure("Fehlgeschlagener Renderauftrag ist verschwunden")
    if (
        row["status"] != "pending"
        or row["outbox_status"] != "pending"
        or row["outbox_attempts"] != 1
        or row["last_error_code"] != "objectstorageunavailable"
        or row["outbox_available_at"] > datetime.now(timezone.utc)
        or any(
            row[column] is not None
            for column in (
                "filename",
                "storage_bucket",
                "object_key",
                "storage_version_id",
                "size_bytes",
                "sha256",
                "render_version",
                "available_at",
            )
        )
    ):
        raise ContractFailure(
            "RustFS-Ausfall hinterließ fälschlich Erfolg oder keinen Retry-Zustand"
        )
    detail = str(row["last_error_detail"])
    if require_env("OBJECT_STORAGE_SECRET_KEY") in detail:
        raise ContractFailure("Outbox-Fehlertext enthält Storage-Zugangsdaten")
    print(
        "storage-workflow: FAILURE PROVED: physisch gestopptes RustFS, "
        "kein Erfolgsstatus, Job pending und wiederholbar"
    )


def storage() -> S3ObjectStorage:
    return S3ObjectStorage(
        endpoint_url=require_env("OBJECT_STORAGE_ENDPOINT_URL"),
        access_key=require_env("OBJECT_STORAGE_ACCESS_KEY"),
        secret_key=require_env("OBJECT_STORAGE_SECRET_KEY"),
        bucket=require_env("OBJECT_STORAGE_BUCKET"),
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
    )


async def assert_success(
    connection: asyncpg.Connection[Any],
    state_path: Path,
    pdf_path: Path,
) -> None:
    state = read_state(state_path)
    document_id = UUID(str(state["documentId"]))
    row = await connection.fetchrow(
        """
        SELECT
            document.*,
            event.status AS outbox_status,
            event.attempts AS outbox_attempts,
            event.completed_at AS outbox_completed_at
        FROM generated_document AS document
        JOIN outbox_event AS event ON event.id = $2
        WHERE document.id = $1
        """,
        document_id,
        UUID(str(state["outboxId"])),
    )
    if row is None:
        raise ContractFailure("Erfolgreicher Renderauftrag ist verschwunden")
    required = (
        "filename",
        "storage_bucket",
        "object_key",
        "storage_version_id",
        "size_bytes",
        "sha256",
        "render_version",
        "available_at",
    )
    if (
        row["status"] != "available"
        or row["outbox_status"] != "completed"
        or row["outbox_attempts"] != 2
        or row["outbox_completed_at"] is None
        or any(row[column] is None for column in required)
    ):
        raise ContractFailure(
            "Wiederholter Renderauftrag wurde nicht vollständig abgeschlossen"
        )
    location = ObjectLocation(
        bucket=str(row["storage_bucket"]),
        key=str(row["object_key"]),
        version_id=str(row["storage_version_id"]),
    )
    object_storage = storage()
    retrieved = await object_storage.get(location)
    digest = hashlib.sha256(retrieved.content).hexdigest()
    if (
        digest != row["sha256"]
        or retrieved.stored.size_bytes != row["size_bytes"]
        or retrieved.stored.media_type != "application/pdf"
        or not retrieved.content.startswith(b"%PDF-")
    ):
        raise ContractFailure(
            "RustFS-Objekt und GeneratedDocument weichen voneinander ab"
        )

    tokens = {str(key): str(value) for key, value in state["tokens"].items()}
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        for role in ("admin", "finance"):
            response = await api.get(
                f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
                headers=session_headers(tokens[role]),
            )
            if (
                response.status_code != 200
                or response.content != retrieved.content
                or response.headers.get("x-document-sha256") != digest
                or response.headers.get("cache-control") != "private, no-store"
                or "attachment;" not in response.headers.get("content-disposition", "")
            ):
                raise ContractFailure(
                    f"{role}: geschützter Core-Download ist nicht byteidentisch"
                )
        inline = await api.get(
            (
                f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download"
                "?inline=true"
            ),
            headers=session_headers(tokens["finance"]),
        )
        if (
            inline.status_code != 200
            or inline.content != retrieved.content
            or "inline;" not in inline.headers.get("content-disposition", "")
        ):
            raise ContractFailure("Geschützte Core-Vorschau ist nicht byteidentisch")
        forbidden = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
            headers=session_headers(tokens["acquirer"]),
        )
        forbidden_text = forbidden.text.casefold()
        if (
            forbidden.status_code != 403
            or error_code(forbidden) != "document_download_required"
            or forbidden.content.startswith(b"%PDF-")
            or any(
                secret in forbidden_text
                for secret in (
                    "http://",
                    "https://",
                    "object_key",
                    "versionid",
                    "sha256",
                )
            )
        ):
            raise ContractFailure(
                "Unberechtigte Persona erhielt Objekt, Speicherbezug oder signierte URL"
            )
        endpoint = require_env("OBJECT_STORAGE_ENDPOINT_URL").rstrip("/")
        anonymous = await api.get(
            f"{endpoint}/{quote(location.bucket)}/{quote(location.key, safe='/')}"
        )
        if anonymous.status_code not in {401, 403, 404}:
            raise ContractFailure("Rechnungsobjekt ist ohne S3-Signatur öffentlich")

    original_key = str(row["object_key"])
    try:
        await connection.execute(
            "UPDATE generated_document SET object_key = $2 WHERE id = $1",
            document_id,
            f"{original_key}.replaced",
        )
    except asyncpg.PostgresError:
        pass
    else:
        raise ContractFailure("Datenbank erlaubte Austausch eines verfügbaren PDFs")
    await connection.execute(
        "UPDATE generated_document SET sent_at = CURRENT_TIMESTAMP WHERE id = $1",
        document_id,
    )
    for statement in (
        "UPDATE generated_document SET sha256 = repeat('0', 64) WHERE id = $1",
        "DELETE FROM generated_document WHERE id = $1",
    ):
        try:
            await connection.execute(statement, document_id)
        except asyncpg.PostgresError:
            pass
        else:
            raise ContractFailure("Versandter Beleg war in der Datenbank veränderbar")

    changed = retrieved.content + b"\n% forbidden replacement after send\n"
    try:
        await object_storage.put_immutable(
            ObjectWrite(
                location=ObjectLocation(
                    bucket=location.bucket,
                    key=location.key,
                ),
                content=changed,
                media_type="application/pdf",
                sha256=hashlib.sha256(changed).hexdigest(),
                metadata={
                    "document-id": str(document_id),
                    "contract": "forbidden-replacement",
                },
            )
        )
    except ObjectStorageConflict:
        pass
    else:
        raise ContractFailure("Storage-Port überschrieb einen versandten Object Key")
    if (await object_storage.get(location)).content != retrieved.content:
        raise ContractFailure("Versandte Objektversion wurde physisch verändert")

    audit_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM audit_event
        WHERE entity_type = 'generated_document'
          AND entity_id = $1
          AND event_type = 'generated_document_available'
        """,
        document_id,
    )
    if audit_count != 1:
        raise ContractFailure(
            "Dokumenterzeugung besitzt keinen eindeutigen Audit-Nachweis"
        )
    pdf_path.write_bytes(retrieved.content)
    print(
        "storage-workflow: SUCCESS: Retry, byteidentischer Core-Download, "
        "Rollen, private Ablage und Versand-Immutabilität bewiesen"
    )


async def execute(arguments: argparse.Namespace) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        if arguments.command == "prepare":
            await prepare(connection, arguments.state)
        elif arguments.command == "assert-failed":
            await assert_failed(connection, arguments.state)
        elif arguments.command == "assert-success":
            await assert_success(connection, arguments.state, arguments.pdf)
        else:
            raise ContractFailure(f"Unbekannter Befehl: {arguments.command}")
    finally:
        await connection.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    subcommands = value.add_subparsers(dest="command", required=True)
    for name in ("prepare", "assert-failed"):
        command = subcommands.add_parser(name)
        command.add_argument("state", type=Path)
    success = subcommands.add_parser("assert-success")
    success.add_argument("state", type=Path)
    success.add_argument("pdf", type=Path)
    return value


if __name__ == "__main__":
    asyncio.run(execute(parser().parse_args()))
