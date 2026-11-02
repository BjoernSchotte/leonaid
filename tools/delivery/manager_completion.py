"""HTTP proof for manager completion of delivery and billing details.

Real PostgreSQL repository behind the real FastAPI route; synthetic identity.
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
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.adapters.postgres.delivery_completion import (
    AsyncpgDeliveryCompletionRepository,
)
from leonaid.application.commitments import (
    CommitmentDraft,
    CommitmentLineDraft,
    CommitmentService,
)
from leonaid.application.delivery_completion import DeliveryCompletionService
from leonaid.domain.action_templates import OfferingUnit
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


async def prove_manager_completion(
    pool: asyncpg.Pool, action_id: UUID, admin_id: UUID, draft: CommitmentDraft
) -> None:
    # A separate customer keeps the privacy lookup proof of orders.py exact.
    assert draft.invoice_recipient is not None
    draft = replace(
        draft,
        buyer=replace(draft.buyer, email="race@example.invalid"),
        invoice_recipient=replace(
            draft.invoice_recipient, email="race@example.invalid"
        ),
    )
    now = datetime.now(timezone.utc)

    def actor(
        user_id: UUID, role: ActionRole, scope: UUID = action_id
    ) -> IdentityPrincipal:
        return IdentityPrincipal(
            UserAccount(
                user_id, f"{user_id}@example.invalid", "Test", AccountStatus.ACTIVE
            ),
            frozenset(),
            (ActionMembership(uuid4(), scope, "Test", user_id, role, now),),
        )

    admin = actor(admin_id, ActionRole.CHARITY_ADMIN)
    app, identity = http_app(admin)
    repo = AsyncpgCommitmentRepository(pool)
    app.state.commitment_service = CommitmentService(repo)
    app.state.delivery_completion_service = DeliveryCompletionService(
        AsyncpgDeliveryCompletionRepository(pool)
    )
    schedules = AsyncpgDeliveryRepository(pool)
    configuration = await schedules.get(action_id)
    first, second = (
        DeliveryWindow(
            uuid4(), action_id, date(2037, 12, 20), time(hour), time(hour + 2)
        )
        for hour in (8, 10)
    )
    await schedules.save(
        replace(configuration, windows=(*configuration.windows, first, second))
    )
    configuration = await schedules.get(action_id)

    # A pre-feature order: review-ready without delivery or billing details.
    legacy = await repo.create(
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
        idempotency_key=f"legacy:{uuid4()}",
        request_hash=uuid4().hex * 2,
        request_id="manager-completion-proof",
        occurred_at=now,
    )
    await pool.execute(
        "UPDATE commitment SET status = 'review_ready' WHERE id = $1", legacy.id
    )
    base = f"/api/v1/actions/{action_id}/commitments"
    order_path = f"{base}/{legacy.id}"
    path = f"{order_path}/delivery-completion"
    billing = {
        "recipientName": "Billing office",
        "streetLine1": "Invoice road 9",
        "postalCode": "54321",
        "city": "Billing",
        "countryCode": "DE",
        "email": "billing@example.invalid",
    }
    delivery = {
        "recipientName": "Warehouse",
        "streetLine1": "Delivery road 2",
        "postalCode": "12345",
        "city": "Test",
        "countryCode": "DE",
    }

    def headers() -> dict[str, str]:
        return {"Idempotency-Key": f"delivery-completion:{uuid4()}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        loaded = (await client.get(order_path)).json()
        version = loaded["deliveryCompletionVersion"]
        assert len(version) == 64 and loaded["status"] == "review_ready"
        body = {
            "expectedVersion": version,
            "invoiceRecipient": billing,
            "deliveryRecipient": delivery,
            "deliveryWindowId": str(first.id),
            "deliveryContact": {"name": "Reception", "phone": "+49 123 45"},
        }

        # Only action managers may complete; never acquirers, drivers,
        # managers of other actions or anonymous callers.
        for denied in (
            actor(uuid4(), ActionRole.ACQUIRER),
            actor(uuid4(), ActionRole.DRIVER),
            actor(admin_id, ActionRole.CHARITY_ADMIN, uuid4()),
        ):
            identity.current = denied
            response = await client.post(path, json=body, headers=headers())
            assert response.status_code == 403, response.text
        identity.current = None
        assert (
            await client.post(path, json=body, headers=headers())
        ).status_code == 401
        identity.current = admin

        # Validation: version format, missing billing, missing window, unknown key.
        for invalid in (
            {**body, "expectedVersion": "stale"},
            {k: v for k, v in body.items() if k != "invoiceRecipient"},
            {**body, "deliveryWindowId": None},
            {**body, "deliveryWindowId": str(uuid4())},
            {**body, "totalMinor": 1},
        ):
            response = await client.post(path, json=invalid, headers=headers())
            assert response.status_code == 422, (invalid, response.text)
        stale = {**body, "expectedVersion": "0" * 64}
        response = await client.post(path, json=stale, headers=headers())
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_completion_conflict"
        assert (await client.get(order_path)).json()[
            "deliveryCompletionVersion"
        ] == version

        # Two competing managers with the same version: exactly one wins.
        competing = {**body, "deliveryContact": {"name": "Other", "phone": None}}
        winner_key, loser_key = headers(), headers()
        results = await asyncio.gather(
            client.post(path, json=body, headers=winner_key),
            client.post(path, json=competing, headers=loser_key),
        )
        assert sorted(r.status_code for r in results) == [200, 409], [
            r.text for r in results
        ]
        winning = next(r for r in results if r.status_code == 200)
        winning_body, winning_headers = (
            (body, winner_key)
            if results[0].status_code == 200
            else (competing, loser_key)
        )
        completed = winning.json()
        loser = next(r for r in results if r.status_code == 409)
        assert loser.json()["code"] == "delivery_completion_conflict"
        assert completed["status"] == "review_ready"
        assert completed["invoiceRecipient"] == billing
        assert completed["deliveryRecipient"] == delivery
        assert completed["deliveryWindowSnapshot"] == first.snapshot(
            configuration.timezone
        )
        for key in ("id", "buyer", "lines", "totalMinor", "currency", "source"):
            assert completed[key] == loaded[key], key
        assert completed["deliveryCompletionVersion"] != version
        events = await pool.fetch(
            """SELECT payload FROM audit_event WHERE entity_id = $1
            AND event_type = 'commitment_delivery_completed'""",
            legacy.id,
        )
        assert len(events) == 1
        assert json.loads(events[0]["payload"]) == {
            "previousStatus": "review_ready",
            "status": "review_ready",
        }
        assert "Warehouse" not in str(events) and "Billing" not in str(events)

        # Exact replay after the booked window was retired returns the result.
        current = await schedules.get(action_id)
        await schedules.save(
            replace(
                current,
                windows=tuple(
                    replace(w, retired=True) if w.id == first.id else w
                    for w in current.windows
                ),
            )
        )
        replay = await client.post(path, json=winning_body, headers=winning_headers)
        assert replay.status_code == 200 and replay.json()["replayed"], replay.text
        assert (
            replay.json()["deliveryWindowSnapshot"]
            == completed["deliveryWindowSnapshot"]
        )
        changed = {
            **winning_body,
            "deliveryContact": {"name": "Changed", "phone": None},
        }
        response = await client.post(path, json=changed, headers=winning_headers)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "idempotency_conflict"

        # The booked time is immutable, even after retirement; billing stays editable.
        new_version = completed["deliveryCompletionVersion"]
        moved = {
            **winning_body,
            "expectedVersion": new_version,
            "deliveryWindowId": str(second.id),
        }
        response = await client.post(path, json=moved, headers=headers())
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_completion_reschedule_forbidden"
        corrected = {
            **winning_body,
            "expectedVersion": new_version,
            "invoiceRecipient": {**billing, "streetLine1": "Invoice road 10"},
        }
        response = await client.post(path, json=corrected, headers=headers())
        assert response.status_code == 200, response.text
        assert response.json()["invoiceRecipient"]["streetLine1"] == "Invoice road 10"
        assert (
            response.json()["deliveryWindowSnapshot"]
            == completed["deliveryWindowSnapshot"]
        )

        # A draft without delivery becomes review-ready when completed.
        open_draft = await repo.create(
            action_id=action_id,
            actor_user_id=admin_id,
            source=CommitmentSource.ADMIN,
            status=CommitmentStatus.DRAFT,
            draft=replace(
                draft,
                delivery_recipient=None,
                delivery_window_id=None,
                delivery_contact=None,
            ),
            idempotency_key=f"open-draft:{uuid4()}",
            request_hash=uuid4().hex * 2,
            request_id="manager-completion-proof",
            occurred_at=now,
        )
        draft_path = f"{base}/{open_draft.id}"
        draft_version = (await client.get(draft_path)).json()[
            "deliveryCompletionVersion"
        ]
        response = await client.post(
            f"{draft_path}/delivery-completion",
            json={
                **body,
                "expectedVersion": draft_version,
                "deliveryWindowId": str(second.id),
            },
            headers=headers(),
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "review_ready"

        # Confirmed or invoiced orders stay unchanged.
        await pool.execute(
            "UPDATE commitment SET status = 'confirmed' WHERE id = $1", open_draft.id
        )
        confirmed_version = (await client.get(draft_path)).json()[
            "deliveryCompletionVersion"
        ]
        response = await client.post(
            f"{draft_path}/delivery-completion",
            json={
                **body,
                "expectedVersion": confirmed_version,
                "deliveryWindowId": str(second.id),
            },
            headers=headers(),
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_completion_closed"
        response = await client.post(
            f"{base}/{uuid4()}/delivery-completion", json=body, headers=headers()
        )
        assert response.status_code == 404, response.text
    print(
        "delivery-completion PASS: manager-only, stale-version conflict, competing edits, "
        "billing and delivery completion, preserved lines/prices, PII-free audit, "
        "replay after retirement, changed-key conflict, immutable booked time, "
        "draft completion, closed orders (synthetic identity)"
    )


async def prove_historical_completion(
    pool: asyncpg.Pool, action_id: UUID, admin_id: UUID
) -> None:
    """All windows have passed: a manager records when an order was delivered.

    Runs last on the foundation action: it inserts past windows (the schedule
    API rightly refuses to create them, and time cannot be moved) and finally
    closes the action's order period, which cannot be undone.
    """
    now = datetime.now(timezone.utc)
    admin = IdentityPrincipal(
        UserAccount(
            admin_id, f"{admin_id}@example.invalid", "Test", AccountStatus.ACTIVE
        ),
        frozenset(),
        (
            ActionMembership(
                uuid4(), action_id, "Test", admin_id, ActionRole.CHARITY_ADMIN, now
            ),
        ),
    )
    app, _identity = http_app(admin)
    repo = AsyncpgCommitmentRepository(pool)
    app.state.commitment_service = CommitmentService(repo)
    app.state.delivery_completion_service = DeliveryCompletionService(
        AsyncpgDeliveryCompletionRepository(pool)
    )
    schedules = AsyncpgDeliveryRepository(pool)
    configuration = await schedules.get(action_id)
    future_active, future_retired = (
        DeliveryWindow(
            uuid4(), action_id, date(2037, 12, 28), time(hour), time(hour + 2)
        )
        for hour in (8, 10)
    )
    configuration = await schedules.save(
        replace(
            configuration,
            windows=(*configuration.windows, future_active, future_retired),
        )
    )
    await schedules.save(
        replace(
            configuration,
            windows=tuple(
                replace(w, retired=True) if w.id == future_retired.id else w
                for w in configuration.windows
            ),
        )
    )
    past, retired_past = uuid4(), uuid4()
    for identifier, days_ago, retired in ((past, 3, False), (retired_past, 5, True)):
        await pool.execute(
            """INSERT INTO action_delivery_window(id, action_id, starts_at, ends_at, retired)
            VALUES ($1, $2,
                (date_trunc('day', now() AT TIME ZONE $3) - make_interval(days => $4)
                    + interval '9 hours') AT TIME ZONE $3,
                (date_trunc('day', now() AT TIME ZONE $3) - make_interval(days => $4)
                    + interval '11 hours') AT TIME ZONE $3,
                $5)""",
            identifier,
            action_id,
            configuration.timezone,
            days_ago,
            retired,
        )
    configuration = await schedules.get(action_id)
    snapshots = {
        window.id: window.snapshot(configuration.timezone)
        for window in configuration.windows
    }
    offering_id = await pool.fetchval(
        "SELECT id FROM offering WHERE action_id=$1 AND status='active' LIMIT 1",
        action_id,
    )
    draft = CommitmentDraft(
        BuyerSnapshot(
            CommitmentPartyKind.PERSON, uuid4(), "Late", "late@example.invalid"
        ),
        None,
        (CommitmentLineDraft(offering_id, 1, OfferingUnit.BOX, 3600),),
    )
    billing = {
        "recipientName": "Billing office",
        "streetLine1": "Invoice road 9",
        "postalCode": "54321",
        "city": "Billing",
        "countryCode": "DE",
        "email": "billing@example.invalid",
    }
    delivery = {
        "recipientName": "Warehouse",
        "streetLine1": "Delivery road 2",
        "postalCode": "12345",
        "city": "Test",
        "countryCode": "DE",
    }
    base = f"/api/v1/actions/{action_id}/commitments"

    def headers() -> dict[str, str]:
        return {"Idempotency-Key": f"delivery-completion:{uuid4()}"}

    async def order(status: CommitmentStatus) -> str:
        created = await repo.create(
            action_id=action_id,
            actor_user_id=admin_id,
            source=CommitmentSource.ADMIN,
            status=CommitmentStatus.DRAFT,
            draft=draft,
            idempotency_key=f"historical:{uuid4()}",
            request_hash=uuid4().hex * 2,
            request_id="historical-completion-proof",
            occurred_at=now,
        )
        await pool.execute(
            "UPDATE commitment SET status = $2 WHERE id = $1", created.id, status.value
        )
        return f"{base}/{created.id}"

    async def audit(path: str) -> list[dict[str, object]]:
        rows = await pool.fetch(
            """SELECT payload FROM audit_event WHERE entity_id = $1
            AND event_type = 'commitment_delivery_completed' ORDER BY occurred_at""",
            UUID(path.rsplit("/", 1)[1]),
        )
        return [json.loads(row["payload"]) for row in rows]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def complete(path: str, window: UUID, **extra: Any) -> httpx.Response:
            version = (await client.get(path)).json()["deliveryCompletionVersion"]
            return await client.post(
                f"{path}/delivery-completion",
                json={
                    "expectedVersion": version,
                    "invoiceRecipient": billing,
                    "deliveryRecipient": delivery,
                    "deliveryWindowId": str(window),
                    **extra,
                },
                headers=headers(),
            )

        # Capture (the draft completion command) still rejects past windows,
        # even for a manager; only the manager completion records history.
        capture = await order(CommitmentStatus.DRAFT)
        response = await client.post(
            f"{capture}/complete",
            json={"deliveryRecipient": delivery, "deliveryWindowId": str(past)},
            headers=headers(),
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "delivery_window_unavailable"

        # A configured past window and a retired past window are both history.
        late = await order(CommitmentStatus.REVIEW_READY)
        response = await complete(late, past)
        assert response.status_code == 200, response.text
        recorded = response.json()
        assert recorded["status"] == "review_ready"
        assert recorded["deliveryWindowId"] == str(past)
        assert recorded["deliveryWindowSnapshot"] == snapshots[past]
        assert await audit(late) == [
            {
                "previousStatus": "review_ready",
                "status": "review_ready",
                "historical": True,
            }
        ]
        events = await pool.fetch(
            "SELECT payload::text AS payload FROM audit_event WHERE entity_id = $1",
            UUID(late.rsplit("/", 1)[1]),
        )
        assert all(
            "Warehouse" not in row["payload"] and "Billing" not in row["payload"]
            for row in events
        )
        retired_late = await order(CommitmentStatus.REVIEW_READY)
        response = await complete(retired_late, retired_past)
        assert response.status_code == 200, response.text
        assert response.json()["deliveryWindowSnapshot"] == snapshots[retired_past]

        # The recorded time is now booked and immutable; billing stays editable.
        response = await complete(late, future_active.id)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "delivery_completion_reschedule_forbidden"
        response = await complete(
            late, past, invoiceRecipient={**billing, "streetLine1": "Invoice road 11"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["deliveryWindowSnapshot"] == snapshots[past]
        assert (await audit(late))[-1]["historical"] is False

        # A retired window that has not started yet is not history; a future
        # window is an ordinary completion.
        unused = await order(CommitmentStatus.REVIEW_READY)
        response = await complete(unused, future_retired.id)
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "delivery_window_unavailable"
        response = await complete(unused, future_active.id)
        assert response.status_code == 200, response.text
        assert await audit(unused) == [
            {
                "previousStatus": "review_ready",
                "status": "review_ready",
                "historical": False,
            }
        ]

        # After the order period closed, capture is closed, but a manager can
        # still complete a draft that was actually delivered.
        closed_draft = await order(CommitmentStatus.DRAFT)
        captured = await order(CommitmentStatus.DRAFT)
        for status in ("active", "completed"):
            await pool.execute(
                "UPDATE charity_action SET status = $2 WHERE id = $1",
                action_id,
                status,
            )
        response = await client.post(
            f"{captured}/complete",
            json={"deliveryRecipient": delivery, "deliveryWindowId": str(past)},
            headers=headers(),
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "commitment_action_closed"
        response = await complete(closed_draft, past)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "review_ready"
        assert await audit(closed_draft) == [
            {"previousStatus": "draft", "status": "review_ready", "historical": True}
        ]
    print(
        "delivery-completion historical PASS: past and retired past windows recorded "
        "by managers only, capture rejects past windows, retired future windows "
        "rejected, recorded time immutable, historical audit flag without personal "
        "data, draft completion after the order period closed (synthetic identity)"
    )
