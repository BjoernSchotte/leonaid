#!/usr/bin/env python3
"""Buyer mails of an order a member entered: real outbox, SMTP and Mailpit.

The sibling of ``order_mails.py`` for specs/mails-documents-donations-push
§6.2 and §6.4. Steps, with a real worker run (``run-until-idle``) between
them:

``record``     a manager switches the action's ``internalOrderMails`` on and
               records two orders in the web admin's name: one with a buyer
               address (one confirmation job, ids and links only) and one
               without (no job).
``confirmed``  the confirmation arrived once in Mailpit, with the order
               number and the sentence that a member recorded the order.
               The mail status says "sent". The manager sends it again
               (twice with one key).
``resent``     the confirmation arrived a second time, under the resend
               key. The manager cancels the order.
``final``      the cancellation notice arrived once, without the internal
               reason; the confirmation cannot be sent again. The switch
               gets its earlier value back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.domain.commitments import order_number
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from tools.identity.contract import KLARA_ID, create_session
from tools.public_orders.order_mails import (
    ACTION_ID,
    CANCELLATION,
    CONFIRMATION,
    NOTE,
    REASON,
    ContractFailure,
    legal_name,
    messages_for,
    recipients,
    require_env,
)

SETTINGS = f"/api/v1/actions/{ACTION_ID}/buyer-mail-configuration"
ORDERS = f"/api/v1/actions/{ACTION_ID}/commitments"
DRIVER_NOTE = "Hofeinfahrt links, Code 4711 (intern)"


class Manager:
    """The API as Klara, who manages the golden action."""

    def __init__(self, api: httpx.AsyncClient, token: str) -> None:
        self._api = api
        self._cookie = {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}

    async def get(self, path: str) -> Any:
        response = await self._api.get(path, headers=self._cookie)
        if response.status_code != 200:
            raise ContractFailure(f"GET {path}: {response.status_code}")
        return response.json()

    async def send(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None,
        *,
        key: str | None = None,
        expected: int,
    ) -> Any:
        headers = dict(self._cookie)
        if key is not None:
            headers["Idempotency-Key"] = key
        response = await self._api.request(method, path, headers=headers, json=body)
        if response.status_code != expected:
            raise ContractFailure(
                f"{method} {path}: {response.status_code} {response.text}"
            )
        return response.json()

    async def switch(self, internal_order_mails: bool) -> None:
        current = await self.get(SETTINGS)
        await self.send(
            "PUT",
            SETTINGS,
            {
                "expectedRevision": current["revision"],
                "internalOrderMails": internal_order_mails,
                "deliveryDayMail": current["deliveryDayMail"],
                "deliveryDaySendTime": current["deliveryDaySendTime"],
            },
            expected=200,
        )

    async def mails(self, order_id: str) -> dict[str, dict[str, Any]]:
        payload = await self.get(f"{ORDERS}/{order_id}/buyer-mails")
        return {str(item["kind"]): dict(item) for item in payload["mails"]}


async def manager(
    connection: asyncpg.Connection[Any], api: httpx.AsyncClient
) -> Manager:
    token = await create_session(connection, KLARA_ID, now=datetime.now(timezone.utc))
    return Manager(api, token)


async def order_body(
    connection: asyncpg.Connection[Any], *, name: str, email: str | None
) -> dict[str, object]:
    """An order of the web admin with what the golden action offers."""

    offering = await connection.fetchrow(
        """
        SELECT id, unit FROM offering
        WHERE action_id = $1 AND status = 'active'
          AND unit = ANY(allowed_quantity_units)
          AND (available_from IS NULL OR available_from <= now())
          AND (available_until IS NULL OR available_until > now())
        ORDER BY code LIMIT 1
        """,
        ACTION_ID,
    )
    company = await connection.fetchval(
        "SELECT twenty_company_id FROM commitment WHERE action_id = $1 "
        "AND twenty_company_id IS NOT NULL ORDER BY created_at LIMIT 1",
        ACTION_ID,
    )
    if offering is None or company is None:
        raise ContractFailure("The golden action has no offering or no buyer")
    address = {
        "recipientName": name,
        "streetLine1": "Marktplatz 3",
        "postalCode": "86150",
        "city": "Augsburg",
        "countryCode": "DE",
    }
    body: dict[str, object] = {
        "source": "admin",
        "readyForReview": True,
        "buyer": {
            "partyKind": "company",
            "twentyId": str(company),
            "displayName": name,
            "email": email,
        },
        "invoiceRecipient": {**address, "email": None},
        "lines": [
            {"offeringId": str(offering["id"]), "quantity": 2, "unit": offering["unit"]}
        ],
    }
    window = await connection.fetchval(
        """
        SELECT delivery_window.id
        FROM action_delivery_window AS delivery_window
        JOIN action_delivery_configuration AS configuration
          ON configuration.action_id = delivery_window.action_id
        WHERE delivery_window.action_id = $1 AND configuration.enabled
          AND NOT delivery_window.retired AND delivery_window.starts_at > now()
        ORDER BY delivery_window.starts_at LIMIT 1
        """,
        ACTION_ID,
    )
    if window is not None:
        # A review-ready order of an action with delivery needs both.
        body["deliveryRecipient"] = address
        body["deliveryWindowId"] = str(window)
        body["allowFullWindow"] = True
        body["deliveryContact"] = {
            "name": "Pforte Herr Geheim",
            "phone": "+49 821 999999",
            "driverNote": DRIVER_NOTE,
        }
    return body


async def jobs(
    connection: asyncpg.Connection[Any], order_id: str, event_type: str
) -> list[asyncpg.Record]:
    return list(
        await connection.fetch(
            "SELECT idempotency_key, status, payload FROM outbox_event "
            "WHERE aggregate_type = 'commitment' AND aggregate_id = $1 "
            "AND event_type = $2 ORDER BY idempotency_key",
            UUID(order_id),
            event_type,
        )
    )


async def record(connection: asyncpg.Connection[Any], state: Path) -> None:
    run = uuid4().hex[:10]
    email = f"intern.{run}@leonaid.invalid"
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        klara = await manager(connection, api)
        before = await klara.get(SETTINGS)
        await klara.switch(True)
        order = await klara.send(
            "POST",
            ORDERS,
            await order_body(connection, name=f"Intern {run} GmbH", email=email),
            key=f"internal-order-mail:{run}-with-address",
            expected=201,
        )
        silent = await klara.send(
            "POST",
            ORDERS,
            await order_body(connection, name=f"Intern {run} ohne Adresse", email=None),
            key=f"internal-order-mail:{run}-without-address",
            expected=201,
        )
        status = (await klara.mails(order["id"]))["confirmation"]
    if order["publicReference"] != order_number(UUID(order["id"])):
        raise ContractFailure(f"Order number differs: {order['publicReference']}")
    queued = await jobs(connection, order["id"], CONFIRMATION)
    if [job["idempotency_key"] for job in queued] != [
        f"order-confirmation-mail:{order['id']}"
    ]:
        raise ContractFailure(f"Internal order has no single job: {queued}")
    payload = json.loads(queued[0]["payload"])
    if set(payload) != {
        "actionId",
        "commitmentId",
        "campaignUrl",
        "privacyUrl",
        "imprintUrl",
    } or "@" in json.dumps(payload):
        raise ContractFailure(f"Job payload carries more than ids: {payload}")
    if status["state"] != "queued":
        raise ContractFailure(f"Mail status before the worker: {status}")
    if await jobs(connection, silent["id"], CONFIRMATION):
        raise ContractFailure("An order without a buyer address queued a mail")
    state.write_text(
        json.dumps(
            {
                "run": run,
                "email": email,
                "order": order["id"],
                "reference": order["publicReference"],
                "version": order["deliveryCompletionVersion"],
                "internalOrderMailsBefore": before["internalOrderMails"],
            }
        ),
        encoding="utf-8",
    )
    print("internal-order-mails: one confirmation job for the order with an address")


async def confirmed(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    club = await legal_name(connection)
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        found = await messages_for(mailpit, data["reference"], "Ihre Bestellung bei ")
    if len(found) != 1:
        raise ContractFailure(f"{len(found)} confirmations for {data['reference']}")
    mail = found[0]
    text = str(mail.get("Text", ""))
    if recipients(mail) != {data["email"].casefold()}:
        raise ContractFailure("Confirmation recipient differs")
    expected = (
        f"Bestellnummer: {data['reference']}",
        f"Ihre Bestellung wurde von einem Mitglied des {club} für Sie erfasst.",
        "Gesamtbetrag: ",
        "/datenschutz",
        "/impressum",
    )
    missing = [item for item in expected if item not in text]
    if missing:
        raise ContractFailure(f"Internal confirmation lacks {missing}")
    for forbidden in (DRIVER_NOTE, "Pforte", "999999"):
        if forbidden in text:
            raise ContractFailure("Delivery contact data reached the buyer")
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        klara = await manager(connection, api)
        status = (await klara.mails(data["order"]))["confirmation"]
        if status["state"] != "sent" or not status["canResend"]:
            raise ContractFailure(f"Mail status after the worker: {status}")
        resend = f"{ORDERS}/{data['order']}/buyer-mails/confirmation/resend"
        for _ in range(2):
            # The second call is the replay of a lost answer.
            await klara.send(
                "POST",
                resend,
                None,
                key=f"internal-order-mail:{data['run']}-resend",
                expected=202,
            )
        status = (await klara.mails(data["order"]))["confirmation"]
    keys = [
        job["idempotency_key"]
        for job in await jobs(connection, data["order"], CONFIRMATION)
    ]
    base = f"order-confirmation-mail:{data['order']}"
    if keys != [base, f"{base}:resend:1"] or status["state"] != "queued":
        raise ContractFailure(f"Resend jobs differ: {keys} {status}")
    print(
        "internal-order-mails: confirmation sent once with the member sentence; "
        "one resend queued"
    )


async def resent(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        found = await messages_for(mailpit, data["reference"], "Ihre Bestellung bei ")
    if len(found) != 2 or any(
        recipients(mail) != {data["email"].casefold()} for mail in found
    ):
        raise ContractFailure(f"{len(found)} confirmations after the resend")
    if str(found[0].get("Text", "")) != str(found[1].get("Text", "")):
        raise ContractFailure("The resent confirmation differs from the first")
    base = f"order-confirmation-mail:{data['order']}"
    ledger = await connection.fetch(
        "SELECT idempotency_key FROM mail_delivery WHERE status = 'sent' "
        "AND idempotency_key = ANY($1::text[]) ORDER BY idempotency_key",
        [base, f"{base}:resend:1"],
    )
    if len(ledger) != 2:
        raise ContractFailure(f"Ledger rows after the resend: {len(ledger)}")
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        klara = await manager(connection, api)
        status = (await klara.mails(data["order"]))["confirmation"]
        if status["state"] != "sent" or not status["canResend"]:
            raise ContractFailure(f"Mail status after the resend: {status}")
        await klara.send(
            "POST",
            f"{ORDERS}/{data['order']}/cancellation",
            {"expectedVersion": data["version"], "reason": REASON, "note": NOTE},
            key=f"internal-order-mail:{data['run']}-cancel",
            expected=201,
        )
    if len(await jobs(connection, data["order"], CANCELLATION)) != 1:
        raise ContractFailure("The cancellation queued no single notice")
    print("internal-order-mails: the resend arrived once; cancellation queued")


async def final(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        confirmations = await messages_for(
            mailpit, data["reference"], "Ihre Bestellung bei "
        )
        notices = await messages_for(
            mailpit, data["reference"], "Stornierung Ihrer Bestellung bei "
        )
    if len(confirmations) != 2:
        raise ContractFailure(
            f"{len(confirmations)} confirmations after the cancellation"
        )
    if len(notices) != 1:
        raise ContractFailure(f"{len(notices)} cancellation notices")
    text = str(notices[0].get("Text", ""))
    if recipients(notices[0]) != {data["email"].casefold()}:
        raise ContractFailure("Cancellation notice recipient differs")
    if f"Bestellnummer: {data['reference']}" not in text:
        raise ContractFailure("Cancellation notice lacks the order number")
    for forbidden in (REASON, NOTE, DRIVER_NOTE):
        if forbidden in text:
            raise ContractFailure("Internal data reached the buyer")
    statuses = {
        str(row["idempotency_key"]): str(row["status"])
        for row in (
            *await jobs(connection, data["order"], CONFIRMATION),
            *await jobs(connection, data["order"], CANCELLATION),
        )
    }
    if set(statuses.values()) != {"completed"}:
        raise ContractFailure(f"Not every job completed: {statuses}")
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        klara = await manager(connection, api)
        mails = await klara.mails(data["order"])
        if (
            mails["confirmation"]["state"] != "sent"
            or mails["confirmation"]["canResend"]
            or mails["cancellation"]["state"] != "sent"
            or not mails["cancellation"]["canResend"]
        ):
            raise ContractFailure(f"Mail status at the end: {mails}")
        # Shared stacks keep the action: give the switch its value back.
        await klara.switch(bool(data["internalOrderMailsBefore"]))
    print(
        "internal-order-mails: one cancellation notice without internal data; "
        "the confirmation of the cancelled order cannot be sent again; "
        "switch restored"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("record", "confirmed", "resent", "final"))
    parser.add_argument("state", type=Path)
    arguments = parser.parse_args()
    steps: dict[str, Callable[[asyncpg.Connection[Any], Path], Awaitable[None]]] = {
        "record": record,
        "confirmed": confirmed,
        "resent": resent,
        "final": final,
    }
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await steps[arguments.step](connection, arguments.state)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
