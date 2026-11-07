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
``final``         the re-run job sent nothing new; the cancellation notice
                  arrived exactly once, without the internal reason.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.application.delivery_completion import delivery_completion_version
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from tools.identity.contract import KLARA_ID, create_session

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
                if "Lieferfenster: " not in text:
                    raise ContractFailure(f"Window missing in {reference}")
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
        cancellation = await cancel_twice(connection, cancelled["id"])
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
        }
    )
    state.write_text(json.dumps(data), encoding="utf-8")
    print(
        f"public-order-mails: {len(orders)} confirmations sent once each "
        f"({windows} with a delivery window)"
    )


async def cancel_twice(connection: asyncpg.Connection[Any], order_id: UUID) -> str:
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
        for _ in range(2):
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
    if results[0]["cancellation"]["id"] != results[1]["cancellation"]["id"]:
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
    print(
        "public-order-mails: re-run job sent nothing; one cancellation notice "
        "without internal reason or note"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("snapshot", "confirmations", "final"))
    parser.add_argument("state", type=Path)
    arguments = parser.parse_args()
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        step = {
            "snapshot": snapshot,
            "confirmations": confirmations,
            "final": final,
        }[arguments.step]
        await step(connection, arguments.state)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
