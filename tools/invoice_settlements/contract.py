#!/usr/bin/env python3
"""Real API/PostgreSQL contract for payment entries, reversals and cancellations."""

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
from leonaid.domain.calendar import local_day

# The service date must lie in the golden action period, which the seed
# places around the seed day (tools/seed/golden.py); today always does.
SERVICE_ON = local_day(datetime.now(timezone.utc)).isoformat()

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
LIFECYCLE_KEY = "poc095:lifecycle-v1"
# Entries the API lifecycle books on the open invoice (all reversed again).
LIFECYCLE_ENTRIES = 3
# The browser books a partial entry, reverses it, then the full payment.
BROWSER_ENTRIES = 2
BROWSER_REVERSALS = 1
PAYMENT_DATE = "2026-07-20"
PAYMENT_REFERENCE = "Bankumsatz KT26-0001 / 20.07.2026"
CANCELLATION_REASON = "Bestellung nach Rechnungsfreigabe vollständig zurückgenommen."


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"poc095-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Error response has no stable contract")
    return str(value["error"].get("code"))


def read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractFailure("The POC-095 state is invalid")
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
        raise ContractFailure(f"{label} is not a JSON object")
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
        raise ContractFailure("Invoice ledger has no record list")
    for item in items:
        if (
            isinstance(item, dict)
            and isinstance(item.get("invoice"), dict)
            and item["invoice"].get("id") == str(invoice_id)
        ):
            return item
    raise ContractFailure(f"Invoice {invoice_id} is missing from the ledger")


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
            raise ContractFailure(f"Persona {label} could record a payment")

    zero = await api.post(
        endpoint,
        headers={
            **session_headers(tokens["klara"]),
            "Idempotency-Key": "poc095:zero:rejected",
        },
        json={**payload, "amountMinor": 0},
    )
    if zero.status_code != 422:
        raise ContractFailure("A payment of 0,00 € was not rejected")

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
        raise ContractFailure("Mismatched payment currency was not rejected")


async def ledger(api: httpx.AsyncClient, token: str) -> dict[str, Any]:
    response = await api.get(
        f"/api/v1/actions/{ACTION_ID}/invoices",
        headers=session_headers(token),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure("Invoice ledger is not an object")
    return payload


def expect_settlement(
    payload: dict[str, Any],
    *,
    label: str,
    status: str,
    paid: int,
    open_: int,
    overpaid: int,
    invoice_status: set[str],
    open_total: int,
) -> int:
    record = invoice_record(payload, OPEN_INVOICE_ID)
    observed = {
        "settlementStatus": record.get("settlementStatus"),
        "paidMinor": record.get("paidMinor"),
        "openMinor": record.get("openMinor"),
        "overpaidMinor": record.get("overpaidMinor"),
        "invoiceStatus": record.get("invoice", {}).get("status"),
        "openTotal": [
            item.get("openMinor")
            for item in payload.get("currencyTotals", [])
            if item.get("currency") == "EUR"
        ],
    }
    if (
        observed["settlementStatus"] != status
        or observed["paidMinor"] != paid
        or observed["openMinor"] != open_
        or observed["overpaidMinor"] != overpaid
        or observed["invoiceStatus"] not in invoice_status
        or observed["openTotal"] != [open_total]
    ):
        raise ContractFailure(f"{label}: unexpected settlement {observed}")
    version = record.get("settlementVersion")
    if not isinstance(version, int):
        raise ContractFailure(f"{label}: settlement version missing")
    return version


async def post_payment(
    api: httpx.AsyncClient,
    token: str,
    *,
    key: str,
    amount: int,
    version: int | None,
    note: str | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "amountMinor": amount,
        "currency": "EUR",
        "receivedOn": PAYMENT_DATE,
        "reference": PAYMENT_REFERENCE,
    }
    if version is not None:
        body["expectedSettlementVersion"] = version
    if note is not None:
        body["note"] = note
    return await api.post(
        f"/api/v1/actions/{ACTION_ID}/invoices/{OPEN_INVOICE_ID}/payments",
        headers={**session_headers(token), "Idempotency-Key": key},
        json=body,
    )


async def post_reversal(
    api: httpx.AsyncClient,
    token: str,
    *,
    payment_id: str,
    key: str,
    version: int | None,
    reason: str = "Bank hat die Gutschrift zurückgeholt.",
) -> httpx.Response:
    body: dict[str, Any] = {"reason": reason}
    if version is not None:
        body["expectedSettlementVersion"] = version
    return await api.post(
        (
            f"/api/v1/actions/{ACTION_ID}/invoices/{OPEN_INVOICE_ID}/"
            f"payments/{payment_id}/reversal"
        ),
        headers={**session_headers(token), "Idempotency-Key": key},
        json=body,
    )


def created(response: httpx.Response, label: str) -> dict[str, Any]:
    if response.status_code != 201:
        raise ContractFailure(
            f"{label}: expected 201, got {response.status_code} {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure(f"{label}: response is not an object")
    return payload


def refused(response: httpx.Response, status: int, code: str, label: str) -> None:
    if response.status_code != status or error_code(response) != code:
        raise ContractFailure(
            f"{label}: expected {status} {code}, got "
            f"{response.status_code} {response.text}"
        )


async def assert_partial_payment_lifecycle(
    api: httpx.AsyncClient,
    tokens: dict[str, str],
) -> None:
    """Partial, over and reversed entries; sums, versions, replay, races."""

    klara = tokens["klara"]
    # The golden open invoice is unpaid and, in this stack, never delivered.
    unpaid = {"issued", "sent"}
    version = expect_settlement(
        await ledger(api, klara),
        label="start",
        status="open",
        paid=0,
        open_=36_000,
        overpaid=0,
        invoice_status=unpaid,
        open_total=36_000,
    )
    if version != 0:
        raise ContractFailure(f"Unpaid invoice starts at version {version}")

    first = created(
        await post_payment(
            api,
            klara,
            key=f"{LIFECYCLE_KEY}:first",
            amount=10_000,
            version=version,
            note="Erste Rate",
        ),
        "partial payment",
    )
    if first.get("note") != "Erste Rate" or first.get("replayed") is not False:
        raise ContractFailure(f"Partial payment response is incomplete: {first}")
    version_after_first = expect_settlement(
        await ledger(api, klara),
        label="partial",
        status="partially_paid",
        paid=10_000,
        open_=26_000,
        overpaid=0,
        invoice_status=unpaid,
        open_total=26_000,
    )

    replay = created(
        await post_payment(
            api,
            klara,
            key=f"{LIFECYCLE_KEY}:first",
            amount=10_000,
            version=version,
            note="Erste Rate",
        ),
        "partial payment replay",
    )
    if replay.get("id") != first.get("id") or replay.get("replayed") is not True:
        raise ContractFailure("Replaying a payment command booked it again")
    refused(
        await post_payment(
            api,
            klara,
            key=f"{LIFECYCLE_KEY}:first",
            amount=10_001,
            version=version_after_first,
        ),
        409,
        "idempotency_conflict",
        "reused payment key",
    )
    refused(
        await post_payment(
            api,
            klara,
            key=f"{LIFECYCLE_KEY}:stale",
            amount=26_000,
            version=version,
        ),
        409,
        "invoice_settlement_stale",
        "stale payment form",
    )
    refused(
        await post_reversal(
            api,
            tokens["finn"],
            payment_id=str(first["id"]),
            key=f"{LIFECYCLE_KEY}:finn-reversal",
            version=version_after_first,
        ),
        403,
        "invoice_settlement_required",
        "finance reader reversal",
    )

    second = created(
        await post_payment(
            api,
            klara,
            key=f"{LIFECYCLE_KEY}:second",
            amount=30_000,
            version=version_after_first,
        ),
        "over payment",
    )
    version_overpaid = expect_settlement(
        await ledger(api, klara),
        label="overpaid",
        status="overpaid",
        paid=40_000,
        open_=0,
        overpaid=4_000,
        invoice_status={"paid"},
        open_total=0,
    )

    refused(
        await post_reversal(
            api,
            klara,
            payment_id=str(first["id"]),
            key=f"{LIFECYCLE_KEY}:reverse-stale",
            version=version_after_first,
        ),
        409,
        "invoice_settlement_stale",
        "stale reversal form",
    )
    reversal = created(
        await post_reversal(
            api,
            klara,
            payment_id=str(first["id"]),
            key=f"{LIFECYCLE_KEY}:reverse-first",
            version=version_overpaid,
        ),
        "reversal",
    )
    if reversal.get("paymentId") != first.get("id"):
        raise ContractFailure(f"Reversal names another entry: {reversal}")
    version_reversed = expect_settlement(
        await ledger(api, klara),
        label="after reversal",
        status="partially_paid",
        paid=30_000,
        open_=6_000,
        overpaid=0,
        invoice_status=unpaid,
        open_total=6_000,
    )
    reversal_replay = created(
        await post_reversal(
            api,
            klara,
            payment_id=str(first["id"]),
            key=f"{LIFECYCLE_KEY}:reverse-first",
            version=version_overpaid,
        ),
        "reversal replay",
    )
    if (
        reversal_replay.get("id") != reversal.get("id")
        or reversal_replay.get("replayed") is not True
    ):
        raise ContractFailure("Replaying a reversal reversed it again")
    refused(
        await post_reversal(
            api,
            klara,
            payment_id=str(first["id"]),
            key=f"{LIFECYCLE_KEY}:reverse-again",
            version=version_reversed,
        ),
        409,
        "invoice_payment_already_reversed",
        "second reversal",
    )
    refused(
        await post_reversal(
            api,
            klara,
            payment_id=str(UUID(int=0)),
            key=f"{LIFECYCLE_KEY}:reverse-unknown",
            version=None,
        ),
        404,
        "invoice_payment_not_found",
        "unknown entry",
    )

    # Two forms opened on the same version: exactly one entry is booked.
    racers = await asyncio.gather(
        *(
            post_payment(
                api,
                klara,
                key=f"{LIFECYCLE_KEY}:race-{index}",
                amount=6_000,
                version=version_reversed,
            )
            for index in range(2)
        )
    )
    statuses = sorted(response.status_code for response in racers)
    if statuses != [201, 409] or any(
        response.status_code == 409
        and error_code(response) != "invoice_settlement_stale"
        for response in racers
    ):
        raise ContractFailure(
            f"Concurrent payments were not serialized: "
            f"{[(r.status_code, r.text) for r in racers]}"
        )
    winner = next(response for response in racers if response.status_code == 201)
    version_raced = expect_settlement(
        await ledger(api, klara),
        label="after race",
        status="paid",
        paid=36_000,
        open_=0,
        overpaid=0,
        invoice_status={"paid"},
        open_total=0,
    )

    # Back to unpaid, so the browser starts from the golden open invoice.
    version_now = version_raced
    for label, payment_id in (
        ("race", str(winner.json()["id"])),
        ("second", str(second["id"])),
    ):
        created(
            await post_reversal(
                api,
                klara,
                payment_id=payment_id,
                key=f"{LIFECYCLE_KEY}:reset-{label}",
                version=version_now,
            ),
            f"reset {label}",
        )
        version_now = invoice_record(await ledger(api, klara), OPEN_INVOICE_ID)[
            "settlementVersion"
        ]
    versions = [
        version,
        version_after_first,
        version_overpaid,
        version_reversed,
        version_raced,
        version_now,
    ]
    if versions != sorted(set(versions)):
        raise ContractFailure(f"Settlement versions do not grow: {versions}")
    final = await ledger(api, klara)
    expect_settlement(
        final,
        label="reset",
        status="open",
        paid=0,
        open_=36_000,
        overpaid=0,
        invoice_status=unpaid,
        open_total=36_000,
    )
    entries = invoice_record(final, OPEN_INVOICE_ID).get("payments", [])
    if (
        len(entries) != LIFECYCLE_ENTRIES
        or any(entry.get("reversal") is None for entry in entries)
        or invoice_record(final, OPEN_INVOICE_ID).get("payment") is not None
    ):
        raise ContractFailure(f"Reversed entries are not all kept: {entries}")
    if await ledger(api, tokens["finn"]) != final:
        raise ContractFailure("Finance reader sees another ledger than the admin")


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
                "Golden ledger does not distinguish open, paid and cancelled"
            )

        await assert_negative_payment_cases(api, tokens)
        await assert_partial_payment_lifecycle(api, tokens)

        response = await api.post(
            f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ID}/invoice",
            headers={
                **session_headers(tokens["klara"]),
                "Idempotency-Key": "poc095:issue:cancellation-case-v1",
            },
            json={"serviceOn": SERVICE_ON},
        )
        response.raise_for_status()
        invoice = response.json()
    if invoice.get("number") != "KT26-0004" or invoice.get("status") != "issued":
        raise ContractFailure(
            f"Invoice for the cancellation case was not issued: {invoice}"
        )
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
        "invoice-settlement-contract: roles, golden status, partial and over "
        "payments, reversals, versions, replay and races proven"
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
        raise ContractFailure(
            "Typst PDF and invoice snapshot are missing before cancellation"
        )
    state["invoiceSnapshot"] = json_object(
        invoice_snapshot,
        label="Invoice snapshot",
    )
    state["documentSnapshot"] = json_object(
        document_snapshot,
        label="Document snapshot",
    )
    write_state(state_path, state)
    print(
        "invoice-settlement-contract: immutable invoice and "
        "Typst document state saved before the browser action"
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
            or open_record.get("settlementStatus") != "paid"
            or open_record.get("openMinor") != 0
            or open_record.get("paidMinor") != 36_000
            or open_record.get("payment", {}).get("reference") != PAYMENT_REFERENCE
            or cancellation_record.get("invoice", {}).get("status") != "cancelled"
            or cancellation_record.get("openMinor") != 0
            or cancellation_record.get("cancellation", {}).get("reason")
            != CANCELLATION_REASON
        ):
            raise ContractFailure("Browser actions are inconsistent in the ledger")

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
            raise ContractFailure("Finance commands are not idempotent")

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
          ) AS cancellation_audits,
          (
            SELECT count(*) FROM payment_reversal WHERE invoice_id = $1
          ) AS reversals,
          (
            SELECT count(*)
            FROM audit_event
            WHERE event_type = 'invoice_payment_reversed'
              AND payload->>'invoiceId' = $1::text
          ) AS reversal_audits
        """,
        OPEN_INVOICE_ID,
        cancellation_invoice_id,
    )
    entries = LIFECYCLE_ENTRIES + BROWSER_ENTRIES
    reversals = LIFECYCLE_ENTRIES + BROWSER_REVERSALS
    if counts is None or dict(counts) != {
        "payments": entries,
        "cancellations": 1,
        "payment_audits": entries,
        "cancellation_audits": 1,
        "reversals": reversals,
        "reversal_audits": reversals,
    }:
        raise ContractFailure(f"Finance audit is inconsistent: {dict(counts or {})}")

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
        raise ContractFailure("Historical record is missing after the cancellation")
    if (
        json_object(invoice_snapshot, label="Invoice snapshot")
        != state["invoiceSnapshot"]
        or json_object(document_snapshot, label="Document snapshot")
        != state["documentSnapshot"]
    ):
        raise ContractFailure(
            "Cancellation changed the historical invoice or Typst document state"
        )
    print(
        "invoice-settlement-contract: partial, over and full payments, reversals, "
        "cancellation, audit, replay and unchanged Typst PDF durably proven"
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
            raise ContractFailure(f"Unknown command: {arguments.command}")
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
