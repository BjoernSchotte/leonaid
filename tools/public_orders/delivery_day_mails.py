#!/usr/bin/env python3
"""The mail on the delivery day: real sweep, outbox, SMTP and Mailpit.

The sibling of ``order_mails.py`` and ``internal_order_mails.py`` for
specs/mails-documents-donations-push §6.3. The suite runs the worker's own
sweep (``outbox delivery-day-mail-sweep``) and the worker
(``run-until-idle``) between the steps:

``prepare``  an action of its own with delivery, whose zone is chosen so
             that it is early afternoon there now, and a window that starts
             in ten minutes: the delivery is "today" and the send time has
             passed, whatever the wall clock says. A manager switches the
             delivery-day mail on and records one order with a buyer address
             and one without.
``queued``   after the sweep: exactly one job, for the order with an
             address, keyed by order and window, with ids and links only.
``sent``     after the worker: one mail in Mailpit that names the window,
             the delivery address and the quantities, and nothing about the
             driver. The status says "sent". The manager sends it again.
``final``    after another sweep and worker run: the sweep queued nothing
             new, the resend arrived once. The order is ticked off as
             delivered; the mail cannot be sent again. The switch goes off.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from tools.identity.contract import KLARA_ID
from tools.public_orders.internal_order_mails import DRIVER_NOTE, Manager, manager
from tools.public_orders.order_mails import (
    ContractFailure,
    legal_name,
    mailpit_messages,
    recipients,
    require_env,
)

DELIVERY_DAY = "order.delivery_day.mail.v1"
SUBJECT = "Ihre Lieferung kommt heute zwischen "


def afternoon_zone(now: datetime) -> str:
    """A fixed-offset zone where it is about 14:00 now.

    ``Etc/GMT-5`` is UTC+5: the sign of these names is reversed.
    """

    offset = 14 - now.astimezone(timezone.utc).hour
    if offset > 14:
        offset -= 24
    if offset == 0:
        return "Etc/GMT"
    return f"Etc/GMT{'-' if offset > 0 else '+'}{abs(offset)}"


async def messages_to(
    mailpit: httpx.AsyncClient, address: str, subject_prefix: str
) -> list[dict[str, Any]]:
    found = []
    for summary in await mailpit_messages(mailpit):
        if address.casefold() in recipients(summary) and str(
            summary.get("Subject", "")
        ).startswith(subject_prefix):
            detail = await mailpit.get(f"/api/v1/message/{summary['ID']}")
            detail.raise_for_status()
            found.append({**summary, **detail.json()})
    return found


async def day_status(klara: Manager, action_id: str, order_id: str) -> dict[str, Any]:
    """The delivery-day row of the order's mail status."""

    payload = await klara.get(
        f"/api/v1/actions/{action_id}/commitments/{order_id}/buyer-mails"
    )
    rows = {str(item["kind"]): dict(item) for item in payload["mails"]}
    if "delivery_day" not in rows:
        raise ContractFailure(f"No delivery-day mail in the status: {rows}")
    return rows["delivery_day"]


async def day_jobs(
    connection: asyncpg.Connection[Any], action_id: str
) -> list[asyncpg.Record]:
    return list(
        await connection.fetch(
            "SELECT idempotency_key, status, payload FROM outbox_event "
            "WHERE event_type = $1 AND aggregate_id IN "
            "(SELECT id FROM commitment WHERE action_id = $2) "
            "ORDER BY idempotency_key",
            DELIVERY_DAY,
            UUID(action_id),
        )
    )


async def prepare(connection: asyncpg.Connection[Any], state: Path) -> None:
    run = uuid4().hex[:10]
    action_id, offering_id, window_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    zone_name = afternoon_zone(now)
    zone = ZoneInfo(zone_name)
    # Windows are stored in whole minutes.
    starts_at = (now + timedelta(minutes=10)).replace(second=0, microsecond=0)
    ends_at = starts_at + timedelta(hours=2)
    if starts_at.astimezone(zone).date() != now.astimezone(zone).date():
        raise ContractFailure(f"The window is not today in {zone_name}")
    await connection.execute(
        """
        INSERT INTO charity_action (
            id, carrier_name, name, purpose, status, starts_on, ends_on,
            archive_slug
        )
        VALUES ($1, 'Liefertag-Proof', $2, 'Proof', 'active',
                '2026-01-01', '2099-12-31', $3)
        """,
        action_id,
        f"Liefertag-Proof {run}",
        f"delivery-day-proof-{action_id}",
    )
    for capability in ("offerings", "ordering", "delivery"):
        await connection.execute(
            "INSERT INTO charity_action_capability (action_id, capability) "
            "VALUES ($1, $2)",
            action_id,
            capability,
        )
    await connection.execute(
        "INSERT INTO action_membership (id, action_id, user_id, role) "
        "VALUES ($1, $2, $3, 'charity_admin')",
        uuid4(),
        action_id,
        KLARA_ID,
    )
    await connection.execute(
        "INSERT INTO action_delivery_configuration (action_id, enabled, timezone) "
        "VALUES ($1, true, $2)",
        action_id,
        zone_name,
    )
    await connection.execute(
        "INSERT INTO action_delivery_window (id, action_id, starts_at, ends_at) "
        "VALUES ($1, $2, $3, $4)",
        window_id,
        action_id,
        starts_at,
        ends_at,
    )
    await connection.execute(
        """
        INSERT INTO offering (
            id, action_id, code, name, status, unit, allowed_quantity_units,
            pieces_per_unit, unit_price_minor, currency
        )
        VALUES ($1, $2, $3, 'Krapfenbox', 'active', 'box',
                ARRAY['box']::text[], 24, 3600, 'EUR')
        """,
        offering_id,
        action_id,
        f"box-{offering_id.hex[:12]}",
    )
    email = f"liefertag.{run}@leonaid.invalid"
    orders = f"/api/v1/actions/{action_id}/commitments"
    settings = f"/api/v1/actions/{action_id}/buyer-mail-configuration"

    def order(name: str, address: str | None) -> dict[str, object]:
        recipient = {
            "recipientName": name,
            "streetLine1": "Marktplatz 3",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
        }
        return {
            "source": "admin",
            "readyForReview": True,
            "buyer": {
                "partyKind": "company",
                "twentyId": str(uuid4()),
                "displayName": name,
                "email": address,
            },
            "invoiceRecipient": {**recipient, "email": None},
            "deliveryRecipient": recipient,
            "deliveryWindowId": str(window_id),
            "deliveryContact": {
                "name": "Pforte Herr Geheim",
                "phone": "+49 821 999999",
                "driverNote": DRIVER_NOTE,
            },
            "lines": [{"offeringId": str(offering_id), "quantity": 2, "unit": "box"}],
        }

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        klara = await manager(connection, api)
        current = await klara.get(settings)
        await klara.send(
            "PUT",
            settings,
            {
                "expectedRevision": current["revision"],
                "internalOrderMails": False,
                "deliveryDayMail": True,
                "deliveryDaySendTime": "05:00",
            },
            expected=200,
        )
        with_address = await klara.send(
            "POST",
            orders,
            order(f"Liefertag {run} GmbH", email),
            key=f"delivery-day-mail:{run}-with-address",
            expected=201,
        )
        without = await klara.send(
            "POST",
            orders,
            order(f"Liefertag {run} ohne Adresse", None),
            key=f"delivery-day-mail:{run}-without-address",
            expected=201,
        )
        announced = await day_status(klara, str(action_id), with_address["id"])
    if announced["state"] != "not_due" or announced["reason"] != "scheduled":
        raise ContractFailure(f"Status before the sweep: {announced}")
    if await day_jobs(connection, str(action_id)):
        raise ContractFailure("A delivery-day job exists before the sweep")
    local_start = starts_at.astimezone(zone)
    local_end = ends_at.astimezone(zone)
    state.write_text(
        json.dumps(
            {
                "run": run,
                "action": str(action_id),
                "window": str(window_id),
                "email": email,
                "order": with_address["id"],
                "reference": with_address["publicReference"],
                "silent": without["id"],
                "subject": f"{SUBJECT}{local_start:%H:%M} und {local_end:%H:%M} Uhr",
                "day": f"{local_start:%d.%m.%Y}",
            }
        ),
        encoding="utf-8",
    )
    print(
        f"delivery-day-mails: action in {zone_name} with a window today and "
        "two orders; nothing queued before the sweep"
    )


async def queued(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    jobs = await day_jobs(connection, data["action"])
    key = f"order-delivery-day-mail:{data['order']}:{data['window']}"
    if [job["idempotency_key"] for job in jobs] != [key]:
        raise ContractFailure(f"The sweep queued other jobs: {jobs}")
    payload = json.loads(jobs[0]["payload"])
    if (
        set(payload)
        != {
            "actionId",
            "commitmentId",
            "windowId",
            "campaignUrl",
            "privacyUrl",
            "imprintUrl",
        }
        or payload["campaignUrl"] is not None
        or not str(payload["privacyUrl"]).endswith("/datenschutz")
        or not str(payload["imprintUrl"]).endswith("/impressum")
        or "@" in json.dumps(payload)
    ):
        raise ContractFailure(f"Job payload carries more than ids: {payload}")
    print("delivery-day-mails: the sweep queued one job, for the order with an address")


def check_mail(mail: dict[str, Any], data: dict[str, Any], club: str) -> None:
    text = str(mail.get("Text", ""))
    if recipients(mail) != {data["email"].casefold()}:
        raise ContractFailure("Delivery-day mail recipient differs")
    if str(mail.get("Subject", "")) != data["subject"]:
        raise ContractFailure(f"Subject differs: {mail.get('Subject')}")
    expected = (
        f"Ihre Bestellung {data['reference']} bei der Aktion "
        f"„Liefertag-Proof {data['run']}“ wird heute, ",
        f"{data['day']}, zwischen ",
        "Lieferadresse:",
        "Marktplatz 3",
        "Bestellt:",
        "- Krapfenbox: 2 Boxen (48 Stück)",
        club,
        "/datenschutz",
        "/impressum",
    )
    missing = [item for item in expected if item not in text]
    if missing:
        raise ContractFailure(f"Delivery-day mail lacks {missing}")
    for forbidden in (DRIVER_NOTE, "Pforte", "999999", "€", "Fahrer"):
        if forbidden in text:
            raise ContractFailure("Tour or price data reached the buyer")


async def with_manager(
    connection: asyncpg.Connection[Any],
    run: Callable[[Manager], Awaitable[None]],
) -> None:
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"), timeout=30
    ) as api:
        await run(await manager(connection, api))


async def sent(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    club = await legal_name(connection)
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        found = await messages_to(mailpit, data["email"], SUBJECT)
    if len(found) != 1:
        raise ContractFailure(f"{len(found)} delivery-day mails")
    check_mail(found[0], data, club)
    orders = f"/api/v1/actions/{data['action']}/commitments"

    async def status_and_resend(klara: Manager) -> None:
        status = await day_status(klara, data["action"], data["order"])
        if status["state"] != "sent" or not status["canResend"]:
            raise ContractFailure(f"Status after the worker: {status}")
        silent = await day_status(klara, data["action"], data["silent"])
        if silent["state"] != "not_due" or silent["reason"] != "no_email":
            raise ContractFailure(f"Status without an address: {silent}")
        for _ in range(2):
            # The second call is the replay of a lost answer.
            await klara.send(
                "POST",
                f"{orders}/{data['order']}/buyer-mails/delivery_day/resend",
                None,
                key=f"delivery-day-mail:{data['run']}-resend",
                expected=202,
            )

    await with_manager(connection, status_and_resend)
    print("delivery-day-mails: one mail with window, address and quantities; resent")


async def final(connection: asyncpg.Connection[Any], state: Path) -> None:
    data = json.loads(state.read_text(encoding="utf-8"))
    club = await legal_name(connection)
    base = f"order-delivery-day-mail:{data['order']}:{data['window']}"
    jobs = {
        str(job["idempotency_key"]): str(job["status"])
        for job in await day_jobs(connection, data["action"])
    }
    # The second sweep queued nothing: one first job and the resend.
    if jobs != {base: "completed", f"{base}:resend:1": "completed"}:
        raise ContractFailure(f"Jobs at the end: {jobs}")
    async with httpx.AsyncClient(
        base_url=require_env("MAIL_TEST_API_URL").rstrip("/"), timeout=15
    ) as mailpit:
        found = await messages_to(mailpit, data["email"], SUBJECT)
    if len(found) != 2:
        raise ContractFailure(f"{len(found)} delivery-day mails after the resend")
    for mail in found:
        check_mail(mail, data, club)
    # The driver ticks the order off: the mail is not sent again.
    await connection.execute(
        "INSERT INTO commitment_delivery (commitment_id, action_id, state, "
        "state_changed_at, state_changed_by_user_id) "
        "VALUES ($1, $2, 'delivered', CURRENT_TIMESTAMP, $3)",
        UUID(data["order"]),
        UUID(data["action"]),
        KLARA_ID,
    )
    orders = f"/api/v1/actions/{data['action']}/commitments"
    settings = f"/api/v1/actions/{data['action']}/buyer-mail-configuration"

    async def delivered(klara: Manager) -> None:
        status = await day_status(klara, data["action"], data["order"])
        if status["state"] != "sent" or status["canResend"]:
            raise ContractFailure(f"Status of the delivered order: {status}")
        await klara.send(
            "POST",
            f"{orders}/{data['order']}/buyer-mails/delivery_day/resend",
            None,
            key=f"delivery-day-mail:{data['run']}-delivered",
            expected=409,
        )
        current = await klara.get(settings)
        # Shared stacks keep the action: it sends nothing from now on.
        await klara.send(
            "PUT",
            settings,
            {
                "expectedRevision": current["revision"],
                "internalOrderMails": False,
                "deliveryDayMail": False,
                "deliveryDaySendTime": current["deliveryDaySendTime"],
            },
            expected=200,
        )

    await with_manager(connection, delivered)
    print(
        "delivery-day-mails: the second sweep queued nothing; the resend "
        "arrived once; a delivered order gets no further mail; switched off"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("prepare", "queued", "sent", "final"))
    parser.add_argument("state", type=Path)
    arguments = parser.parse_args()
    steps: dict[str, Callable[[asyncpg.Connection[Any], Path], Awaitable[None]]] = {
        "prepare": prepare,
        "queued": queued,
        "sent": sent,
        "final": final,
    }
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await steps[arguments.step](connection, arguments.state)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
