#!/usr/bin/env python3
"""Real API/PostgreSQL contract for exact payments and invoice cancellations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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
OPEN_INVOICE_ID = UUID("90000000-0000-4000-8000-000000000001")
PAID_INVOICE_ID = UUID("90000000-0000-4000-8000-000000000002")
CANCELLED_INVOICE_ID = UUID("90000000-0000-4000-8000-000000000003")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
FOREIGN_ADMIN_ID = UUID("10000000-0000-4000-8000-000000000003")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
FINN_ID = UUID("10000000-0000-4000-8000-000000000007")
SESSION_NAMESPACE = UUID("be0408f6-66eb-43ec-9353-c8a7d480951e")
PAYMENT_KEY = "poc095:payment:browser-v1"
CANCELLATION_KEY = "poc095:cancellation:browser-v1"
PAYMENT_DATE = "2026-07-20"
PAYMENT_REFERENCE = "Bankumsatz KT26-0001 / 20.07.2026"
CANCELLATION_REASON = "Bestellung nach Rechnungsfreigabe vollständig zurückgenommen."


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc095-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(value["error"].get("code"))


def read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractFailure("Der POC-095-Zustand ist ungültig")
    return value


def write_state(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def json_object(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ContractFailure(f"{label} ist kein JSON-Objekt")
    return value


async def seed_sessions(
    connection: asyncpg.Connection[Any],
    output: Path,
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    users = (
        ("KLARA_SESSION", "klara", KLARA_ID),
        ("FINN_SESSION", "finn", FINN_ID),
        ("ANNA_SESSION", "anna", ANNA_ID),
        ("FOREIGN_ADMIN_SESSION", "foreign-admin", FOREIGN_ADMIN_ID),
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
                $5, $5, 'POC-095 Finanzjournal',
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


def invoice_record(payload: dict[str, Any], invoice_id: UUID) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ContractFailure("Rechnungsjournal besitzt keine Belegliste")
    for item in items:
        if (
            isinstance(item, dict)
            and isinstance(item.get("invoice"), dict)
            and item["invoice"].get("id") == str(invoice_id)
        ):
            return item
    raise ContractFailure(f"Rechnung {invoice_id} fehlt im Journal")


async def assert_negative_payment_cases(
    api: httpx.AsyncClient,
    tokens: dict[str, str],
) -> None:
    endpoint = f"/api/v1/actions/{ACTION_ID}/invoices/{OPEN_INVOICE_ID}/payments"
    payload = {
        "amountMinor": 36_000,
        "currency": "EUR",
        "receivedOn": PAYMENT_DATE,
        "reference": PAYMENT_REFERENCE,
    }
    for label, key in (
        ("finn", "poc095:finance-reader:forbidden"),
        ("anna", "poc095:acquirer:forbidden"),
        ("foreign-admin", "poc095:foreign-admin:forbidden"),
    ):
        response = await api.post(
            endpoint,
            headers={
                **session_headers(tokens[label]),
                "Idempotency-Key": key,
            },
            json=payload,
        )
        if (
            response.status_code != 403
            or error_code(response) != "invoice_settlement_required"
        ):
            raise ContractFailure(f"Persona {label} konnte eine Zahlung buchen")

    for amount, key in (
        (35_999, "poc095:partial:rejected"),
        (36_001, "poc095:overpayment:rejected"),
    ):
        response = await api.post(
            endpoint,
            headers={
                **session_headers(tokens["klara"]),
                "Idempotency-Key": key,
            },
            json={**payload, "amountMinor": amount},
        )
        if (
            response.status_code != 422
            or error_code(response) != "invoice_payment_full_amount_required"
        ):
            raise ContractFailure(
                f"Teil-/Überzahlung {amount} wurde nicht stabil abgewiesen"
            )

    wrong_currency = await api.post(
        endpoint,
        headers={
            **session_headers(tokens["klara"]),
            "Idempotency-Key": "poc095:currency:rejected",
        },
        json={**payload, "currency": "USD"},
    )
    if (
        wrong_currency.status_code != 422
        or error_code(wrong_currency) != "invoice_payment_currency_mismatch"
    ):
        raise ContractFailure("Abweichende Zahlungswährung wurde nicht abgewiesen")


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
        admin_response = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["klara"]),
        )
        admin_response.raise_for_status()
        finance_response = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["finn"]),
        )
        finance_response.raise_for_status()
        admin_payload = admin_response.json()
        finance_payload = finance_response.json()
        if (
            len(admin_payload.get("items", [])) != 3
            or admin_payload.get("currencyTotals")
            != [{"currency": "EUR", "grossMinor": 54_000, "openMinor": 36_000}]
            or invoice_record(admin_payload, OPEN_INVOICE_ID).get("openMinor") != 36_000
            or invoice_record(admin_payload, PAID_INVOICE_ID).get("payment") is None
            or invoice_record(admin_payload, CANCELLED_INVOICE_ID).get("cancellation")
            is None
            or finance_payload != admin_payload
        ):
            raise ContractFailure(
                "Golden-Journal unterscheidet offen, bezahlt und storniert nicht"
            )

        await assert_negative_payment_cases(api, tokens)

        response = await api.post(
            f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ID}/invoice",
            headers={
                **session_headers(tokens["klara"]),
                "Idempotency-Key": "poc095:issue:cancellation-case-v1",
            },
            json={"serviceOn": "2026-11-15"},
        )
        response.raise_for_status()
        invoice = response.json()
    if invoice.get("number") != "KT26-0004" or invoice.get("status") != "issued":
        raise ContractFailure(f"Storno-Beleg wurde nicht freigegeben: {invoice}")
    state = {
        "cancellationInvoiceId": str(invoice["id"]),
        "openInvoiceId": str(OPEN_INVOICE_ID),
    }
    write_state(state_path, state)
    with sessions_path.open("a", encoding="utf-8") as output:
        output.write(f"CANCELLATION_INVOICE_ID={invoice['id']}\n")
        output.write(f"OPEN_INVOICE_ID={OPEN_INVOICE_ID}\n")
        output.write(f"PAYMENT_DATE={PAYMENT_DATE}\n")
        output.write(f"PAYMENT_REFERENCE={PAYMENT_REFERENCE}\n")
        output.write(f"CANCELLATION_REASON={CANCELLATION_REASON}\n")
        output.write(f"PAYMENT_KEY={PAYMENT_KEY}\n")
        output.write(f"CANCELLATION_KEY={CANCELLATION_KEY}\n")
    print(
        "invoice-settlement-contract: Rollen, Golden-Status und serverseitige "
        "Vollzahlungsgrenze bewiesen"
    )


async def capture(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    state = read_state(state_path)
    invoice_id = UUID(str(state["cancellationInvoiceId"]))
    invoice_snapshot = await connection.fetchval(
        """
        SELECT to_jsonb(invoice) - ARRAY['status', 'updated_at']::text[]
        FROM invoice
        WHERE id = $1
        """,
        invoice_id,
    )
    document_snapshot = await connection.fetchval(
        """
        SELECT to_jsonb(document)
        FROM generated_document AS document
        WHERE invoice_id = $1
          AND status = 'available'
        """,
        invoice_id,
    )
    if invoice_snapshot is None or document_snapshot is None:
        raise ContractFailure("Typst-PDF und Rechnungs-Snapshot fehlen vor Storno")
    state["invoiceSnapshot"] = json_object(
        invoice_snapshot,
        label="Rechnungs-Snapshot",
    )
    state["documentSnapshot"] = json_object(
        document_snapshot,
        label="Dokument-Snapshot",
    )
    write_state(state_path, state)
    print(
        "invoice-settlement-contract: unveränderlicher Rechnungs- und "
        "Typst-Dokumentstand vor Browseraktion gesichert"
    )


async def assert_after_browser(
    connection: asyncpg.Connection[Any],
    state_path: Path,
) -> None:
    state = read_state(state_path)
    cancellation_invoice_id = UUID(str(state["cancellationInvoiceId"]))
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=30,
    ) as api:
        admin_headers = session_headers(token_for("klara", KLARA_ID))
        response = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=admin_headers,
        )
        response.raise_for_status()
        payload = response.json()
        open_record = invoice_record(payload, OPEN_INVOICE_ID)
        cancellation_record = invoice_record(payload, cancellation_invoice_id)
        if (
            payload.get("currencyTotals")
            != [{"currency": "EUR", "grossMinor": 64_800, "openMinor": 0}]
            or open_record.get("invoice", {}).get("status") != "paid"
            or open_record.get("openMinor") != 0
            or open_record.get("payment", {}).get("reference") != PAYMENT_REFERENCE
            or cancellation_record.get("invoice", {}).get("status") != "cancelled"
            or cancellation_record.get("openMinor") != 0
            or cancellation_record.get("cancellation", {}).get("reason")
            != CANCELLATION_REASON
        ):
            raise ContractFailure("Browseraktionen sind im Journal inkonsistent")

        payment_replay = await api.post(
            f"/api/v1/actions/{ACTION_ID}/invoices/{OPEN_INVOICE_ID}/payments",
            headers={
                **admin_headers,
                "Idempotency-Key": PAYMENT_KEY,
            },
            json={
                "amountMinor": 36_000,
                "currency": "EUR",
                "receivedOn": PAYMENT_DATE,
                "reference": PAYMENT_REFERENCE,
            },
        )
        payment_replay.raise_for_status()
        cancellation_replay = await api.post(
            (
                f"/api/v1/actions/{ACTION_ID}/invoices/"
                f"{cancellation_invoice_id}/cancellation"
            ),
            headers={
                **admin_headers,
                "Idempotency-Key": CANCELLATION_KEY,
            },
            json={"reason": CANCELLATION_REASON},
        )
        cancellation_replay.raise_for_status()
        if (
            payment_replay.json().get("replayed") is not True
            or cancellation_replay.json().get("replayed") is not True
        ):
            raise ContractFailure("Finanzbefehle sind nicht idempotent")

    counts = await connection.fetchrow(
        """
        SELECT
          (
            SELECT count(*) FROM payment_record WHERE invoice_id = $1
          ) AS payments,
          (
            SELECT count(*) FROM invoice_cancellation WHERE invoice_id = $2
          ) AS cancellations,
          (
            SELECT count(*)
            FROM audit_event
            WHERE event_type = 'invoice_payment_recorded'
              AND payload->>'invoiceId' = $1::text
          ) AS payment_audits,
          (
            SELECT count(*)
            FROM audit_event
            WHERE event_type = 'invoice_cancelled'
              AND payload->>'invoiceId' = $2::text
          ) AS cancellation_audits
        """,
        OPEN_INVOICE_ID,
        cancellation_invoice_id,
    )
    if counts is None or dict(counts) != {
        "payments": 1,
        "cancellations": 1,
        "payment_audits": 1,
        "cancellation_audits": 1,
    }:
        raise ContractFailure(f"Finanz-Audit ist inkonsistent: {dict(counts or {})}")

    invoice_snapshot = await connection.fetchval(
        """
        SELECT to_jsonb(invoice) - ARRAY['status', 'updated_at']::text[]
        FROM invoice
        WHERE id = $1
        """,
        cancellation_invoice_id,
    )
    document_snapshot = await connection.fetchval(
        """
        SELECT to_jsonb(document)
        FROM generated_document AS document
        WHERE invoice_id = $1
          AND status = 'available'
        """,
        cancellation_invoice_id,
    )
    if invoice_snapshot is None or document_snapshot is None:
        raise ContractFailure("Historischer Beleg fehlt nach dem Storno")
    if (
        json_object(invoice_snapshot, label="Rechnungs-Snapshot")
        != state["invoiceSnapshot"]
        or json_object(document_snapshot, label="Dokument-Snapshot")
        != state["documentSnapshot"]
    ):
        raise ContractFailure(
            "Storno veränderte historischen Rechnungs- oder Typst-Dokumentstand"
        )
    print(
        "invoice-settlement-contract: Vollzahlung, Storno, Audit, Replay und "
        "unverändertes Typst-PDF dauerhaft bewiesen"
    )


async def run(arguments: argparse.Namespace) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        if arguments.command == "prepare":
            await prepare(connection, arguments.state, arguments.sessions)
        elif arguments.command == "capture":
            await capture(connection, arguments.state)
        elif arguments.command == "assert":
            await assert_after_browser(connection, arguments.state)
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
    for command_name in ("capture", "assert"):
        command = commands.add_parser(command_name)
        command.add_argument("state", type=Path)
    return value


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
