#!/usr/bin/env python3
"""Real API/PostgreSQL/RustFS/Mailpit contract for invoice delivery."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMITMENT_ID = UUID("80000000-0000-4000-8000-000000000002")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000002")
FINANCE_ID = UUID("10000000-0000-4000-8000-000000000007")
SESSION_NAMESPACE = UUID("5a3033b7-9052-4d7e-b3a3-5e9945ea8c68")
EXPECTED_RECIPIENT = "max.mustermann@sonnenseite.leonaid.invalid"


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc094-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(value["error"].get("code"))


def read_state(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ContractFailure("Der POC-094-Zustand ist ungültig")
    return value


def write_state(path: Path, value: dict[str, str]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def seed_sessions(
    connection: asyncpg.Connection[Any],
    output: Path,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    users = (
        ("ADMIN_SESSION", "admin", ADMIN_ID),
        ("FINANCE_SESSION", "finance", FINANCE_ID),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [user_id for _name, _label, user_id in users],
    )
    tokens: dict[str, str] = {}
    values: list[str] = []
    for env_name, label, user_id in users:
        token = token_for(label, user_id)
        tokens[label] = token
        values.append(f"{env_name}={token}\n")
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, device_hint,
                created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $5, 'POC-094 Rechnungsversand',
                $5, $5
            )
            """,
            uuid5(SESSION_NAMESPACE, label),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    output.write_text("".join(values), encoding="utf-8")
    output.chmod(0o600)
    return tokens


async def prepare(
    connection: asyncpg.Connection[Any],
    state_path: Path,
    sessions_path: Path,
) -> None:
    tokens = await seed_sessions(connection, sessions_path)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        response = await api.post(
            f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ID}/invoice",
            headers={
                **session_headers(tokens["admin"]),
                "Idempotency-Key": "poc094:issue:golden-v1",
            },
            json={"serviceOn": "2026-11-15"},
        )
        response.raise_for_status()
        invoice = response.json()
    if (
        invoice.get("number") != "KT26-0004"
        or invoice.get("status") != "issued"
        or invoice.get("recipient", {}).get("email") != EXPECTED_RECIPIENT
    ):
        raise ContractFailure(f"Golden-Rechnung ist nicht versandfähig: {invoice}")
    state = {"invoiceId": str(invoice["id"])}
    write_state(state_path, state)
    with sessions_path.open("a", encoding="utf-8") as output:
        output.write(f"INVOICE_ID={invoice['id']}\n")
    print(
        "invoice-delivery-contract: Golden-Rechnung KT26-0004 mit "
        "unveränderlichem E-Mail-Empfänger freigegeben"
    )


async def queue(
    connection: asyncpg.Connection[Any],
    state_path: Path,
    sessions_path: Path,
) -> None:
    state = read_state(state_path)
    invoice_id = UUID(state["invoiceId"])
    document = await connection.fetchrow(
        """
        SELECT *
        FROM generated_document
        WHERE invoice_id = $1
          AND status = 'available'
        """,
        invoice_id,
    )
    if document is None:
        raise ContractFailure("Das Typst-PDF ist noch nicht versandbereit")
    tokens = {
        "admin": token_for("admin", ADMIN_ID),
        "finance": token_for("finance", FINANCE_ID),
    }
    async with (
        httpx.AsyncClient(
            base_url=require_env("API_BASE_URL").rstrip("/"),
            timeout=60,
        ) as api,
        httpx.AsyncClient(
            base_url=require_env("MAIL_TEST_API_URL").rstrip("/"),
            timeout=10,
        ) as mailpit,
    ):
        cleared = await mailpit.delete("/api/v1/messages")
        cleared.raise_for_status()
        forbidden = await api.post(
            f"/api/v1/actions/{ACTION_ID}/invoices/{invoice_id}/deliveries",
            headers={
                **session_headers(tokens["finance"]),
                "Idempotency-Key": "poc094:finance:forbidden",
            },
        )
        if (
            forbidden.status_code != 403
            or error_code(forbidden) != "invoice_delivery_required"
        ):
            raise ContractFailure("Finanz-Leser konnte eine Rechnung versenden")

        headers = {
            **session_headers(tokens["admin"]),
            "Idempotency-Key": "poc094:delivery:golden-v1",
        }
        response = await api.post(
            f"/api/v1/actions/{ACTION_ID}/invoices/{invoice_id}/deliveries",
            headers=headers,
        )
        response.raise_for_status()
        replay = await api.post(
            f"/api/v1/actions/{ACTION_ID}/invoices/{invoice_id}/deliveries",
            headers=headers,
        )
        replay.raise_for_status()
        delivery = response.json()
        if (
            replay.json() != delivery
            or delivery.get("status") != "queued"
            or delivery.get("attempts") != 0
            or delivery.get("generatedDocumentId") != str(document["id"])
            or delivery.get("recipientEmail") != EXPECTED_RECIPIENT
        ):
            raise ContractFailure(
                f"Idempotenter Versandauftrag ist inkonsistent: {delivery}"
            )
        invoice_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["admin"]),
        )
        invoice_list.raise_for_status()
        record = next(
            (
                item
                for item in invoice_list.json().get("items", [])
                if item.get("invoice", {}).get("id") == str(invoice_id)
            ),
            None,
        )
        if not isinstance(record, dict) or record.get("deliveries") != [delivery]:
            raise ContractFailure(
                "Versandstatus ist im Rechnungsjournal nicht sichtbar"
            )
    counts = await connection.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM invoice_delivery WHERE invoice_id = $1)
            AS deliveries,
          (
            SELECT count(*)
            FROM outbox_event
            WHERE aggregate_type = 'invoice_delivery'
              AND aggregate_id = $2
          ) AS outbox
        """,
        invoice_id,
        UUID(str(delivery["id"])),
    )
    if counts is None or dict(counts) != {"deliveries": 1, "outbox": 1}:
        raise ContractFailure(f"Versand-Replay duplizierte Daten: {dict(counts or {})}")
    state.update(
        {
            "deliveryId": str(delivery["id"]),
            "documentId": str(document["id"]),
            "documentSha256": str(document["sha256"]),
        }
    )
    write_state(state_path, state)
    with sessions_path.open("a", encoding="utf-8") as output:
        output.write(f"DELIVERY_ID={delivery['id']}\n")
    print(
        "invoice-delivery-contract: Versand einmalig per Outbox eingeplant; "
        "Finanz-Leser bleibt schreibgeschützt"
    )


async def assert_failed(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    state = read_state(state_path)
    invoice_id = UUID(state["invoiceId"])
    delivery_id = UUID(state["deliveryId"])
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as api:
        response = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(token_for("admin", ADMIN_ID)),
        )
        response.raise_for_status()
    deliveries = next(
        item["deliveries"]
        for item in response.json()["items"]
        if item["invoice"]["id"] == str(invoice_id)
    )
    delivery = next(item for item in deliveries if item["id"] == str(delivery_id))
    if (
        delivery.get("status") != "failed"
        or delivery.get("attempts") != 1
        or delivery.get("canRetry") is not True
        or delivery.get("lastErrorCode") != "mail_unavailable"
        or delivery.get("lastErrorDetail") != "mail_unavailable"
        or delivery.get("messageId") is not None
    ):
        raise ContractFailure(
            f"SMTP-Ausfall ist nicht vollständig sichtbar: {delivery}"
        )
    row = await connection.fetchrow(
        """
        SELECT event.status, event.attempts, event.last_error_code,
               event.last_error_detail, mail.id AS mail_id
        FROM invoice_delivery AS delivery
        JOIN outbox_event AS event ON event.id = delivery.outbox_event_id
        LEFT JOIN mail_delivery AS mail
          ON mail.outbox_event_id = event.id
        WHERE delivery.id = $1
        """,
        delivery_id,
    )
    if (
        row is None
        or row["status"] != "dead_letter"
        or row["attempts"] != 1
        or row["last_error_code"] != "mail_unavailable"
        or row["last_error_detail"] != "mail_unavailable"
        or row["mail_id"] is not None
    ):
        raise ContractFailure(
            f"Durable Fehlerzustand ist inkonsistent: {dict(row or {})}"
        )
    print(
        "invoice-delivery-contract: real gestopptes Mailpit ergab sichtbaren "
        "Fehler, Versuch 1 und administrativen Wiederanlauf"
    )


async def wait_for_delivery(
    api: httpx.AsyncClient,
    *,
    invoice_id: str,
    delivery_id: str,
    expected_status: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(token_for("admin", ADMIN_ID)),
        )
        response.raise_for_status()
        for record in response.json().get("items", []):
            if record.get("invoice", {}).get("id") != invoice_id:
                continue
            for delivery in record.get("deliveries", []):
                if (
                    delivery.get("id") == delivery_id
                    and delivery.get("status") == expected_status
                ):
                    return cast(dict[str, Any], delivery)
        await asyncio.sleep(0.2)
    raise ContractFailure(
        f"Versand {delivery_id} erreichte Status {expected_status} nicht"
    )


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


async def mailpit_messages(mailpit: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await mailpit.get("/api/v1/messages")
    response.raise_for_status()
    value = response.json()
    messages = value.get("messages") if isinstance(value, dict) else None
    if not isinstance(messages, list) or any(
        not isinstance(item, dict) for item in messages
    ):
        raise ContractFailure("Mailpit-Nachrichtenliste ist ungültig")
    return [cast(dict[str, Any], item) for item in messages]


async def assert_mime_message(
    mailpit: httpx.AsyncClient,
    summary: dict[str, Any],
    *,
    expected_sha256: str,
    expected_message_id: str,
) -> None:
    message_id = summary.get("ID")
    if not isinstance(message_id, str):
        raise ContractFailure("Mailpit-Nachricht besitzt keine ID")
    raw_response = await mailpit.get(f"/api/v1/message/{message_id}/raw")
    raw_response.raise_for_status()
    message = BytesParser(policy=policy.default).parsebytes(raw_response.content)
    plain = message.get_body(preferencelist=("plain",))
    attachments = list(message.iter_attachments())
    attachment_payload = (
        attachments[0].get_payload(decode=True) if len(attachments) == 1 else None
    )
    if (
        recipient_addresses(summary.get("To")) != {EXPECTED_RECIPIENT}
        or str(message["To"]).casefold() != EXPECTED_RECIPIENT
        or str(message["Subject"]) != "Rechnung KT26-0004 · Krapfentaxi 2026"
        or str(message["Message-ID"]) != expected_message_id
        or plain is None
        or "Rechnungsbetrag: 108,00 €" not in plain.get_content()
        or "Verwendungszweck: KT26-0004" not in plain.get_content()
        or len(attachments) != 1
        or attachments[0].get_content_type() != "application/pdf"
        or attachments[0].get_filename() != "Rechnung-KT26-0004.pdf"
        or not isinstance(attachment_payload, bytes)
        or hashlib.sha256(attachment_payload).hexdigest() != expected_sha256
    ):
        raise ContractFailure("Mailpit-MIME oder PDF-Anhang weicht vom Auftrag ab")


async def assert_delivered(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    state = read_state(state_path)
    async with (
        httpx.AsyncClient(
            base_url=require_env("API_BASE_URL").rstrip("/"),
            timeout=30,
        ) as api,
        httpx.AsyncClient(
            base_url=require_env("MAIL_TEST_API_URL").rstrip("/"),
            timeout=10,
        ) as mailpit,
    ):
        delivery = await wait_for_delivery(
            api,
            invoice_id=state["invoiceId"],
            delivery_id=state["deliveryId"],
            expected_status="sent",
        )
        messages = await mailpit_messages(mailpit)
        if (
            len(messages) != 1
            or delivery.get("attempts") != 2
            or delivery.get("canRetry") is not False
            or not delivery.get("messageId")
            or not delivery.get("sentAt")
            or delivery.get("lastErrorCode") is not None
            or delivery.get("lastErrorDetail") is not None
        ):
            raise ContractFailure(
                f"Wiederanlauf lieferte keinen eindeutigen Erfolg: {delivery}"
            )
        await assert_mime_message(
            mailpit,
            messages[0],
            expected_sha256=state["documentSha256"],
            expected_message_id=str(delivery["messageId"]),
        )
        retry = await api.post(
            (
                f"/api/v1/actions/{ACTION_ID}/invoices/{state['invoiceId']}/"
                f"deliveries/{state['deliveryId']}/retry"
            ),
            headers=session_headers(token_for("admin", ADMIN_ID)),
        )
        if (
            retry.status_code != 409
            or error_code(retry) != "invoice_delivery_already_sent"
        ):
            raise ContractFailure("Bestätigter Erfolg konnte erneut gestartet werden")
        await asyncio.sleep(0.5)
        if len(await mailpit_messages(mailpit)) != 1:
            raise ContractFailure("Retry nach bestätigtem Erfolg duplizierte die Mail")
    row = await connection.fetchrow(
        """
        SELECT
          invoice.status AS invoice_status,
          document.sent_at,
          (SELECT count(*) FROM mail_delivery WHERE outbox_event_id = event.id)
            AS mail_deliveries
        FROM invoice_delivery AS delivery
        JOIN outbox_event AS event ON event.id = delivery.outbox_event_id
        JOIN invoice ON invoice.id = delivery.invoice_id
        JOIN generated_document AS document
          ON document.id = delivery.generated_document_id
        WHERE delivery.id = $1
        """,
        UUID(state["deliveryId"]),
    )
    if (
        row is None
        or row["invoice_status"] != "sent"
        or row["sent_at"] is None
        or row["mail_deliveries"] != 1
    ):
        raise ContractFailure(
            f"SMTP-Erfolg ist nicht fachlich projiziert: {dict(row or {})}"
        )
    print(
        "invoice-delivery-contract: Retry nach echtem Ausfall ergab exakt eine "
        "MIME-Mail mit byteidentischem Typst-PDF; bestätigter Erfolg ist gesperrt"
    )


async def queue_resend(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    state = read_state(state_path)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as api:
        response = await api.post(
            f"/api/v1/actions/{ACTION_ID}/invoices/{state['invoiceId']}/deliveries",
            headers={
                **session_headers(token_for("admin", ADMIN_ID)),
                "Idempotency-Key": "poc094:delivery:deliberate-resend-v1",
            },
        )
        response.raise_for_status()
        delivery = response.json()
    document_count = await connection.fetchval(
        "SELECT count(*) FROM generated_document WHERE invoice_id = $1",
        UUID(state["invoiceId"]),
    )
    if (
        delivery.get("id") == state["deliveryId"]
        or delivery.get("generatedDocumentId") != state["documentId"]
        or delivery.get("status") != "queued"
        or document_count != 1
    ):
        raise ContractFailure(
            "Bewusster Neuversand nutzt nicht exakt dasselbe Rechnungsdokument"
        )
    state["resendDeliveryId"] = str(delivery["id"])
    write_state(state_path, state)
    print(
        "invoice-delivery-contract: bewusster Neuversand separat eingeplant, "
        "ohne neue Dokumentversion"
    )


async def assert_resend(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    state = read_state(state_path)
    async with (
        httpx.AsyncClient(
            base_url=require_env("API_BASE_URL").rstrip("/"),
            timeout=30,
        ) as api,
        httpx.AsyncClient(
            base_url=require_env("MAIL_TEST_API_URL").rstrip("/"),
            timeout=10,
        ) as mailpit,
    ):
        resent = await wait_for_delivery(
            api,
            invoice_id=state["invoiceId"],
            delivery_id=state["resendDeliveryId"],
            expected_status="sent",
        )
        messages = await mailpit_messages(mailpit)
        if len(messages) != 2 or not resent.get("messageId"):
            raise ContractFailure("Bewusster Neuversand ergab nicht exakt zwei Mails")
        database_message_ids = {
            str(row["message_id"])
            for row in await connection.fetch(
                """
                SELECT mail.message_id
                FROM invoice_delivery AS delivery
                JOIN mail_delivery AS mail
                  ON mail.outbox_event_id = delivery.outbox_event_id
                WHERE delivery.invoice_id = $1
                """,
                UUID(state["invoiceId"]),
            )
        }
        if len(database_message_ids) != 2:
            raise ContractFailure("Neuversand besitzt keine eigene Message-ID")
        for summary in messages:
            summary_message_id = f"<{summary.get('MessageID')}>"
            if summary_message_id not in database_message_ids:
                raise ContractFailure("Mailpit- und PostgreSQL-Message-ID weichen ab")
            await assert_mime_message(
                mailpit,
                summary,
                expected_sha256=state["documentSha256"],
                expected_message_id=summary_message_id,
            )
    counts = await connection.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM generated_document WHERE invoice_id = $1)
            AS documents,
          (SELECT count(*) FROM invoice_delivery WHERE invoice_id = $1)
            AS deliveries,
          (
            SELECT count(*)
            FROM invoice_delivery AS delivery
            JOIN mail_delivery AS mail
              ON mail.outbox_event_id = delivery.outbox_event_id
            WHERE delivery.invoice_id = $1
          ) AS sent
        """,
        UUID(state["invoiceId"]),
    )
    if counts is None or dict(counts) != {
        "documents": 1,
        "deliveries": 2,
        "sent": 2,
    }:
        raise ContractFailure(
            f"Neuversandszahlen sind inkonsistent: {dict(counts or {})}"
        )
    print(
        "invoice-delivery-contract: zwei bewusste Zustellungen, zwei Message-IDs "
        "und weiterhin exakt ein unverändertes Typst-PDF"
    )


async def run(arguments: argparse.Namespace) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        if arguments.command == "prepare":
            await prepare(connection, arguments.state, arguments.sessions)
        elif arguments.command == "queue":
            await queue(connection, arguments.state, arguments.sessions)
        elif arguments.command == "assert-failed":
            await assert_failed(connection, arguments.state)
        elif arguments.command == "assert-delivered":
            await assert_delivered(connection, arguments.state)
        elif arguments.command == "queue-resend":
            await queue_resend(connection, arguments.state)
        elif arguments.command == "assert-resend":
            await assert_resend(connection, arguments.state)
        else:
            raise ContractFailure(f"Unbekannter Befehl: {arguments.command}")
    finally:
        await connection.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("state", type=Path)
    prepare_command.add_argument("sessions", type=Path)
    queue_command = commands.add_parser("queue")
    queue_command.add_argument("state", type=Path)
    queue_command.add_argument("sessions", type=Path)
    for command_name in (
        "assert-failed",
        "assert-delivered",
        "queue-resend",
        "assert-resend",
    ):
        command = commands.add_parser(command_name)
        command.add_argument("state", type=Path)
    return value


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
