#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL/Twenty invoice-issuing contract for POC-090."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx
from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import (
    TwentyCrmGateway,
    TwentyGatewaySettings,
)
from leonaid.application.crm import CompanyUpdate, PostalAddress
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
COMMITMENT_ID = UUID("80000000-0000-4000-8000-000000000002")
DRAFT_COMMITMENT_ID = UUID("80000000-0000-4000-8000-000000000001")
COMPANY_ID = UUID("40000000-0000-4000-8000-000000000002")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
FINN_ID = UUID("10000000-0000-4000-8000-000000000007")
SESSION_NAMESPACE = UUID("6a6a9df4-b543-4f3f-a603-75687dfcf87f")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID, kind: str) -> str:
    return f"poc090-{kind}-{user_id}-server-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(error.get("code"))


async def seed_sessions(
    connection: asyncpg.Connection[Any],
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    sessions = (
        ("klara_fresh", KLARA_ID, now, now),
        (
            "klara_stale",
            KLARA_ID,
            now - timedelta(days=1),
            now - timedelta(days=1),
        ),
        ("anna", ANNA_ID, now, now),
        ("finn", FINN_ID, now, now),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [KLARA_ID, ANNA_ID, FINN_ID],
    )
    tokens: dict[str, str] = {}
    for kind, user_id, created_at, fresh_login_at in sessions:
        token = token_for(user_id, kind)
        tokens[kind] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $5)
            """,
            uuid5(SESSION_NAMESPACE, kind),
            user_id,
            session_token_digest(token),
            created_at + SESSION_LIFETIME,
            now,
            fresh_login_at,
            created_at,
        )
    return tokens


async def issue(
    api: httpx.AsyncClient,
    *,
    token: str,
    idempotency_key: str,
    service_on: str = "2026-11-15",
) -> httpx.Response:
    return await api.post(
        f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ID}/invoice",
        headers={
            **session_headers(token),
            "Idempotency-Key": idempotency_key,
            "X-Request-ID": f"poc090:{idempotency_key}",
        },
        json={"serviceOn": service_on},
    )


async def assert_database_result(
    connection: asyncpg.Connection[Any],
    invoice_id: UUID,
) -> None:
    invoice_count = await connection.fetchval(
        "SELECT count(*) FROM invoice WHERE commitment_id = $1",
        COMMITMENT_ID,
    )
    profile_next = await connection.fetchval(
        "SELECT next_number FROM invoice_profile WHERE action_id = $1",
        ACTION_ID,
    )
    commitment_status = await connection.fetchval(
        "SELECT status FROM commitment WHERE id = $1",
        COMMITMENT_ID,
    )
    audit_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM audit_event
        WHERE entity_type = 'invoice'
          AND entity_id = $1
          AND event_type = 'invoice_issued'
          AND payload->>'number' = 'KT26-0004'
        """,
        invoice_id,
    )
    receipt_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM command_receipt
        WHERE command_type = 'issue_invoice_v1'
          AND result->>'invoiceId' = $1
          AND completed_at IS NOT NULL
        """,
        str(invoice_id),
    )
    if (
        invoice_count != 1
        or profile_next != 5
        or commitment_status != "invoiced"
        or audit_count != 1
        or receipt_count != 2
    ):
        raise ContractFailure(
            "Rechnung, Nummernkreis, Bestellstatus, Audit oder "
            "Befehlsnachweise sind nicht atomar"
        )


async def mutate_twenty_company() -> None:
    settings = TwentyGatewaySettings(
        base_url=require_env("TWENTY_BASE_URL"),
        api_key=SecretStr(require_env("TWENTY_INTEGRATION_API_KEY")),
        timeout_seconds=10,
    )
    async with TwentyCrmGateway(settings) as gateway:
        updated, _ = await gateway.update_company(
            COMPANY_ID,
            COMPANY_ID,
            CompanyUpdate(
                address=PostalAddress(
                    street_line_1="Nachträgliche CRM-Straße 99",
                    postal_code="99999",
                    city="CRM-Neustadt",
                    country="Deutschland",
                )
            ),
            correlation_id="poc090:twenty:address-change",
        )
        if (
            updated.data.address.street_line_1 != "Nachträgliche CRM-Straße 99"
            or updated.data.address.postal_code != "99999"
        ):
            raise ContractFailure("Die reale Twenty-Adresse wurde nicht geändert")


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    tokens = await seed_sessions(connection)
    api_url = require_env("API_BASE_URL").rstrip("/")
    async with httpx.AsyncClient(base_url=api_url, timeout=60) as api:
        admin_context = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoice-context",
            headers=session_headers(tokens["klara_fresh"]),
        )
        admin_context.raise_for_status()
        context_value = admin_context.json()
        if (
            context_value["actionName"] != "Krapfentaxi 2026"
            or not context_value["mayIssue"]
            or context_value["profile"]["nextInvoiceNumber"] != "KT26-0004"
            or not context_value["profile"]["readyToIssue"]
        ):
            raise ContractFailure("Admin-Rechnungskontext ist unvollständig")

        finance_context = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoice-context",
            headers=session_headers(tokens["finn"]),
        )
        finance_context.raise_for_status()
        if finance_context.json()["mayIssue"]:
            raise ContractFailure("Finanz-Leser erhielt Freigaberechte")

        acquirer_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["anna"]),
        )
        if (
            acquirer_list.status_code != 403
            or error_code(acquirer_list) != "invoice_read_required"
        ):
            raise ContractFailure("Akquisiteur konnte Rechnungen lesen")

        finance_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["finn"]),
        )
        finance_list.raise_for_status()
        if len(finance_list.json()["items"]) != 3:
            raise ContractFailure("Finanz-Leser sieht nicht alle Golden-Rechnungen")

        finance_issue = await issue(
            api,
            token=tokens["finn"],
            idempotency_key="poc090:finance:forbidden",
        )
        if (
            finance_issue.status_code != 403
            or error_code(finance_issue) != "invoice_issue_required"
        ):
            raise ContractFailure("Finanz-Leser konnte eine Rechnung freigeben")

        stale_issue = await issue(
            api,
            token=tokens["klara_stale"],
            idempotency_key="poc090:stale:fresh-required",
        )
        if (
            stale_issue.status_code != 401
            or error_code(stale_issue) != "fresh_login_required"
        ):
            raise ContractFailure("Rechnungsfreigabe verlangte keinen Fresh Login")
        before_count = await connection.fetchval(
            "SELECT count(*) FROM invoice WHERE commitment_id = $1",
            COMMITMENT_ID,
        )
        if before_count != 0:
            raise ContractFailure("Abgewiesener Fresh Login erzeugte eine Rechnung")

        draft_issue = await api.post(
            f"/api/v1/actions/{ACTION_ID}/commitments/{DRAFT_COMMITMENT_ID}/invoice",
            headers={
                **session_headers(tokens["klara_fresh"]),
                "Idempotency-Key": "poc090:draft:forbidden",
                "X-Request-ID": "poc090:draft:forbidden",
            },
            json={"serviceOn": "2026-11-15"},
        )
        if (
            draft_issue.status_code != 422
            or error_code(draft_issue) != "invoice_commitment_not_review_ready"
        ):
            raise ContractFailure("Entwurfsbestellung konnte fakturiert werden")

        first, second = await asyncio.gather(
            issue(
                api,
                token=tokens["klara_fresh"],
                idempotency_key="poc090:concurrent:first",
            ),
            issue(
                api,
                token=tokens["klara_fresh"],
                idempotency_key="poc090:concurrent:second",
            ),
        )
        first.raise_for_status()
        second.raise_for_status()
        values = (first.json(), second.json())
        ids = {value["id"] for value in values}
        numbers = {value["number"] for value in values}
        replays = sorted(value["replayed"] for value in values)
        if len(ids) != 1 or numbers != {"KT26-0004"} or replays != [False, True]:
            raise ContractFailure(
                "Konkurrierende Freigabe erzeugte mehr als eine Rechnung/Nummer"
            )
        invoice_id = UUID(str(values[0]["id"]))
        issued_snapshot = values[0]["recipient"]
        if issued_snapshot["streetLine1"] != "Sonnenstraße 2":
            raise ContractFailure("Rechnung enthält nicht den erwarteten Snapshot")
        await assert_database_result(connection, invoice_id)

        replay = await issue(
            api,
            token=tokens["klara_fresh"],
            idempotency_key="poc090:concurrent:first",
        )
        replay.raise_for_status()
        if replay.json()["id"] != str(invoice_id) or not replay.json()["replayed"]:
            raise ContractFailure("Idempotente Wiederholung wurde nicht erkannt")

        conflicting_replay = await issue(
            api,
            token=tokens["klara_fresh"],
            idempotency_key="poc090:concurrent:first",
            service_on="2026-11-14",
        )
        if (
            conflicting_replay.status_code != 409
            or error_code(conflicting_replay) != "idempotency_conflict"
        ):
            raise ContractFailure("Abweichende Wiederholung wurde akzeptiert")

        await mutate_twenty_company()
        after_crm_change = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["finn"]),
        )
        after_crm_change.raise_for_status()
        stored = next(
            item["invoice"]
            for item in after_crm_change.json()["items"]
            if item["invoice"]["id"] == str(invoice_id)
        )
        if stored["recipient"] != issued_snapshot:
            raise ContractFailure("Twenty-Änderung veränderte den Rechnungssnapshot")

        try:
            await connection.execute(
                """
                UPDATE invoice
                SET recipient_snapshot =
                    jsonb_set(recipient_snapshot::jsonb, '{streetLine1}', '"DB Neu 1"')
                WHERE id = $1
                """,
                invoice_id,
            )
        except asyncpg.PostgresError:
            pass
        else:
            raise ContractFailure("Datenbank erlaubte Snapshot-Überschreibung")
        persisted_street = await connection.fetchval(
            "SELECT recipient_snapshot->>'streetLine1' FROM invoice WHERE id = $1",
            invoice_id,
        )
        if persisted_street != "Sonnenstraße 2":
            raise ContractFailure("Unveränderlicher Snapshot wurde beschädigt")

        final_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["klara_fresh"]),
        )
        final_list.raise_for_status()
        final_value = final_list.json()
        if len(final_value["items"]) != 4 or final_value["currencyTotals"] != [
            {"currency": "EUR", "grossMinor": 64_800}
        ]:
            raise ContractFailure(
                f"Rechnungsliste oder Golden-Summe ist falsch: {final_value!r}"
            )

    print(
        "invoice-contract: OK: Fresh Login, Rollen, konkurrierende Freigabe, "
        "Nummernkreis und Twenty-unabhängiger Snapshot"
    )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
