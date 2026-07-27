#!/usr/bin/env python3
"""Cross-system evidence contract for the complete Krapfentaxi journey."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx
from pydantic import SecretStr
from pypdf import PdfReader

from leonaid.adapters.storage import S3ObjectStorage
from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.object_storage import ObjectLocation
from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest

KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
SESSION_NAMESPACE = UUID("7b8a92fb-efaf-4118-a449-bc9f4f8e9f91")
ENGINES = ("chromium", "firefox", "webkit")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(round_name: str, engine: str, freshness: str) -> str:
    return f"poc122-{round_name}-{engine}-{freshness}-{KLARA_ID}-real-session"


async def prepare_sessions(
    connection: asyncpg.Connection[Any],
    *,
    round_name: str,
    output: Path,
) -> None:
    now = datetime.now(timezone.utc)
    await connection.execute(
        "DELETE FROM user_session WHERE device_hint LIKE 'POC-122 %'"
    )
    lines: list[str] = []
    for engine in ENGINES:
        for freshness, fresh_login_at in (
            ("fresh", now),
            ("stale", now - timedelta(hours=1)),
        ):
            token = token_for(round_name, engine, freshness)
            suffix = "_STALE" if freshness == "stale" else ""
            lines.append(f"KLARA_{engine.upper()}{suffix}_SESSION={token}\n")
            await connection.execute(
                """
                INSERT INTO user_session (
                    id, user_id, token_digest, expires_at, last_seen_at,
                    fresh_login_at, device_hint, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $5)
                """,
                uuid5(
                    SESSION_NAMESPACE,
                    f"{round_name}:{engine}:{freshness}",
                ),
                KLARA_ID,
                session_token_digest(token),
                now + SESSION_LIFETIME - timedelta(hours=2),
                now,
                fresh_login_at,
                f"POC-122 {round_name} {engine} {freshness}",
                now - timedelta(hours=2),
            )
    output.write_text("".join(lines), encoding="utf-8")
    output.chmod(0o600)


def load_artifacts(directory: Path, round_name: str) -> list[dict[str, Any]]:
    result = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob(f"golden-{round_name}-*.json"))
    ]
    if len(result) != 3 or {item.get("browser") for item in result} != set(ENGINES):
        raise ContractFailure(f"Browserartefakte für {round_name} unvollständig")
    return result


def recipient_addresses(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str):
        if "@" in value:
            result.add(value.casefold())
    elif isinstance(value, dict):
        for item in value.values():
            result.update(recipient_addresses(item))
    elif isinstance(value, list):
        for item in value:
            result.update(recipient_addresses(item))
    return result


async def mail_messages(mailpit: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await mailpit.get("/api/v1/messages")
    response.raise_for_status()
    messages = response.json().get("messages", [])
    if not isinstance(messages, list):
        raise ContractFailure("Mailpit-Nachrichtenliste fehlt")
    return [item for item in messages if isinstance(item, dict)]


async def assert_invoice_mail(
    mailpit: httpx.AsyncClient,
    messages: list[dict[str, Any]],
    *,
    recipient: str,
    pdf_sha256: str,
) -> None:
    candidates = [
        item
        for item in messages
        if recipient.casefold() in recipient_addresses(item.get("To"))
        and str(item.get("Subject", "")).startswith("Rechnung ")
    ]
    if len(candidates) != 1 or not isinstance(candidates[0].get("ID"), str):
        raise ContractFailure(f"Rechnungs-Mail an {recipient} nicht eindeutig")
    response = await mailpit.get(f"/api/v1/message/{candidates[0]['ID']}/raw")
    response.raise_for_status()
    message = BytesParser(policy=policy.default).parsebytes(response.content)
    attachments = list(message.iter_attachments())
    payload = attachments[0].get_payload(decode=True) if len(attachments) == 1 else None
    if (
        len(attachments) != 1
        or attachments[0].get_content_type() != "application/pdf"
        or not isinstance(payload, bytes)
        or hashlib.sha256(payload).hexdigest() != pdf_sha256
    ):
        raise ContractFailure(f"MIME-PDF an {recipient} ist nicht byteidentisch")


async def verify_round(
    connection: asyncpg.Connection[Any],
    *,
    round_name: str,
    artifacts_directory: Path,
    output: Path,
    normalized_output: Path,
) -> None:
    artifacts = load_artifacts(artifacts_directory, round_name)
    companies = [str(item["company"]) for item in artifacts]
    emails = [f"journey-{round_name}-{engine}@leonaid.invalid" for engine in ENGINES]
    commitment_ids = [UUID(str(item["commitmentId"])) for item in artifacts]
    invoice_ids = [UUID(str(item["invoiceId"])) for item in artifacts]
    public_references = [str(item["publicReference"]) for item in artifacts]

    row = await connection.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM user_account WHERE email = ANY($1::text[])) AS users,
          (
            SELECT count(*)
            FROM action_membership AS membership
            JOIN user_account AS account ON account.id = membership.user_id
            WHERE account.email = ANY($1::text[]) AND membership.role = 'acquirer'
          ) AS memberships,
          (
            SELECT count(*)
            FROM acquisition_assignment AS assignment
            JOIN user_account AS account
              ON account.id = assignment.acquirer_user_id
            WHERE account.email = ANY($1::text[])
          ) AS assignments,
          (
            SELECT count(*)
            FROM acquisition_activity
            WHERE note = ANY($2::text[])
          ) AS activities,
          (
            SELECT count(*) FROM commitment
            WHERE id = ANY($3::uuid[]) AND source = 'acquisition'
              AND total_minor = 7200
          ) AS internal_orders,
          (
            SELECT count(*) FROM commitment
            WHERE public_reference = ANY($4::text[]) AND source = 'public_form'
              AND total_minor = 3600
          ) AS public_orders,
          (
            SELECT count(*) FROM invoice
            WHERE id = ANY($5::uuid[]) AND status = 'paid'
              AND gross_minor = 7200
          ) AS paid_invoices,
          (
            SELECT count(*) FROM payment_record
            WHERE invoice_id = ANY($5::uuid[]) AND amount_minor = 7200
          ) AS payments,
          (
            SELECT count(*)
            FROM invoice_delivery AS delivery
            JOIN outbox_event AS event ON event.id = delivery.outbox_event_id
            WHERE delivery.invoice_id = ANY($5::uuid[])
              AND event.status = 'completed'
          ) AS deliveries,
          (
            SELECT count(*) FROM outbox_event
            WHERE idempotency_key IN (
              SELECT idempotency_key FROM outbox_event
              GROUP BY idempotency_key HAVING count(*) > 1
            )
          ) AS duplicate_outbox,
          (
            SELECT count(*) FROM user_account
            WHERE email LIKE 'journey-round-%@leonaid.invalid'
          ) AS journey_users_total
        """,
        emails,
        [
            f"Golden Journey {round_name}-{engine}: Bedarf besprochen."
            for engine in ENGINES
        ],
        commitment_ids,
        public_references,
        invoice_ids,
    )
    expected = {
        "users": 3,
        "memberships": 3,
        "assignments": 3,
        "activities": 3,
        "internal_orders": 3,
        "public_orders": 3,
        "paid_invoices": 3,
        "payments": 3,
        "deliveries": 3,
        "duplicate_outbox": 0,
        "journey_users_total": 3 if round_name == "round-1" else 6,
    }
    values = {key: int(row[key]) for key in expected} if row else {}
    if values != expected:
        raise ContractFailure(f"PostgreSQL-Fachsummen für {round_name}: {values}")

    integration_key = require_env("TWENTY_INTEGRATION_API_KEY")
    async with TwentyCrmGateway(
        TwentyGatewaySettings(
            base_url=require_env("TWENTY_BASE_URL"),
            api_key=SecretStr(integration_key),
            timeout_seconds=20,
        )
    ) as crm:
        crm_records = []
        for company in companies:
            found = await crm.search_companies(
                company,
                correlation_id=f"poc122:{round_name}:twenty",
            )
            exact = [item for item in found if item.data.name == company]
            if len(exact) != 1:
                raise ContractFailure(f"Twenty-Firma nicht eindeutig: {company}")
            crm_records.append(exact[0])
    if {str(item.twenty_id) for item in crm_records} != {
        str(item["partyTwentyId"]) for item in artifacts
    }:
        raise ContractFailure("Twenty-IDs weichen von Browserantworten ab")

    storage = S3ObjectStorage(
        endpoint_url=require_env("OBJECT_STORAGE_ENDPOINT_URL"),
        access_key=require_env("OBJECT_STORAGE_ACCESS_KEY"),
        secret_key=require_env("OBJECT_STORAGE_SECRET_KEY"),
        bucket=require_env("OBJECT_STORAGE_BUCKET"),
    )
    document_rows = await connection.fetch(
        """
        SELECT invoice_id, object_key, storage_version_id, sha256, size_bytes
        FROM generated_document
        WHERE invoice_id = ANY($1::uuid[]) AND status = 'available'
        ORDER BY invoice_id
        """,
        invoice_ids,
    )
    if len(document_rows) != 3:
        raise ContractFailure("Nicht alle Journey-PDFs sind verfügbar")
    pdf_evidence: dict[str, dict[str, object]] = {}
    async with httpx.AsyncClient(
        base_url=require_env("MAILPIT_API_URL").rstrip("/"),
        timeout=20,
    ) as mailpit:
        messages = await mail_messages(mailpit)
        for document in document_rows:
            retrieved = await storage.get(
                ObjectLocation(
                    bucket=require_env("OBJECT_STORAGE_BUCKET"),
                    key=str(document["object_key"]),
                    version_id=str(document["storage_version_id"]),
                )
            )
            digest = hashlib.sha256(retrieved.content).hexdigest()
            invoice_id = str(document["invoice_id"])
            artifact = next(
                item for item in artifacts if str(item["invoiceId"]) == invoice_id
            )
            text = "\n".join(
                page.extract_text() or ""
                for page in PdfReader(BytesIO(retrieved.content)).pages
            )
            if (
                not retrieved.content.startswith(b"%PDF-")
                or digest != document["sha256"]
                or len(retrieved.content) != document["size_bytes"]
                or str(artifact["invoiceNumber"]) not in text
                or str(artifact["company"]) not in text
            ):
                raise ContractFailure(f"PDF-Nachweis fehlerhaft: {invoice_id}")
            browser_pdf = artifacts_directory / (
                f"golden-{round_name}-{artifact['browser']}-"
                f"{artifact['invoiceNumber']}.pdf"
            )
            if (
                not browser_pdf.is_file()
                or hashlib.sha256(browser_pdf.read_bytes()).hexdigest() != digest
            ):
                raise ContractFailure(
                    f"Browser-PDF ist nicht byteidentisch: {invoice_id}"
                )
            recipient = f"journey-{round_name}-{artifact['browser']}@leonaid.invalid"
            await assert_invoice_mail(
                mailpit,
                messages,
                recipient=recipient,
                pdf_sha256=digest,
            )
            pdf_evidence[str(artifact["invoiceNumber"])] = {
                "sha256": digest,
                "sizeBytes": len(retrieved.content),
            }

    summary = {
        "businessCounts": values,
        "companies": sorted(companies),
        "datasetVersion": "1.0.0",
        "pdfs": pdf_evidence,
        "round": round_name,
    }
    output.write_text(
        f"{json.dumps(summary, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    normalized_summary = {
        "businessCounts": values,
        "companies": sorted(companies),
        "datasetVersion": "1.0.0",
        "pdfs": {
            number: {"sizeBytes": evidence["sizeBytes"]}
            for number, evidence in pdf_evidence.items()
        },
        "round": round_name,
    }
    normalized_output.write_text(
        f"{json.dumps(normalized_summary, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


async def execute(arguments: argparse.Namespace) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        if arguments.command == "prepare-sessions":
            await prepare_sessions(
                connection,
                round_name=arguments.round,
                output=arguments.output,
            )
        elif arguments.command == "verify":
            await verify_round(
                connection,
                round_name=arguments.round,
                artifacts_directory=arguments.artifacts,
                output=arguments.output,
                normalized_output=arguments.normalized_output,
            )
        else:
            raise ContractFailure(f"Unbekannter Befehl: {arguments.command}")
    finally:
        await connection.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    sessions = commands.add_parser("prepare-sessions")
    sessions.add_argument("round")
    sessions.add_argument("output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("round")
    verify.add_argument("artifacts", type=Path)
    verify.add_argument("output", type=Path)
    verify.add_argument("normalized_output", type=Path)
    return result


if __name__ == "__main__":
    asyncio.run(execute(parser().parse_args()))
