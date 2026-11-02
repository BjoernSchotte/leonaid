#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL/Twenty invoice-issuing contract for POC-090."""

from __future__ import annotations

import asyncio
import json
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
EXPECTED_PAYMENT_DETAILS = {
    "accountHolder": "Lions Hilfswerk LeonAid Golden e.V.",
    "iban": "DE89370400440532013000",
    "bic": "COBADEFFXXX",
}


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def token_for(user_id: UUID, kind: str) -> str:
    return f"poc090-{kind}-{user_id}-server-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Error response has no stable contract")
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
    payment_details = await connection.fetchval(
        "SELECT payment_details_snapshot FROM invoice WHERE id = $1",
        invoice_id,
    )
    if (
        invoice_count != 1
        or profile_next != 5
        or commitment_status != "invoiced"
        or audit_count != 1
        or receipt_count != 2
        or (
            json.loads(payment_details)
            if isinstance(payment_details, str)
            else payment_details
        )
        != EXPECTED_PAYMENT_DETAILS
    ):
        raise ContractFailure(
            "Invoice, number sequence, order status, audit or "
            "command receipts are not atomic"
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
            raise ContractFailure("The real Twenty address was not changed")


def completion_path(commitment_id: UUID = COMMITMENT_ID) -> str:
    return (
        f"/api/v1/actions/{ACTION_ID}/commitments/{commitment_id}/delivery-completion"
    )


async def exercise_delivery_completion(
    connection: asyncpg.Connection[Any],
    api: httpx.AsyncClient,
    tokens: dict[str, str],
) -> dict[str, Any]:
    """Delivery planning enabled after capture blocks invoicing until completed."""
    window_id = UUID("98000000-0000-4000-8000-000000000001")
    await connection.execute(
        """
        INSERT INTO charity_action_capability (action_id, capability)
        VALUES ($1, 'delivery') ON CONFLICT DO NOTHING
        """,
        ACTION_ID,
    )
    await connection.execute(
        """
        INSERT INTO action_delivery_configuration (action_id, enabled)
        VALUES ($1, true)
        ON CONFLICT (action_id) DO UPDATE
        SET enabled = true, revision = action_delivery_configuration.revision + 1
        """,
        ACTION_ID,
    )
    await connection.execute(
        """
        INSERT INTO action_delivery_window (id, action_id, starts_at, ends_at)
        -- A fixed local day time: a window may not cross local midnight.
        VALUES ($1, $2,
            ((now() AT TIME ZONE 'Europe/Berlin')::date + 1 + time '10:00')
                AT TIME ZONE 'Europe/Berlin',
            ((now() AT TIME ZONE 'Europe/Berlin')::date + 1 + time '12:00')
                AT TIME ZONE 'Europe/Berlin')
        """,
        window_id,
        ACTION_ID,
    )
    blocked = await issue(
        api,
        token=tokens["klara_fresh"],
        idempotency_key="poc090:delivery:incomplete",
    )
    if (
        blocked.status_code != 409
        or error_code(blocked) != "invoice_delivery_incomplete"
    ):
        raise ContractFailure(
            f"Invoice was issued without delivery details: {blocked.status_code} {blocked.text}"
        )
    if await connection.fetchval(
        "SELECT count(*) FROM invoice WHERE commitment_id = $1", COMMITMENT_ID
    ):
        raise ContractFailure("Rejected issuing created an invoice")

    loaded = await api.get(
        f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ID}",
        headers=session_headers(tokens["klara_fresh"]),
    )
    loaded.raise_for_status()
    order = loaded.json()
    recipient = order["invoiceRecipient"]
    if recipient is None or recipient["streetLine1"] != "Sonnenstraße 2":
        raise ContractFailure("Golden order has no billing details")
    body = {
        "expectedVersion": order["deliveryCompletionVersion"],
        "invoiceRecipient": {**recipient, "email": "rechnung@sonnenseite.example"},
        "deliveryRecipient": {
            "recipientName": "Bäckerei Sonnenseite KG, Lager",
            "streetLine1": "Lagerweg 4",
            "postalCode": "10243",
            "city": "Beispielstadt",
            "countryCode": "DE",
        },
        "deliveryWindowId": str(window_id),
    }

    async def complete(token: str, key: str, value: dict[str, Any]) -> httpx.Response:
        return await api.post(
            completion_path(),
            headers={
                **session_headers(token),
                "Idempotency-Key": key,
                "X-Request-ID": f"poc090:{key}",
            },
            json=value,
        )

    denied = await complete(tokens["anna"], "poc090:completion:acquirer", body)
    if denied.status_code != 403:
        raise ContractFailure("Acquirer could complete delivery details")
    finance = await complete(tokens["finn"], "poc090:completion:finance", body)
    if finance.status_code != 403:
        raise ContractFailure("Finance reader could complete delivery details")
    anonymous = await api.post(
        completion_path(),
        headers={"Idempotency-Key": "poc090:completion:anonymous"},
        json=body,
    )
    if anonymous.status_code != 401:
        raise ContractFailure("Anonymous delivery completion was not rejected")
    stale = await complete(
        tokens["klara_fresh"],
        "poc090:completion:stale",
        {**body, "expectedVersion": "0" * 64},
    )
    if stale.status_code != 409 or error_code(stale) != "delivery_completion_conflict":
        raise ContractFailure("Stale delivery completion was accepted")
    accepted = await complete(tokens["klara_fresh"], "poc090:completion:ok", body)
    accepted.raise_for_status()
    completed: dict[str, Any] = accepted.json()
    if (
        completed["status"] != "review_ready"
        or completed["lines"] != order["lines"]
        or completed["totalMinor"] != order["totalMinor"]
        or completed["deliveryWindowId"] != str(window_id)
        or completed["invoiceRecipient"]["email"] != "rechnung@sonnenseite.example"
    ):
        raise ContractFailure("Delivery completion changed the order incorrectly")
    replay = await complete(tokens["klara_fresh"], "poc090:completion:ok", body)
    replay.raise_for_status()
    if not replay.json()["replayed"] or replay.json()["id"] != completed["id"]:
        raise ContractFailure("Delivery completion replay was not exact")
    return completed


async def assert_completion_closed(
    api: httpx.AsyncClient, tokens: dict[str, str], completed: dict[str, Any]
) -> None:
    current = await api.get(
        f"/api/v1/actions/{ACTION_ID}/commitments/{COMMITMENT_ID}",
        headers=session_headers(tokens["klara_fresh"]),
    )
    current.raise_for_status()
    response = await api.post(
        completion_path(),
        headers={
            **session_headers(tokens["klara_fresh"]),
            "Idempotency-Key": "poc090:completion:after-invoice",
        },
        json={
            "expectedVersion": current.json()["deliveryCompletionVersion"],
            "invoiceRecipient": completed["invoiceRecipient"],
            "deliveryRecipient": completed["deliveryRecipient"],
            "deliveryWindowId": completed["deliveryWindowId"],
        },
    )
    if (
        response.status_code != 409
        or error_code(response) != "delivery_completion_closed"
    ):
        raise ContractFailure("An invoiced order could still be edited")


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
            or context_value["profile"]["legalConfigurationVersionId"]
            != "94000000-0000-4000-8000-000000000044"
            or context_value["profile"]["paymentDetails"] != EXPECTED_PAYMENT_DETAILS
            or not context_value["profile"]["readyToIssue"]
        ):
            raise ContractFailure("Admin invoice context is incomplete")

        await connection.execute(
            """
            UPDATE invoice_profile
            SET legal_configuration_version_id = NULL
            WHERE action_id = $1
            """,
            ACTION_ID,
        )
        stale_profile = await issue(
            api,
            token=tokens["klara_fresh"],
            idempotency_key="poc090:stale-legal-configuration",
        )
        if (
            stale_profile.status_code != 409
            or error_code(stale_profile) != "invoice_legal_configuration_stale"
        ):
            raise ContractFailure(
                "Unbound invoice profile was not rejected fail-closed"
            )
        await connection.execute(
            """
            UPDATE invoice_profile
            SET legal_configuration_version_id = $1
            WHERE action_id = $2
            """,
            UUID("94000000-0000-4000-8000-000000000044"),
            ACTION_ID,
        )

        finance_context = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoice-context",
            headers=session_headers(tokens["finn"]),
        )
        finance_context.raise_for_status()
        if finance_context.json()["mayIssue"]:
            raise ContractFailure("Finance reader received issue rights")

        acquirer_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["anna"]),
        )
        if (
            acquirer_list.status_code != 403
            or error_code(acquirer_list) != "invoice_read_required"
        ):
            raise ContractFailure("Acquirer could read invoices")

        finance_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["finn"]),
        )
        finance_list.raise_for_status()
        if len(finance_list.json()["items"]) != 3:
            raise ContractFailure("Finance reader does not see all golden invoices")

        finance_issue = await issue(
            api,
            token=tokens["finn"],
            idempotency_key="poc090:finance:forbidden",
        )
        if (
            finance_issue.status_code != 403
            or error_code(finance_issue) != "invoice_issue_required"
        ):
            raise ContractFailure("Finance reader could issue an invoice")

        stale_issue = await issue(
            api,
            token=tokens["klara_stale"],
            idempotency_key="poc090:stale:fresh-required",
        )
        if (
            stale_issue.status_code != 401
            or error_code(stale_issue) != "fresh_login_required"
        ):
            raise ContractFailure("Invoice issuing did not require a fresh login")
        before_count = await connection.fetchval(
            "SELECT count(*) FROM invoice WHERE commitment_id = $1",
            COMMITMENT_ID,
        )
        if before_count != 0:
            raise ContractFailure("Rejected fresh login created an invoice")

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
            raise ContractFailure("Draft order could be invoiced")

        completed = await exercise_delivery_completion(connection, api, tokens)

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
                "Concurrent issuing created more than one invoice/number"
            )
        invoice_id = UUID(str(values[0]["id"]))
        issued_snapshot = values[0]["recipient"]
        if values[0]["paymentDetails"] != EXPECTED_PAYMENT_DETAILS:
            raise ContractFailure(
                "Invoice does not contain the approved payment details"
            )
        if issued_snapshot["streetLine1"] != "Sonnenstraße 2":
            raise ContractFailure("Invoice does not contain the expected snapshot")
        if issued_snapshot["email"] != completed["invoiceRecipient"]["email"]:
            raise ContractFailure("Invoice does not use the completed billing details")
        await assert_database_result(connection, invoice_id)
        await assert_completion_closed(api, tokens, completed)

        replay = await issue(
            api,
            token=tokens["klara_fresh"],
            idempotency_key="poc090:concurrent:first",
        )
        replay.raise_for_status()
        if replay.json()["id"] != str(invoice_id) or not replay.json()["replayed"]:
            raise ContractFailure("Idempotent replay was not detected")

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
            raise ContractFailure("Conflicting replay was accepted")

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
            raise ContractFailure("Twenty change altered the invoice snapshot")

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
            raise ContractFailure("Database allowed a snapshot overwrite")
        persisted_street = await connection.fetchval(
            "SELECT recipient_snapshot->>'streetLine1' FROM invoice WHERE id = $1",
            invoice_id,
        )
        if persisted_street != "Sonnenstraße 2":
            raise ContractFailure("Immutable snapshot was corrupted")
        try:
            await connection.execute(
                """
                UPDATE invoice
                SET payment_details_snapshot =
                    jsonb_set(payment_details_snapshot, '{iban}', '"DE00000000000000000000"')
                WHERE id = $1
                """,
                invoice_id,
            )
        except asyncpg.PostgresError:
            pass
        else:
            raise ContractFailure("Database allowed a payment details change")
        persisted_payment_details = await connection.fetchval(
            "SELECT payment_details_snapshot FROM invoice WHERE id = $1",
            invoice_id,
        )
        normalized_payment_details = (
            json.loads(persisted_payment_details)
            if isinstance(persisted_payment_details, str)
            else persisted_payment_details
        )
        if normalized_payment_details != EXPECTED_PAYMENT_DETAILS:
            raise ContractFailure("Payment details snapshot was corrupted")

        final_list = await api.get(
            f"/api/v1/actions/{ACTION_ID}/invoices",
            headers=session_headers(tokens["klara_fresh"]),
        )
        final_list.raise_for_status()
        final_value = final_list.json()
        if len(final_value["items"]) != 4 or final_value["currencyTotals"] != [
            {"currency": "EUR", "grossMinor": 64_800, "openMinor": 46_800}
        ]:
            raise ContractFailure(
                f"Invoice list or golden total is wrong: {final_value!r}"
            )

    print(
        "invoice-contract: OK: fresh login, roles, concurrent issuing, "
        "number sequence and snapshot independent of Twenty and configuration"
    )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
