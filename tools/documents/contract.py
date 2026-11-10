#!/usr/bin/env python3
"""Real PostgreSQL/RustFS/API contract for document discovery and access."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.adapters.storage import S3ObjectStorage
from leonaid.adapters.typst import (
    CANCELLATION_RENDER_VERSION,
    PLEDGE_RENDER_VERSION,
    TypstDonationPledgeRenderer,
    TypstInvoiceCancellationRenderer,
)
from leonaid.application.object_storage import (
    ObjectDeletionAuthorization,
    ObjectLocation,
)
from leonaid.domain.donations import DonationPledgeDocument
from leonaid.domain.invoice_cancellation_documents import InvoiceCancellationDocument
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
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc093-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Error response has no stable contract")
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
        raise ContractFailure("Document response is not an object")
    expected = {
        "id": str(row["id"]),
        "actionId": str(row["action_id"]),
        "commitmentId": str(row["commitment_id"]),
        "invoiceId": str(row["invoice_id"]),
        "donationId": None,
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
            "API metadata differs from the PostgreSQL document state: "
            f"{json.dumps(value, sort_keys=True)}"
        )
    private_fields = {
        "storageBucket",
        "objectKey",
        "storageVersionId",
        "sha256",
    }
    if private_fields.intersection(value):
        raise ContractFailure("Internal storage references leaked to the frontend")


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
        raise ContractFailure(f"Document reference is incomplete: {path}")
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
        raise ContractFailure("Golden document is missing in PostgreSQL")
    item = value["items"][0]
    if not isinstance(item, dict):
        raise ContractFailure("Document list entry is not an object")
    assert_document_payload(item.get("document"), row)
    if (
        item.get("invoiceNumber") != f"KT26-{str(invoice_id)[-1].zfill(4)}"
        or not str(item.get("buyerDisplayName", "")).strip()
    ):
        raise ContractFailure("Domain document label is missing")
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
        raise ContractFailure("Action context does not show all three golden documents")
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
        raise ContractFailure("PostgreSQL does not contain three golden documents")
    by_id = {
        str(item.get("document", {}).get("id")): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("document"), dict)
    }
    for row in rows:
        item = by_id.get(str(row["id"]))
        if item is None:
            raise ContractFailure("Action context lost a PostgreSQL document")
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
            raise ContractFailure("Document is missing for the byte comparison")
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
        # The preview link of the invoice pane opens the same bytes inline.
        preview = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{row['id']}/download",
            params={"inline": "true"},
            headers=session_headers(token),
        )
        digest = hashlib.sha256(golden).hexdigest()
        filename = f"filename*=UTF-8''Rechnung-KT26-{sequence:04d}.pdf"
        if (
            response.status_code != 200
            or response.content != golden
            or retrieved.content != golden
            or response.headers.get("content-type") != "application/pdf"
            or response.headers.get("x-document-sha256") != digest
            or response.headers.get("x-document-version") != "2"
            or response.headers.get("content-disposition") != f"attachment; {filename}"
        ):
            raise ContractFailure(
                "PostgreSQL, RustFS, golden PDF and API are not byte-identical"
            )
        if (
            preview.status_code != 200
            or preview.content != golden
            or preview.headers.get("content-disposition") != f"inline; {filename}"
        ):
            raise ContractFailure("Inline PDF preview differs from the download")


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
            "Golden precondition missing: acquirer is not assigned to the company"
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
                "Acquirer or foreign-action boundary does not protect documents"
            )
    print(
        "document-contract: OK: action, order, invoice, company and contact; "
        "admin/finance allowed, acquirer/foreign action denied; bytes exact"
    )


async def cancellation_invoice(connection: asyncpg.Connection[Any]) -> None:
    """The real worker renders and stores a cancellation invoice.

    The golden invoice KT26-0003 was cancelled before cancellation invoices
    existed. A manager issues the document; the worker renders the stored
    snapshot with the `invoice-cancellation-v1` template, stores it and the
    API serves exactly those bytes.
    """

    token = token_for("admin", ADMIN_ID)
    path = f"/api/v1/actions/{ACTION_ID}/invoices/{INVOICE_THREE_ID}"
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        issued = await api.post(
            f"{path}/cancellation/document",
            headers={
                **session_headers(token),
                "Idempotency-Key": "poc093:cancellation-document",
            },
        )
        if issued.status_code != 201:
            raise ContractFailure(
                f"Cancellation invoice was not issued: {issued.status_code} "
                f"{issued.text}"
            )
        number = str(issued.json()["number"])
        # The next number of the invoice series after KT26-0001 to -0003.
        if number != "KT26-0004" or issued.json()["issuedOn"] is None:
            raise ContractFailure(f"Unexpected cancellation number: {number}")
        document: dict[str, Any] | None = None
        for _attempt in range(90):
            listing = await api.get(f"{path}/documents", headers=session_headers(token))
            listing.raise_for_status()
            document = next(
                (
                    item
                    for item in listing.json()["items"]
                    if item["document"]["documentType"] == "invoice_cancellation_pdf"
                ),
                None,
            )
            if document is not None and document["document"]["status"] == "available":
                break
            await asyncio.sleep(1)
        else:
            raise ContractFailure("The worker did not render the cancellation invoice")
        if (
            document is None
            or document["documentNumber"] != number
            or document["invoiceNumber"] != "KT26-0003"
            or document["document"]["filename"] != f"Stornorechnung-{number}.pdf"
            or document["document"]["renderVersion"] != CANCELLATION_RENDER_VERSION
        ):
            raise ContractFailure("Cancellation document metadata is wrong")
        document_id = document["document"]["id"]
        download = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
            headers=session_headers(token),
        )
        acquirer = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
            headers=session_headers(token_for("acquirer", ACQUIRER_ID)),
        )

    row = await connection.fetchrow(
        """
        SELECT document.*, cancellation.id AS cancellation_id,
               cancellation.snapshot
        FROM generated_document AS document
        JOIN invoice_cancellation AS cancellation
          ON cancellation.invoice_id = document.invoice_id
        WHERE document.id = $1
        """,
        UUID(document_id),
    )
    if row is None:
        raise ContractFailure("The cancellation document row is missing")
    snapshot = InvoiceCancellationDocument.from_payload(json.loads(row["snapshot"]))
    # Deterministic: rendering the stored snapshot again gives the same bytes.
    expected = TypstInvoiceCancellationRenderer().render(snapshot)
    retrieved = await storage().get(
        ObjectLocation(
            bucket=str(row["storage_bucket"]),
            key=str(row["object_key"]),
            version_id=str(row["storage_version_id"]),
        )
    )
    expected_key = (
        f"actions/{ACTION_ID}/invoices/{INVOICE_THREE_ID}/cancellations/"
        f"{row['cancellation_id']}/v1/{expected.sha256}.pdf"
    )
    filename = f"filename*=UTF-8''Stornorechnung-{number}.pdf"
    if (
        download.status_code != 200
        or download.content != expected.content
        or retrieved.content != expected.content
        or str(row["object_key"]) != expected_key
        or str(row["sha256"]) != expected.sha256
        or download.headers.get("content-type") != "application/pdf"
        or download.headers.get("x-document-sha256") != expected.sha256
        or download.headers.get("content-disposition") != f"attachment; {filename}"
    ):
        raise ContractFailure(
            "Snapshot, renderer, RustFS and API disagree on the cancellation invoice"
        )
    if snapshot.original_number != "KT26-0003" or snapshot.number != number:
        raise ContractFailure("The cancellation invoice names the wrong invoice")
    if (
        acquirer.status_code != 403
        or error_code(acquirer) != "document_download_required"
    ):
        raise ContractFailure("An acquirer could download the cancellation invoice")
    untouched = await connection.fetchrow(
        "SELECT number, status FROM invoice WHERE id = $1", INVOICE_THREE_ID
    )
    if untouched is None or (untouched["number"], untouched["status"]) != (
        "KT26-0003",
        "cancelled",
    ):
        raise ContractFailure("Issuing the cancellation invoice changed the invoice")
    print(
        f"document-contract: OK: cancellation invoice {number} issued, rendered "
        "by the worker, stored and served byte-identical"
    )


DONOR_EMAIL = "spenderin.poc093@donor.leonaid.invalid"


async def donation_pledge(connection: asyncpg.Connection[Any]) -> None:
    """The real worker renders, stores and mails a donation pledge.

    A manager records a donation in the golden action. It takes the first
    number of the donation series; the worker renders the frozen pledge with
    the `donation-pledge-v1` template; the API serves exactly those bytes and
    the mail to the donor carries them.
    """

    token = token_for("admin", ADMIN_ID)
    headers = session_headers(token)
    path = f"/api/v1/actions/{ACTION_ID}/donations"
    async with (
        httpx.AsyncClient(
            base_url=require_env("API_BASE_URL").rstrip("/"), timeout=60
        ) as api,
        httpx.AsyncClient(
            base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=10
        ) as mailpit,
    ):
        created = await api.post(
            path,
            headers={**headers, "Idempotency-Key": "poc093:donation"},
            json={
                "donor": {
                    "name": "Spenderin POC-093",
                    "streetLine1": "Gartenweg 4",
                    "postalCode": "12345",
                    "city": "Musterstadt",
                    "email": DONOR_EMAIL,
                },
                "pledgedMinor": 5000,
            },
        )
        if created.status_code != 201:
            raise ContractFailure(
                f"Donation was not recorded: {created.status_code} {created.text}"
            )
        donation = created.json()
        number = str(donation["number"])
        if number != "SP26-0001" or donation["status"] != "pledged":
            raise ContractFailure(f"Unexpected donation: {number}")
        record: dict[str, Any] = donation
        for _attempt in range(90):
            listing = await api.get(path, headers=headers)
            listing.raise_for_status()
            record = next(
                item for item in listing.json()["items"] if item["id"] == donation["id"]
            )
            if record["pledgeDocument"]["status"] == "available":
                break
            await asyncio.sleep(1)
        else:
            raise ContractFailure("The worker did not render the donation pledge")
        if listing.json()["receivingBodyName"] != (
            "Förderverein Lions Club Musterstadt e. V."
        ):
            raise ContractFailure("The donation list names the wrong receiving body")
        document_id = record["pledgeDocument"]["id"]
        if record["pledgeDocument"]["filename"] != f"Spendenzusage-{number}.pdf":
            raise ContractFailure("The pledge PDF has the wrong filename")
        download = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
            headers=headers,
        )
        acquirer = await api.get(
            f"/api/v1/actions/{ACTION_ID}/documents/{document_id}/download",
            headers=session_headers(token_for("acquirer", ACQUIRER_ID)),
        )
        foreign = await api.get(
            f"/api/v1/actions/{FOREIGN_ACTION_ID}/documents/{document_id}/download",
            headers=session_headers(token_for("foreign_admin", FOREIGN_ADMIN_ID)),
        )
        cleared = await mailpit.delete("/api/v1/messages")
        cleared.raise_for_status()
        sent = await api.post(
            f"{path}/{donation['id']}/pledge/deliveries",
            headers={**headers, "Idempotency-Key": "poc093:donation-pledge-mail"},
        )
        if sent.status_code != 201:
            raise ContractFailure(
                f"The pledge mail was not queued: {sent.status_code} {sent.text}"
            )
        delivery: dict[str, Any] = sent.json()
        for _attempt in range(90):
            listing = await api.get(path, headers=headers)
            listing.raise_for_status()
            record = next(
                item for item in listing.json()["items"] if item["id"] == donation["id"]
            )
            delivery = record["pledgeDeliveries"][0]
            if delivery["status"] == "sent":
                break
            await asyncio.sleep(1)
        else:
            raise ContractFailure(f"The pledge mail was not sent: {delivery}")
        messages = await mailpit.get("/api/v1/messages")
        messages.raise_for_status()
        summaries = messages.json()["messages"]
        if len(summaries) != 1:
            raise ContractFailure(f"Mailpit holds {len(summaries)} mails, not one")
        raw = await mailpit.get(f"/api/v1/message/{summaries[0]['ID']}/raw")
        raw.raise_for_status()

    row = await connection.fetchrow(
        """
        SELECT document.*, donation.pledge_snapshot
        FROM generated_document AS document
        JOIN donation ON donation.id = document.donation_id
        WHERE document.id = $1
        """,
        UUID(document_id),
    )
    if row is None:
        raise ContractFailure("The pledge document row is missing")
    snapshot = DonationPledgeDocument.from_payload(json.loads(row["pledge_snapshot"]))
    # Deterministic: rendering the stored snapshot again gives the same bytes.
    expected = TypstDonationPledgeRenderer().render(snapshot)
    retrieved = await storage().get(
        ObjectLocation(
            bucket=str(row["storage_bucket"]),
            key=str(row["object_key"]),
            version_id=str(row["storage_version_id"]),
        )
    )
    expected_key = (
        f"actions/{ACTION_ID}/donations/{donation['id']}/pledge/v1/"
        f"{expected.sha256}.pdf"
    )
    filename = f"filename*=UTF-8''Spendenzusage-{number}.pdf"
    if (
        download.status_code != 200
        or download.content != expected.content
        or retrieved.content != expected.content
        or str(row["object_key"]) != expected_key
        or str(row["sha256"]) != expected.sha256
        or str(row["render_version"]) != PLEDGE_RENDER_VERSION
        or row["invoice_id"] is not None
        or row["commitment_id"] is not None
        or download.headers.get("content-type") != "application/pdf"
        or download.headers.get("content-disposition") != f"attachment; {filename}"
    ):
        raise ContractFailure(
            "Snapshot, renderer, RustFS and API disagree on the donation pledge"
        )
    if (
        snapshot.body.legal_name != "Förderverein Lions Club Musterstadt e. V."
        or snapshot.body.iban != "DE02120300000000202051"
        or snapshot.number != number
    ):
        raise ContractFailure("The pledge does not show the receiving body")
    if (
        acquirer.status_code != 403
        or error_code(acquirer) != "document_download_required"
    ):
        raise ContractFailure("An acquirer could download the donation pledge")
    if foreign.status_code not in (403, 404):
        raise ContractFailure("Another action could download the donation pledge")
    message = BytesParser(policy=policy.default).parsebytes(raw.content)
    plain = message.get_body(preferencelist=("plain",))
    attachments = list(message.iter_attachments())
    attachment = attachments[0].get_payload(decode=True) if attachments else None
    if (
        str(message["To"]).casefold() != DONOR_EMAIL
        or str(message["Subject"]) != f"Spendenzusage {number} · Krapfentaxi 2026"
        or plain is None
        or "Dieses Schreiben ist keine Rechnung." not in plain.get_content()
        or f"Verwendungszweck {number}" not in " ".join(plain.get_content().split())
        or "50,00 €" not in plain.get_content()
        or len(attachments) != 1
        or attachments[0].get_content_type() != "application/pdf"
        or attachments[0].get_filename() != f"Spendenzusage-{number}.pdf"
        or not isinstance(attachment, bytes)
        or hashlib.sha256(attachment).hexdigest() != expected.sha256
    ):
        raise ContractFailure("The pledge mail or its PDF attachment is wrong")
    audit = await connection.fetch(
        """
        SELECT event_type FROM audit_event
        WHERE action_id = $1 AND event_type LIKE 'donation%'
        ORDER BY occurred_at, id
        """,
        ACTION_ID,
    )
    events = [str(item["event_type"]) for item in audit]
    if events[:2] != ["donation_pledged", "donation_pledge_delivery_requested"]:
        raise ContractFailure(f"The donation audit trail is wrong: {events}")
    print(
        f"document-contract: OK: donation pledge {number} rendered by the "
        "worker, stored, served byte-identical and mailed with its PDF"
    )


async def assert_missing_object(connection: asyncpg.Connection[Any]) -> None:
    # The invoice PDF; the invoice also has its cancellation invoice by now.
    row = await connection.fetchrow(
        """
        SELECT * FROM generated_document
        WHERE invoice_id = $1 AND document_type = 'invoice_pdf'
        """,
        INVOICE_THREE_ID,
    )
    if row is None:
        raise ContractFailure("Document for the controlled failure case is missing")
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
            reason="POC-093 controlled test of a missing object version",
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
    listed_types = sorted(
        str(item["document"]["documentType"]) for item in listed.json().get("items", [])
    )
    if (
        listed_types != ["invoice_cancellation_pdf", "invoice_pdf"]
        or response.status_code != 503
        or error_code(response) != "generated_document_storage_missing"
        or response.headers.get("content-type") != "application/json"
        or not response.content
        or response.content.startswith(b"%PDF")
    ):
        raise ContractFailure(
            "Missing RustFS version did not give a diagnosable JSON error"
        )
    print(
        "document-contract: OK: missing RustFS version stays listed and "
        "returns error generated_document_storage_missing instead of an empty download"
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
        elif arguments.command == "cancellation-invoice":
            await cancellation_invoice(connection)
        elif arguments.command == "donation-pledge":
            await donation_pledge(connection)
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
    commands.add_parser("cancellation-invoice")
    commands.add_parser("donation-pledge")
    commands.add_parser("assert-missing")
    return value


if __name__ == "__main__":
    asyncio.run(main(parser().parse_args()))
