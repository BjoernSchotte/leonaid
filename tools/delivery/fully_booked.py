"""Proof of the manual "ausgebucht" switch per delivery window (task 6.5).

Real PostgreSQL repositories behind the real FastAPI routes; synthetic identity.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import (
    AsyncpgDeliveryRepository,
    guard_window_booking,
)
from leonaid.adapters.postgres.delivery_completion import (
    AsyncpgDeliveryCompletionRepository,
)
from leonaid.adapters.postgres.public_orders import AsyncpgPublicOrderRepository
from leonaid.application.commitments import CommitmentDraft, CommitmentService
from leonaid.application.delivery import DeliveryService, require_publicly_bookable
from leonaid.application.delivery_completion import DeliveryCompletionService
from leonaid.application.errors import Conflict
from leonaid.application.public_orders import (
    PublicOrderCrmOutcome,
    PublicOrderDraft,
    PublicOrderPartyDraft,
    ResolvedPublicParty,
)
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
)
from leonaid.domain.delivery import DeliveryWindow
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)
from tools.delivery.http_configuration import http_app

EMAIL = "fully-booked@example.invalid"


async def _audit(pool: asyncpg.Pool, window_id: UUID) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """SELECT payload FROM audit_event
        WHERE entity_type = 'delivery_window' AND entity_id = $1
          AND event_type = 'delivery_window_fully_booked_changed'
        ORDER BY occurred_at, id""",
        window_id,
    )
    return [json.loads(row["payload"]) for row in rows]


async def _event(pool: asyncpg.Pool, commitment_id: UUID, event: str) -> Any:
    payload = await pool.fetchval(
        "SELECT payload FROM audit_event WHERE entity_id = $1 AND event_type = $2",
        commitment_id,
        event,
    )
    return json.loads(payload)


async def _queued_behind(
    pool: asyncpg.Pool,
    holder: asyncpg.Connection,
    task: asyncio.Task[Any],
    what: str,
) -> None:
    """Return once a backend is blocked by the holder's lock; fail otherwise.

    A fixed sleep would also pass for a command that is only slow.
    """

    holder_pid = await holder.fetchval("SELECT pg_backend_pid()")
    deadline = asyncio.get_running_loop().time() + 10
    async with pool.acquire() as observer:
        while True:
            assert not task.done(), f"{what} did not wait for the lock"
            if await observer.fetchval(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE $1::integer = ANY(pg_blocking_pids(pid))",
                holder_pid,
            ):
                return
            assert asyncio.get_running_loop().time() < deadline, (
                f"{what} never queued behind the lock"
            )
            await asyncio.sleep(0.02)


async def prove_fully_booked(
    pool: asyncpg.Pool,
    *,
    action_id: UUID,
    admin_id: UUID,
    draft: CommitmentDraft,
    alias: str,
) -> None:
    now = datetime.now(timezone.utc)

    def actor(role: ActionRole) -> IdentityPrincipal:
        return IdentityPrincipal(
            UserAccount(
                admin_id, "admin@example.invalid", "Test", AccountStatus.ACTIVE
            ),
            frozenset(),
            (ActionMembership(uuid4(), action_id, "Test", admin_id, role, now),),
        )

    admin = actor(ActionRole.CHARITY_ADMIN)
    app, identity = http_app(admin)
    schedules = AsyncpgDeliveryRepository(pool)
    commitments = AsyncpgCommitmentRepository(pool)
    app.state.delivery_service = DeliveryService(schedules)
    app.state.commitment_service = CommitmentService(commitments)
    app.state.delivery_completion_service = DeliveryCompletionService(
        AsyncpgDeliveryCompletionRepository(pool)
    )
    configuration = await schedules.get(action_id)
    full, other = (
        DeliveryWindow(
            uuid4(), action_id, date(2037, 12, 22), time(hour), time(hour + 2)
        )
        for hour in (8, 10)
    )
    configuration = await schedules.save(
        replace(configuration, windows=(*configuration.windows, full, other))
    )
    assert not any(window.fully_booked for window in configuration.windows)

    # A separate customer keeps the privacy lookup proof exact.
    assert draft.invoice_recipient is not None
    draft = replace(
        draft,
        buyer=replace(draft.buyer, email=EMAIL),
        invoice_recipient=replace(draft.invoice_recipient, email=EMAIL),
    )
    public = AsyncpgPublicOrderRepository(pool)
    buyer = BuyerSnapshot(CommitmentPartyKind.PERSON, uuid4(), "Full", EMAIL)
    party = ResolvedPublicParty(
        buyer=buyer, contact_twenty_id=None, outcome=PublicOrderCrmOutcome.REUSED
    )

    def public_draft(window_id: UUID) -> PublicOrderDraft:
        assert draft.delivery_recipient is not None
        assert draft.invoice_recipient is not None
        return PublicOrderDraft(
            PublicOrderPartyDraft(None, "Full", "Customer", EMAIL),
            draft.delivery_recipient,
            draft.invoice_recipient,
            draft.lines,
            None,
            True,
            True,
            "test-v1",
            delivery_window_id=window_id,
            delivery_contact=draft.delivery_contact,
        )

    async def public_order(value: PublicOrderDraft, key: str) -> Any:
        request_hash = value.request_hash(action_id=action_id, public_alias=alias)
        async with public.order_command(
            lock_key=f"fully-booked:{buyer.twenty_id}",
            idempotency_key=key,
            request_hash=request_hash,
        ) as command:
            if command.existing_result is not None:
                return command.existing_result
            outcome = await command.record_order(
                action_id=action_id,
                public_alias=alias,
                party=party,
                draft=value,
                idempotency_key=key,
                request_hash=request_hash,
                request_id="fully-booked-proof",
                occurred_at=now,
            )
            await command.complete(outcome)
            return outcome

    async def order_count() -> int:
        return int(
            await pool.fetchval(
                "SELECT count(*) FROM commitment WHERE delivery_window_id = $1",
                full.id,
            )
        )

    # A public order booked before the switch; its replay must survive it.
    early_key = f"fully-booked:{uuid4()}"
    early = await public_order(public_draft(full.id), early_key)
    assert not early.replayed

    base = f"/api/v1/actions/{action_id}"
    switch = f"{base}/delivery-windows/{full.id}/fully-booked"
    configuration_path = f"{base}/delivery-configuration"

    def headers() -> dict[str, str]:
        return {"Idempotency-Key": f"fully-booked:{uuid4()}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Switching: managers only, audited, repeating it changes nothing.
        identity.current = actor(ActionRole.ACQUIRER)
        response = await client.put(switch, json={"fullyBooked": True})
        assert response.status_code == 403, response.text
        identity.current = admin
        assert (
            await client.put(switch, json={"fullyBooked": True, "extra": 1})
        ).status_code == 422
        assert (
            await client.put(
                f"{base}/delivery-windows/{uuid4()}/fully-booked",
                json={"fullyBooked": True},
            )
        ).status_code == 404
        revision = (await schedules.get(action_id)).revision
        for _ in range(2):
            response = await client.put(switch, json={"fullyBooked": True})
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            body = response.json()
            assert body["revision"] == revision
            assert next(w for w in body["windows"] if w["id"] == str(full.id))[
                "fullyBooked"
            ]
        assert await _audit(pool, full.id) == [
            {"fullyBooked": True, "previousFullyBooked": False}
        ]

        # A stale form save keeps the switch: the form never writes it,
        # even when it echoes the windows with a different fullyBooked.
        current = (await client.get(configuration_path)).json()
        form = {
            "expectedRevision": current["revision"],
            "enabled": current["enabled"],
            "timezone": current["timezone"],
            "windows": [
                {**window, "fullyBooked": False} for window in current["windows"]
            ],
        }
        response = await client.put(configuration_path, json=form)
        assert response.status_code == 200, response.text
        assert next(w for w in response.json()["windows"] if w["id"] == str(full.id))[
            "fullyBooked"
        ]

        # A new window cannot start full: refused, not silently dropped.
        current = (await client.get(configuration_path)).json()
        response = await client.put(
            configuration_path,
            json={
                "expectedRevision": current["revision"],
                "enabled": current["enabled"],
                "timezone": current["timezone"],
                "windows": [
                    *current["windows"],
                    {
                        "deliveryOn": "2037-12-23",
                        "startsAt": "08:00",
                        "endsAt": "10:00",
                        "fullyBooked": True,
                    },
                ],
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "delivery_window_full_new"

        # Public: refused early and under lock; nothing is written; the
        # earlier order's replay still returns its result.
        configuration = await schedules.get(action_id)
        try:
            require_publicly_bookable(configuration, full.id)
        except Conflict as error:
            assert error.code == "delivery_window_full"
        else:
            raise AssertionError("Public pre-check accepted a full window")
        require_publicly_bookable(configuration, other.id)
        before = await order_count()
        try:
            await public_order(public_draft(full.id), f"fully-booked:{uuid4()}")
        except Conflict as error:
            assert error.code == "delivery_window_full"
        else:
            raise AssertionError("Public order booked a full window")
        assert await order_count() == before
        replayed = await public_order(public_draft(full.id), early_key)
        assert replayed.replayed
        assert replayed.commitment.id == early.commitment.id
        open_order = await public_order(
            public_draft(other.id), f"fully-booked:{uuid4()}"
        )
        assert not open_order.replayed

        # Admin capture: 409 without confirmation, then booked with it; the
        # confirmed resend reuses the refused attempt's key.
        offering_id = draft.lines[0].offering_id
        capture: dict[str, Any] = {
            "source": "admin",
            "readyForReview": True,
            "buyer": {
                "partyKind": "person",
                "twentyId": str(uuid4()),
                "displayName": "Full buyer",
                "email": EMAIL,
            },
            "invoiceRecipient": {
                "recipientName": "Billing",
                "streetLine1": "Invoice 1",
                "postalCode": "12345",
                "city": "Test",
                "email": EMAIL,
            },
            "deliveryRecipient": {
                "recipientName": "Warehouse",
                "streetLine1": "Delivery 2",
                "postalCode": "12345",
                "city": "Test",
            },
            "deliveryWindowId": str(full.id),
            "lines": [{"offeringId": str(offering_id), "quantity": 1, "unit": "box"}],
        }
        create_path = f"{base}/commitments"
        key = headers()
        response = await client.post(create_path, json=capture, headers=key)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_window_full"
        response = await client.post(
            create_path, json={**capture, "allowFullWindow": True}, headers=key
        )
        assert response.status_code == 201, response.text
        created = UUID(response.json()["id"])
        assert (await _event(pool, created, "commitment_created"))[
            "fullWindowBooked"
        ] is True
        # The confirmation is not order content: the plain replay matches.
        replay = await client.post(create_path, json=capture, headers=key)
        assert replay.status_code == 201 and replay.json()["replayed"], replay.text
        response = await client.post(
            create_path,
            json={**capture, "deliveryWindowId": str(other.id)},
            headers=headers(),
        )
        assert response.status_code == 201, response.text
        assert "fullWindowBooked" not in await _event(
            pool, UUID(response.json()["id"]), "commitment_created"
        )

        # A draft books nothing; its completion applies the switch.
        response = await client.post(
            create_path, json={**capture, "readyForReview": False}, headers=headers()
        )
        assert response.status_code == 201, response.text
        draft_id = response.json()["id"]
        complete_path = f"{create_path}/{draft_id}/complete"
        completion = {
            "deliveryRecipient": capture["deliveryRecipient"],
            "deliveryWindowId": str(full.id),
        }
        key = headers()
        response = await client.post(complete_path, json=completion, headers=key)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_window_full"
        response = await client.post(
            complete_path, json={**completion, "allowFullWindow": True}, headers=key
        )
        assert response.status_code == 200, response.text
        assert await _event(pool, UUID(draft_id), "commitment_completed") == {
            "previousStatus": "draft",
            "status": "review_ready",
            "fullWindowBooked": True,
        }

        # Manager completion of a draft that already carries the full
        # window: the draft books it only now, so it asks as well.
        response = await client.post(
            create_path, json={**capture, "readyForReview": False}, headers=headers()
        )
        assert response.status_code == 201, response.text
        carried = response.json()
        carried_path = f"{create_path}/{carried['id']}"
        carried_body = {
            "expectedVersion": carried["deliveryCompletionVersion"],
            "invoiceRecipient": {**capture["invoiceRecipient"], "countryCode": "DE"},
            "deliveryRecipient": capture["deliveryRecipient"],
            "deliveryWindowId": str(full.id),
        }
        key = headers()
        response = await client.post(
            f"{carried_path}/delivery-completion", json=carried_body, headers=key
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_window_full"
        response = await client.post(
            f"{carried_path}/delivery-completion",
            json={**carried_body, "allowFullWindow": True},
            headers=key,
        )
        assert response.status_code == 200, response.text
        assert await _event(
            pool, UUID(carried["id"]), "commitment_delivery_completed"
        ) == {
            "previousStatus": "draft",
            "status": "review_ready",
            "historical": False,
            "fullWindowBooked": True,
        }

        # Manager completion of an order without a window.
        legacy = await commitments.create(
            action_id=action_id,
            actor_user_id=admin_id,
            source=CommitmentSource.ADMIN,
            status=CommitmentStatus.DRAFT,
            draft=replace(
                draft,
                invoice_recipient=None,
                delivery_recipient=None,
                delivery_window_id=None,
                delivery_contact=None,
            ),
            idempotency_key=f"fully-booked:{uuid4()}",
            request_hash=uuid4().hex * 2,
            request_id="fully-booked-proof",
            occurred_at=now,
        )
        await pool.execute(
            "UPDATE commitment SET status = 'review_ready' WHERE id = $1", legacy.id
        )
        order_path = f"{create_path}/{legacy.id}"
        version = (await client.get(order_path)).json()["deliveryCompletionVersion"]
        manager = {
            "expectedVersion": version,
            "invoiceRecipient": {**capture["invoiceRecipient"], "countryCode": "DE"},
            "deliveryRecipient": capture["deliveryRecipient"],
            "deliveryWindowId": str(full.id),
        }
        key = headers()
        response = await client.post(
            f"{order_path}/delivery-completion", json=manager, headers=key
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_window_full"
        response = await client.post(
            f"{order_path}/delivery-completion",
            json={**manager, "allowFullWindow": True},
            headers=key,
        )
        assert response.status_code == 200, response.text
        assert await _event(pool, legacy.id, "commitment_delivery_completed") == {
            "previousStatus": "review_ready",
            "status": "review_ready",
            "historical": False,
            "fullWindowBooked": True,
        }

        # Switching off is audited and opens the window for the public again.
        response = await client.put(switch, json={"fullyBooked": False})
        assert response.status_code == 200, response.text
        assert (await _audit(pool, full.id))[-1] == {
            "fullyBooked": False,
            "previousFullyBooked": True,
        }
        await public_order(public_draft(full.id), f"fully-booked:{uuid4()}")

        # Retiring clears the switch, audited; a retired window stays closed.
        assert (await client.put(switch, json={"fullyBooked": True})).status_code == 200
        current = (await client.get(configuration_path)).json()
        form = {
            "expectedRevision": current["revision"],
            "enabled": current["enabled"],
            "timezone": current["timezone"],
            "windows": [
                {
                    **{k: v for k, v in window.items() if k != "fullyBooked"},
                    "retired": window["retired"] or window["id"] == str(full.id),
                }
                for window in current["windows"]
            ],
        }
        response = await client.put(configuration_path, json=form)
        assert response.status_code == 200, response.text
        stored = next(w for w in response.json()["windows"] if w["id"] == str(full.id))
        assert stored["retired"] and not stored["fullyBooked"]
        assert (await _audit(pool, full.id))[-1] == {
            "fullyBooked": False,
            "previousFullyBooked": True,
            "reason": "retired",
        }
        response = await client.put(switch, json={"fullyBooked": True})
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_window_retired"
        try:
            await pool.execute(
                "UPDATE action_delivery_window SET fully_booked = true WHERE id = $1",
                full.id,
            )
        except asyncpg.CheckViolationError:
            pass
        else:
            raise AssertionError("Database accepted a retired, full window")

        # A window that has begun can no longer be switched.
        past = uuid4()
        await pool.execute(
            """INSERT INTO action_delivery_window(id, action_id, starts_at, ends_at)
            VALUES ($1, $2, '2020-01-01 08:00+00', '2020-01-01 09:00+00')""",
            past,
            action_id,
        )
        response = await client.put(
            f"{base}/delivery-windows/{past}/fully-booked", json={"fullyBooked": True}
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_window_past"
        await pool.execute(
            "UPDATE action_delivery_window SET retired = true WHERE id = $1", past
        )

    # The real public order path: the switch commits after the order command
    # started (after its early check) and before the order is recorded. The
    # guard in the same transaction refuses it; nothing is written.
    async def other_count() -> int:
        return int(
            await pool.fetchval(
                "SELECT count(*) FROM commitment WHERE delivery_window_id = $1",
                other.id,
            )
        )

    before = await other_count()
    value = public_draft(other.id)
    race_key = f"fully-booked:{uuid4()}"
    request_hash = value.request_hash(action_id=action_id, public_alias=alias)
    try:
        async with public.order_command(
            lock_key=f"fully-booked:{buyer.twenty_id}",
            idempotency_key=race_key,
            request_hash=request_hash,
        ) as command:
            assert command.existing_result is None
            await schedules.set_fully_booked(
                action_id=action_id,
                window_id=other.id,
                fully_booked=True,
                actor_user_id=admin_id,
                request_id="fully-booked-proof",
            )
            await command.record_order(
                action_id=action_id,
                public_alias=alias,
                party=party,
                draft=value,
                idempotency_key=race_key,
                request_hash=request_hash,
                request_id="fully-booked-proof",
                occurred_at=now,
            )
    except Conflict as error:
        assert error.code == "delivery_window_full"
    else:
        raise AssertionError("Public order booked a window switched meanwhile")
    assert await other_count() == before
    assert not await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM command_receipt WHERE idempotency_key = $1)",
        race_key,
    )
    await schedules.set_fully_booked(
        action_id=action_id,
        window_id=other.id,
        fully_booked=False,
        actor_user_id=admin_id,
        request_id="fully-booked-proof",
    )

    # Lock order: a switch waits for a running booking, and a booking waits
    # for a pending switch and then sees its committed value.
    async with pool.acquire() as booking:
        transaction = booking.transaction()
        await transaction.start()
        try:
            assert not await guard_window_booking(
                booking, window_id=other.id, allow_full_window=False
            )
            switching = asyncio.create_task(
                schedules.set_fully_booked(
                    action_id=action_id,
                    window_id=other.id,
                    fully_booked=True,
                    actor_user_id=admin_id,
                    request_id="fully-booked-proof",
                )
            )
            await _queued_behind(pool, booking, switching, "Switch")
        finally:
            await transaction.commit()
        assert any(w.fully_booked for w in (await switching).windows)
    async with pool.acquire() as switcher, pool.acquire() as booking:
        async with booking.transaction():
            async with switcher.transaction():
                await switcher.execute(
                    "UPDATE action_delivery_window SET fully_booked = false WHERE id = $1",
                    other.id,
                )
                waiting = asyncio.create_task(
                    guard_window_booking(
                        booking, window_id=other.id, allow_full_window=False
                    )
                )
                await _queued_behind(pool, switcher, waiting, "Booking")
            assert await waiting is False
    print(
        "KLF-065 fully-booked PASS: audited manager switch (no-op repeat, 403/404/409), stale form keeps it, new full window refused, public refusal early and under lock with replay intact, switch between check and record refused on the real path, admin create/completion/manager completion (also of a draft carrying the window) with confirmation recorded, retire clears it, lock order both ways"
    )
