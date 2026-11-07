#!/usr/bin/env python3
"""Buyer mails of public orders through the real outbox, SMTP and Mailpit.

Steps, with a real worker run (``run-until-idle``) between them:

``snapshot``      before any order: remember the public orders and mails
                  that already exist (shared stacks keep earlier data).
``confirmations`` every new public order has exactly one confirmation job,
                  one SMTP ledger row and one Mailpit message with the
                  order, the club details and the links. Then one sent job
                  is put back to pending (a lost completion), and one order
                  is cancelled over HTTP, twice with the same key.
                  A name with a forged paragraph or a bidi override is
                  refused (422). Another order is cancelled while its
                  recipient is at the per-address limit.
``final``         the re-run job sent nothing new; the cancellation notice
                  arrived exactly once, without the internal reason; the
                  limited notice is dead-lettered, sent nothing and shows in
                  the operations view.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.application.order_mails import (
    RECIPIENT_LIMIT,
    delivery_window_label,
    recipient_sha256,
)
from leonaid.application.delivery_completion import delivery_completion_version
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from tools.identity.contract import KLARA_ID, SYSTEM_ID, create_session
from tools.public_orders.contract import order_body, public_context

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
CONFIRMATION = "order.confirmation.mail.v1"
CANCELLATION = "order.cancellation.mail.v1"
# Internal: a manager's reason and note never reach the buyer.
REASON = "Lieferadresse außerhalb des Liefergebiets (intern)"
NOTE = "Interne Notiz: Fahrer Bernd informiert"


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def money(amount_minor: int) -> str:
    whole, fraction = divmod(amount_minor, 100)
    return f"{whole:,}".replace(",", ".") + f",{fraction:02d} €"


async def mailpit_messages(mailpit: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await mailpit.get("/api/v1/messages", params={"limit": 1000})
    response.raise_for_status()
    value = response.json()
    messages = value.get("messages")
    if not isinstance(messages, list) or int(value.get("total", 0)) > len(messages):
        raise ContractFailure("Mailpit list is incomplete")
    return messages


def recipients(summary: dict[str, Any]) -> set[str]:
    return {
        str(item.get("Address", "")).casefold()
        for item in summary.get("To") or []
        if isinstance(item, dict)
    }


async def messages_for(
    mailpit: httpx.AsyncClient, reference: str, subject_prefix: str
) -> list[dict[str, Any]]:
    found = []
    for summary in await mailpit_messages(mailpit):
        subject = str(summary.get("Subject", ""))
        if reference in subject and subject.startswith(subject_prefix):
            detail = await mailpit.get(f"/api/v1/message/{summary['ID']}")
            detail.raise_for_status()
            found.append({**summary, **detail.json()})
    return found


async def new_orders(
    connection: asyncpg.Connection[Any], known: list[str]
) -> list[asyncpg.Record]:
    return list(
        await connection.fetch(
            """
            SELECT id, public_reference, customer_snapshot->>'email' AS email,
                total_minor, message_snapshot, delivery_window_snapshot
            FROM commitment
            WHERE source = 'public_form' AND NOT (id = ANY($1::uuid[]))
            ORDER BY created_at, id
            """,
            [UUID(item) for item in known],
        )
    )


async def snapshot(connection: asyncpg.Connection[Any], state: Path) -> None:
    known = await connection.fetch(
        "SELECT id FROM commitment WHERE source = 'public_form'"
    )
    state.write_text(
        json.dumps({"known": [str(row["id"]) for row in known]}), encoding="utf-8"
    )


async def legal_name(connection: asyncpg.Connection[Any]) -> str:
    value = await connection.fetchval(
        """
        SELECT version.legal_name
        FROM legal_configuration_state AS state
        JOIN legal_configuration_version AS version
          ON version.id = state.active_version_id
        """
    )
    if not value:
        raise ContractFailure("No active legal configuration")
    return str(value)


async def confirmations(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    orders = await new_orders(connection, data["known"])
    if len(orders) < 3:
        raise ContractFailure(f"Too few public orders to prove: {len(orders)}")
    club = await legal_name(connection)
    windows = 0
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        for order in orders:
            key = f"order-confirmation-mail:{order['id']}"
            job = await connection.fetchrow(
                """
                SELECT status, payload,
                    (SELECT count(*) FROM outbox_event AS other
                     WHERE other.aggregate_id = event.aggregate_id
                       AND other.event_type = event.event_type) AS jobs,
                    (SELECT count(*) FROM mail_delivery
                     WHERE mail_delivery.idempotency_key = event.idempotency_key
                       AND mail_delivery.status = 'sent') AS sent
                FROM outbox_event AS event
                WHERE event.idempotency_key = $1
                """,
                key,
            )
            if job is None or job["jobs"] != 1:
                raise ContractFailure(f"Order {order['id']} has no single job")
            if job["status"] != "completed" or job["sent"] != 1:
                raise ContractFailure(f"Confirmation not sent once: {dict(job)}")
            payload = json.loads(job["payload"])
            if set(payload) != {
                "actionId",
                "commitmentId",
                "campaignUrl",
                "privacyUrl",
                "imprintUrl",
            } or "@" in json.dumps(payload):
                raise ContractFailure(f"Job payload carries more than ids: {payload}")
            reference = str(order["public_reference"])
            found = await messages_for(mailpit, reference, "Ihre Bestellung bei ")
            if len(found) != 1:
                raise ContractFailure(f"{len(found)} confirmations for {reference}")
            mail = found[0]
            text = str(mail.get("Text", ""))
            if recipients(mail) != {str(order["email"]).casefold()}:
                raise ContractFailure(f"Confirmation recipient differs: {reference}")
            expected = (
                f"Bestellnummer: {reference}",
                f"Gesamtbetrag: {money(int(order['total_minor']))}",
                "Zur Aktion: https://",
                club,
                "/impressum",
                "Datenschutz: https://",
                "/datenschutz",
                "Guten Tag,",
            )
            missing = [item for item in expected if item not in text]
            if missing or not any(
                line.startswith("Zur Aktion: ") and line.endswith("/krapfentaxi")
                for line in text.splitlines()
            ):
                raise ContractFailure(f"Confirmation {reference} lacks {missing}")
            if order["message_snapshot"] and order["message_snapshot"] in text:
                raise ContractFailure("The order message reached the buyer")
            if order["delivery_window_snapshot"] is not None:
                windows += 1
                window = order["delivery_window_snapshot"]
                label = delivery_window_label(
                    window if isinstance(window, dict) else json.loads(window)
                )
                if f"Lieferfenster: {label}" not in text:
                    raise ContractFailure(f"Window missing in {reference}")
        if windows < 1:
            raise ContractFailure("No order with a delivery window was mailed")
        # A lost completion: the job runs again and must not send twice.
        redelivered = orders[0]
        status = await connection.execute(
            """
            UPDATE outbox_event
            SET status = 'pending', completed_at = NULL, available_at = now()
            WHERE idempotency_key = $1 AND status = 'completed'
            """,
            f"order-confirmation-mail:{redelivered['id']}",
        )
        if status != "UPDATE 1":
            raise ContractFailure("Could not re-queue the sent confirmation")
        cancelled = orders[-1]
        cancellation = await cancel(connection, cancelled["id"], times=2)
        # Another buyer at the per-address limit: synthetic ledger rows
        # stand for earlier order mails to that address within the hour.
        limited = next(
            order
            for order in orders[1:-1]
            if str(order["email"]).casefold() != str(cancelled["email"]).casefold()
        )
        flood = [f"order-confirmation-mail:{uuid4()}" for _ in range(RECIPIENT_LIMIT)]
        await connection.executemany(
            """
            INSERT INTO mail_delivery (
                id, outbox_event_id, idempotency_key, message_id,
                recipient_sha256, status
            )
            VALUES ($1, NULL, $2, $3, $4, 'sent')
            """,
            [
                (
                    uuid4(),
                    key,
                    f"<{uuid4().hex}@limit-proof.leonaid.invalid>",
                    recipient_sha256(str(limited["email"])),
                )
                for key in flood
            ],
        )
        await cancel(connection, limited["id"], times=1)
    await refused_injection(connection)
    data.update(
        {
            "orders": [str(order["id"]) for order in orders],
            "redelivered": str(redelivered["id"]),
            "redeliveredReference": str(redelivered["public_reference"]),
            "cancelled": str(cancelled["id"]),
            "cancelledReference": str(cancelled["public_reference"]),
            "cancelledEmail": str(cancelled["email"]),
            "cancellation": cancellation,
            "windows": windows,
            "limited": str(limited["id"]),
            "limitedReference": str(limited["public_reference"]),
            "flood": flood,
        }
    )
    state.write_text(json.dumps(data), encoding="utf-8")
    print(
        f"public-order-mails: {len(orders)} confirmations sent once each "
        f"({windows} with a delivery window)"
    )


async def refused_injection(connection: asyncpg.Connection[Any]) -> None:
    """A forged paragraph or a bidi override in an address never gets in."""

    before = await connection.fetchval(
        "SELECT count(*) FROM commitment WHERE source = 'public_form'"
    )
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        token, _offering = await public_context(api)
        for index, (label, field, value, code) in enumerate(
            (
                (
                    "paragraph",
                    "recipientName",
                    "Max\n\nWichtig: Bitte überweisen Sie vorab auf DE12 3456.",
                    "public_order_delivery_recipient_invalid",
                ),
                (
                    "bidi",
                    "city",
                    "Augs\u202egrub",
                    "public_order_delivery_recipient_invalid",
                ),
                (
                    "link",
                    "streetLine1",
                    "www.zahlung-vorab.example 1",
                    "public_order_delivery_recipient_invalid",
                ),
                # A lone surrogate must be a clear 422, never a 500 at storage.
                (
                    "surrogate",
                    "recipientName",
                    "Ina\ud800",
                    "public_order_delivery_recipient_invalid",
                ),
            )
        ):
            body = order_body(
                token=token,
                command=uuid4(),
                given_name="Ina",
                family_name="Injektion",
                email="ina.injektion@leonaid.invalid",
                company_name=None,
                quantity=1,
            )
            delivery = dict(cast(dict[str, object], body["deliveryRecipient"]))
            delivery[field] = value
            body["deliveryRecipient"] = delivery
            # ASCII-escaped JSON: a lone surrogate cannot be encoded as UTF-8.
            response = await api.post(
                "/api/v1/public/actions/krapfentaxi/orders",
                content=json.dumps(body),
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": f"poc072:mail-injection-{label}",
                    "X-LeonAid-Order-Key": require_env("LEONAID_ORDER_SUBMISSION_KEY"),
                    "X-Forwarded-For": f"203.0.113.{76 + index}",
                    "User-Agent": f"LeonAid Contract/mail-injection-{label}",
                },
            )
            payload = response.json()
            if (
                response.status_code != 422
                or payload.get("error", {}).get("code") != code
                or "Lieferanschrift" not in payload["error"]["message"]
            ):
                raise ContractFailure(
                    f"Injection {label} was not refused: {response.status_code}"
                )
    after = await connection.fetchval(
        "SELECT count(*) FROM commitment WHERE source = 'public_form'"
    )
    if after != before:
        raise ContractFailure("A refused injection order was stored")


async def cancel(
    connection: asyncpg.Connection[Any], order_id: UUID, *, times: int
) -> str:
    order = await AsyncpgCommitmentRepository._get(connection, order_id, replayed=False)
    token = await create_session(connection, KLARA_ID, now=datetime.now(timezone.utc))
    key = f"public-order-mail-cancel:{uuid4()}"
    body = {
        "expectedVersion": delivery_completion_version(order),
        "reason": REASON,
        "note": NOTE,
    }
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        results = []
        for _ in range(times):
            response = await api.post(
                f"/api/v1/actions/{ACTION_ID}/commitments/{order_id}/cancellation",
                headers={
                    "Cookie": f"{SESSION_COOKIE_NAME}={token}",
                    "Idempotency-Key": key,
                },
                json=body,
            )
            if response.status_code != 201:
                raise ContractFailure(f"Cancellation failed: {response.text}")
            results.append(response.json())
    if len({result["cancellation"]["id"] for result in results}) != 1:
        raise ContractFailure("The replayed cancellation differs")
    jobs = await connection.fetchval(
        """
        SELECT count(*) FROM outbox_event
        WHERE aggregate_id = $1 AND event_type = $2
        """,
        order_id,
        CANCELLATION,
    )
    if jobs != 1:
        raise ContractFailure(f"Cancellation queued {jobs} notices")
    return str(results[0]["cancellation"]["id"])


async def final(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        again = await messages_for(
            mailpit, data["redeliveredReference"], "Ihre Bestellung bei "
        )
        if len(again) != 1:
            raise ContractFailure(f"Re-run job sent {len(again)} confirmations")
        status = await connection.fetchval(
            "SELECT status FROM outbox_event WHERE idempotency_key = $1",
            f"order-confirmation-mail:{data['redelivered']}",
        )
        if status != "completed":
            raise ContractFailure(f"Re-run job did not complete: {status}")
        notices = await messages_for(
            mailpit, data["cancelledReference"], "Stornierung Ihrer Bestellung bei "
        )
        if len(notices) != 1:
            raise ContractFailure(f"{len(notices)} cancellation notices")
        notice = notices[0]
        text = str(notice.get("Text", ""))
        if recipients(notice) != {data["cancelledEmail"].casefold()}:
            raise ContractFailure("Cancellation notice recipient differs")
        for expected in (
            f"Bestellnummer: {data['cancelledReference']}",
            "storniert. Sie wird nicht geliefert.",
            "Bei Fragen zur Stornierung erreichen Sie uns unter",
            "/datenschutz",
        ):
            if expected not in text:
                raise ContractFailure(f"Cancellation notice lacks {expected!r}")
        for forbidden in (REASON, NOTE, "Bernd"):
            if forbidden in text:
                raise ContractFailure("Internal cancellation data reached the buyer")
    sent = await connection.fetchval(
        """
        SELECT count(*) FROM mail_delivery
        WHERE idempotency_key = $1 AND status = 'sent'
        """,
        f"order-cancellation-mail:{data['cancelled']}",
    )
    if sent != 1:
        raise ContractFailure(f"Cancellation ledger has {sent} rows")
    await limited_notice(connection, data)
    print(
        "public-order-mails: re-run job sent nothing; one cancellation notice "
        "without internal reason or note; injection refused; the notice over "
        "the per-address limit is dead-lettered and visible in operations"
    )


async def limited_notice(
    connection: asyncpg.Connection[Any], data: dict[str, Any]
) -> None:
    key = f"order-cancellation-mail:{data['limited']}"
    job = await connection.fetchrow(
        "SELECT id, status, attempts, last_error_code FROM outbox_event "
        "WHERE idempotency_key = $1",
        key,
    )
    if (
        job is None
        or job["status"] != "dead_letter"
        or job["attempts"] != 1
        or job["last_error_code"] != "order_mail_recipient_limit"
    ):
        raise ContractFailure(f"Limited notice not dead-lettered: {dict(job or {})}")
    if await connection.fetchval(
        "SELECT count(*) FROM mail_delivery WHERE idempotency_key = $1", key
    ):
        raise ContractFailure("The limited notice was sent")
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        if await messages_for(
            mailpit, data["limitedReference"], "Stornierung Ihrer Bestellung bei "
        ):
            raise ContractFailure("The limited notice reached Mailpit")
    token = await create_session(connection, SYSTEM_ID, now=datetime.now(timezone.utc))
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=60
    ) as api:
        response = await api.get(
            "/api/v1/admin/operations",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        )
    if response.status_code != 200:
        raise ContractFailure(f"Operations view failed: {response.status_code}")
    failed = {item["id"]: item for item in response.json().get("failedJobs", [])}
    shown = failed.get(str(job["id"]))
    if (
        shown is None
        or shown["eventType"] != CANCELLATION
        or shown["lastErrorCode"] != "order_mail_recipient_limit"
    ):
        raise ContractFailure("The limited notice is not visible in operations")
    # The synthetic ledger rows only stood for earlier mails. Without them
    # the operator's retry sends the notice (checked in ``recovered``).
    await connection.execute(
        "DELETE FROM mail_delivery WHERE idempotency_key = ANY($1::text[])",
        data["flood"],
    )
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        retried = await api.post(
            f"/api/v1/admin/operations/jobs/{job['id']}/retry",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        )
    if retried.status_code != 200:
        raise ContractFailure(f"Operator retry failed: {retried.status_code}")


async def recovered(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    key = f"order-cancellation-mail:{data['limited']}"
    status = await connection.fetchval(
        "SELECT status FROM outbox_event WHERE idempotency_key = $1", key
    )
    if status != "completed":
        raise ContractFailure(f"Retried notice did not complete: {status}")
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        notices = await messages_for(
            mailpit, data["limitedReference"], "Stornierung Ihrer Bestellung bei "
        )
    if len(notices) != 1:
        raise ContractFailure(f"Retried notice sent {len(notices)} mails")
    print("public-order-mails: the operator retry sent the limited notice once")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "step", choices=("snapshot", "confirmations", "final", "recovered")
    )
    parser.add_argument("state", type=Path)
    arguments = parser.parse_args()
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        step = {
            "snapshot": snapshot,
            "confirmations": confirmations,
            "final": final,
            "recovered": recovered,
        }[arguments.step]
        await step(connection, arguments.state)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
