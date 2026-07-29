#!/usr/bin/env python3
"""Real PostgreSQL/RustFS/API contract for document discovery and access."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.adapters.storage import S3ObjectStorage
from leonaid.application.object_storage import (
    ObjectDeletionAuthorization,
    ObjectLocation,
)
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
FOREIGN_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
FOREIGN_ADMIN_ID = UUID("10000000-0000-4000-8000-000000000003")
ACQUIRER_ID = UUID("10000000-0000-4000-8000-000000000004")
FINANCE_ID = UUID("10000000-0000-4000-8000-000000000007")
INVOICE_ONE_ID = UUID("90000000-0000-4000-8000-000000000001")
INVOICE_TWO_ID = UUID("90000000-0000-4000-8000-000000000002")
INVOICE_THREE_ID = UUID("90000000-0000-4000-8000-000000000003")
COMMITMENT_ONE_ID = UUID("80000000-0000-4000-8000-000000000004")
COMPANY_ID = UUID("40000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("50000000-0000-4000-8000-000000000005")
SESSION_NAMESPACE = UUID("058c5830-f8bf-46d5-938f-71e25bfa6ef6")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc093-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(value["error"].get("code"))


def storage() -> S3ObjectStorage:
    return S3ObjectStorage(
        endpoint_url=require_env("OBJECT_STORAGE_ENDPOINT_URL"),
        access_key=require_env("OBJECT_STORAGE_ACCESS_KEY"),
        secret_key=require_env("OBJECT_STORAGE_SECRET_KEY"),
        bucket=require_env("OBJECT_STORAGE_BUCKET"),
        region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
    )


async def seed_sessions(
    connection: asyncpg.Connection[Any],
    output: Path,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    users = (
        ("ADMIN_SESSION", "admin", ADMIN_ID),
        ("FOREIGN_ADMIN_SESSION", "foreign_admin", FOREIGN_ADMIN_ID),
        ("ACQUIRER_SESSION", "acquirer", ACQUIRER_ID),
        ("FINANCE_SESSION", "finance", FINANCE_ID),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [user_id for _name, _label, user_id in users],
    )
    tokens: dict[str, str] = {}
    output_values: list[str] = []
    for env_name, label, user_id in users:
        token = token_for(label, user_id)
        tokens[label] = token
        output_values.append(f"{env_name}={token}\n")
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, device_hint,
                created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $5, 'POC-093 Dokumentabruf',
                $5, $5
            )
            """,
            uuid5(SESSION_NAMESPACE, label),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    output.write_text("".join(output_values), encoding="utf-8")
    output.chmod(0o600)
    return tokens


def assert_document_payload(
    value: object,
    row: asyncpg.Record,
) -> None:
    if not isinstance(value, dict):
        raise ContractFailure("Dokumentantwort ist kein Objekt")
    expected = {
        "id": str(row["id"]),
        "actionId": str(row["action_id"]),
        "commitmentId": str(row["commitment_id"]),
        "invoiceId": str(row["invoice_id"]),
        "twentyCompanyId": (
            str(row["twenty_company_id"])
            if row["twenty_company_id"] is not None
            else None
        ),
        "twentyPersonId": (
            str(row["twenty_person_id"])
            if row["twenty_person_id"] is not None
            else None
        ),
        "documentType": "invoice_pdf",
        "mediaType": "application/pdf",
        "filename": str(row["filename"]),
        "sizeBytes": int(row["size_bytes"]),
        "renderVersion": str(row["render_version"]),
        "version": int(row["version"]),
        "status": "available",
        "createdAt": row["created_at"].isoformat().replace("+00:00", "Z"),
        "availableAt": row["available_at"].isoformat().replace("+00:00", "Z"),
        "sentAt": None,
    }
    if value != expected:
        raise ContractFailure(
            "API-Metadaten weichen vom PostgreSQL-Dokumentstand ab: "
            f"{json.dumps(value, sort_keys=True)}"
        )
    private_fields = {
        "storageBucket",
        "objectKey",
        "storageVersionId",
        "sha256",
    }
    if private_fields.intersection(value):
        raise ContractFailure("Interne Speicherbezüge wurden an das Frontend geleakt")


async def assert_list(
    api: httpx.AsyncClient,
    connection: asyncpg.Connection[Any],
    *,
    path: str,
    token: str,
    reference_kind: str,
    reference_id: UUID,
    invoice_id: UUID,
) -> dict[str, object]:
    response = await api.get(path, headers=session_headers(token))
    response.raise_for_status()
    value = response.json()
    if (
        value.get("actionId") != str(ACTION_ID)
        or value.get("reference") != {"kind": reference_kind, "id": str(reference_id)}
        or len(value.get("items", [])) != 1
        or response.headers.get("cache-control") != "private, no-store"
    ):
        raise ContractFailure(f"Dokumentreferenz ist unvollständig: {path}")
    row = await connection.fetchrow(
        """
        SELECT *
        FROM generated_document
        WHERE action_id = $1
          AND invoice_id = $2
        """,
        ACTION_ID,
        invoice_id,
    )
    if row is None:
        raise ContractFailure("Golden-Dokument fehlt in PostgreSQL")
    item = value["items"][0]
    if not isinstance(item, dict):
        raise ContractFailure("Dokumentlisteneintrag ist kein Objekt")
    assert_document_payload(item.get("document"), row)
    if (
        item.get("invoiceNumber") != f"KT26-{str(invoice_id)[-1].zfill(4)}"
        or not str(item.get("buyerDisplayName", "")).strip()
    ):
        raise ContractFailure("Fachliche Dokumentbezeichnung fehlt")
    return item


async def assert_action_list(
    api: httpx.AsyncClient,
    connection: asyncpg.Connection[Any],
    *,
    token: str,
) -> list[dict[str, object]]:
    response = await api.get(
        f"/api/v1/actions/{ACTION_ID}/documents",
        headers=session_headers(token),
    )
    response.raise_for_status()
    value = response.json()
    items = value.get("items")
    if (
        value.get("reference") != {"kind": "action", "id": str(ACTION_ID)}
        or not isinstance(items, list)
        or len(items) != 3
    ):
        raise ContractFailure("Aktionskontext zeigt nicht alle drei Golden-Dokumente")
    rows = await connection.fetch(
        """
        SELECT *
        FROM generated_document
        WHERE action_id = $1
        ORDER BY created_at DESC, id
        """,
        ACTION_ID,
    )
    if len(rows) != 3:
        raise ContractFailure("PostgreSQL enthält nicht drei Golden-Dokumente")
    by_id = {
        str(item.get("document", {}).get("id")): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("document"), dict)
    }
    for row in rows:
        item = by_id.get(str(row["id"]))
        if item is None:
            raise ContractFailure("Aktionskontext verlor ein PostgreSQL-Dokument")
        assert_document_payload(item["document"], row)
    return items


async def assert_exact_bytes(
    api: httpx.AsyncClient,
    connection: asyncpg.Connection[Any],
    *,
    token: str,
    golden_pdf_directory: Path,
) -> None:
    object_storage = storage()
    for sequence, invoice_id in enumerate(
        (INVOICE_ONE_ID, INVOICE_TWO_ID, INVOICE_THREE_ID),
        start=1,
    ):
        row = await connection.fetchrow(
            "SELECT * FROM generated_document WHERE invoice_id = $1",
            invoice_id,
        )
        if row is None:
            raise ContractFailure("Dokument fehlt beim Bytevergleich")
        retrieved = await object_storage.get(
            ObjectLocation(
                bucket=str(row["storage_bucket"]),
                key=str(row["object_key"]),
                version_id=str(row["storage_version_id"]),
            )
        )
        golden = (golden_pdf_directory / f"KT26-{sequence:04d}.pdf").read_bytes()
        response = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{row['id']}/download",
            headers=session_headers(token),
        )
        digest = hashlib.sha256(golden).hexdigest()
        if (
            response.status_code != 200
            or response.content != golden
            or retrieved.content != golden
            or response.headers.get("content-type") != "application/pdf"
            or response.headers.get("x-document-sha256") != digest
            or response.headers.get("x-document-version") != "2"
        ):
            raise ContractFailure(
                "PostgreSQL, RustFS, Golden-PDF und API sind nicht byteidentisch"
            )


async def exercise(
    connection: asyncpg.Connection[Any],
    sessions_output: Path,
    golden_pdf_directory: Path,
) -> None:
    tokens = await seed_sessions(connection, sessions_output)
    assignment_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM acquisition_assignment
        WHERE action_id = $1
          AND acquirer_user_id = $2
          AND twenty_company_id = $3
        """,
        ACTION_ID,
        ACQUIRER_ID,
        COMPANY_ID,
    )
    if assignment_count != 1:
        raise ContractFailure(
            "Golden-Voraussetzung fehlt: Akquisiteur ist der Firma nicht zugeordnet"
        )

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        await assert_action_list(api, connection, token=tokens["admin"])
        await assert_action_list(api, connection, token=tokens["finance"])
        await assert_list(
            api,
            connection,
            path=(
                f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ONE_ID}/documents"
            ),
            token=tokens["admin"],
            reference_kind="commitment",
            reference_id=COMMITMENT_ONE_ID,
            invoice_id=INVOICE_ONE_ID,
        )
        await assert_list(
            api,
            connection,
            path=f"/api/v1/actions/{ACTION_ID}/invoices/{INVOICE_ONE_ID}/documents",
            token=tokens["finance"],
            reference_kind="invoice",
            reference_id=INVOICE_ONE_ID,
            invoice_id=INVOICE_ONE_ID,
        )
        await assert_list(
            api,
            connection,
            path=f"/api/v1/actions/{ACTION_ID}/crm/companies/{COMPANY_ID}/documents",
            token=tokens["admin"],
            reference_kind="twenty_company",
            reference_id=COMPANY_ID,
            invoice_id=INVOICE_TWO_ID,
        )
        await assert_list(
            api,
            connection,
            path=f"/api/v1/actions/{ACTION_ID}/crm/people/{PERSON_ID}/documents",
            token=tokens["finance"],
            reference_kind="twenty_person",
            reference_id=PERSON_ID,
            invoice_id=INVOICE_ONE_ID,
        )
        await assert_exact_bytes(
            api,
            connection,
            token=tokens["finance"],
            golden_pdf_directory=golden_pdf_directory,
        )

        acquirer_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/crm/companies/{COMPANY_ID}/documents",
            headers=session_headers(tokens["acquirer"]),
        )
        acquirer_download = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{INVOICE_TWO_ID}/download",
            headers=session_headers(tokens["acquirer"]),
        )
        foreign_admin = await api.get(
            f"/api/v1/actions/{FOREIGN_ACTION_ID}/documents",
            headers=session_headers(tokens["admin"]),
        )
        foreign_document = await api.get(
            (
                f"/api/v1/actions/{FOREIGN_ACTION_ID}/documents/"
                f"{INVOICE_ONE_ID}/download"
            ),
            headers=session_headers(tokens["foreign_admin"]),
        )
        if (
            acquirer_list.status_code != 403
            or error_code(acquirer_list) != "document_download_required"
            or acquirer_download.status_code != 403
            or error_code(acquirer_download) != "document_download_required"
            or foreign_admin.status_code != 403
            or error_code(foreign_admin) != "document_download_required"
            or foreign_document.status_code != 404
            or error_code(foreign_document) != "generated_document_not_found"
            or foreign_document.content.startswith(b"%PDF")
        ):
            raise ContractFailure(
                "Akquisiteurs- oder Fremdaktionsgrenze schützt Dokumente nicht"
            )
    print(
        "document-contract: OK: Aktion, Bestellung, Rechnung, Firma und Kontakt; "
        "Admin/Finanzen erlaubt, Akquise/Fremdaktion verweigert; Bytes exakt"
    )


async def assert_missing_object(connection: asyncpg.Connection[Any]) -> None:
    row = await connection.fetchrow(
        "SELECT * FROM generated_document WHERE invoice_id = $1",
        INVOICE_THREE_ID,
    )
    if row is None:
        raise ContractFailure("Dokument für kontrollierten Fehlfall fehlt")
    location = ObjectLocation(
        bucket=str(row["storage_bucket"]),
        key=str(row["object_key"]),
        version_id=str(row["storage_version_id"]),
    )
    object_storage = storage()
    await object_storage.delete(
        location,
        authorization=ObjectDeletionAuthorization(
            actor_user_id=ADMIN_ID,
            reason="POC-093 kontrollierter Test einer fehlenden Objektversion",
        ),
    )
    token = token_for("finance", FINANCE_ID)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        listed = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices/{INVOICE_THREE_ID}/documents",
            headers=session_headers(token),
        )
        listed.raise_for_status()
        response = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{row['id']}/download",
            headers=session_headers(token),
        )
    if (
        len(listed.json().get("items", [])) != 1
        or response.status_code != 503
        or error_code(response) != "generated_document_storage_missing"
        or response.headers.get("content-type") != "application/json"
        or not response.content
        or response.content.startswith(b"%PDF")
    ):
        raise ContractFailure(
            "Fehlende RustFS-Version ergab keinen diagnostizierbaren JSON-Fehler"
        )
    print(
        "document-contract: OK: fehlende RustFS-Version bleibt auffindbar und "
        "liefert Fehler generated_document_storage_missing statt Leerdownload"
    )


async def main(arguments: argparse.Namespace) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        if arguments.command == "exercise":
            await exercise(
                connection,
                arguments.sessions_output,
                arguments.golden_pdf_directory,
            )
        else:
            await assert_missing_object(connection)
    finally:
        await connection.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    exercise_command = commands.add_parser("exercise")
    exercise_command.add_argument("sessions_output", type=Path)
    exercise_command.add_argument("golden_pdf_directory", type=Path)
    commands.add_parser("assert-missing")
    return value


if __name__ == "__main__":
    asyncio.run(main(parser().parse_args()))
