"""HTTP order creation/completion proof with a real database and fixture identity."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.application.commitments import CommitmentService
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)
from tools.delivery.http_configuration import http_app


async def prove_completion(pool: asyncpg.Pool, action_id: UUID, admin_id: UUID) -> None:
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

    anna_id, colleague_id, person_id = uuid4(), uuid4(), uuid4()
    for user_id in (anna_id, colleague_id):
        await pool.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Test','active')",
            user_id,
            f"{user_id}@example.invalid",
        )
        await pool.execute(
            "INSERT INTO acquisition_assignment(id,action_id,twenty_person_id,acquirer_user_id) VALUES($1,$2,$3,$4)",
            uuid4(),
            action_id,
            person_id,
            user_id,
        )
    anna = actor(anna_id, ActionRole.ACQUIRER)
    admin = actor(admin_id, ActionRole.CHARITY_ADMIN)
    app, identity = http_app(anna)
    repo = AsyncpgCommitmentRepository(pool)
    app.state.commitment_service = CommitmentService(repo)
    schedules = AsyncpgDeliveryRepository(pool)
    configuration = await schedules.get(action_id)
    window = next(w for w in configuration.windows if not w.retired)
    offering_id = await pool.fetchval(
        "SELECT id FROM offering WHERE action_id=$1 LIMIT 1", action_id
    )
    path = f"/api/v1/actions/{action_id}/commitments"
    body = {
        "source": "acquisition",
        "readyForReview": False,
        "buyer": {
            "partyKind": "person",
            "twentyId": str(person_id),
            "displayName": "Buyer",
        },
        "invoiceRecipient": {
            "recipientName": "Billing",
            "streetLine1": "Invoice 1",
            "postalCode": "12345",
            "city": "Test",
        },
        "lines": [
            {
                "offeringId": str(offering_id),
                "quantity": 2,
                "unit": "box",
                "quotedUnitPriceMinor": 1,
            }
        ],
    }
    delivery = {
        "deliveryRecipient": {
            "recipientName": "Warehouse",
            "streetLine1": "Delivery 2",
            "postalCode": "12345",
            "city": "Test",
        },
        "deliveryWindowId": str(window.id),
        "deliveryContact": {"name": " Reception ", "phone": "+49 123 / 456"},
    }

    def headers():
        return {"Idempotency-Key": f"delivery:{uuid4()}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Direct HTTP capture has the same required fields as the future UI.
        response = await client.post(
            path, json={**body, "readyForReview": True}, headers=headers()
        )
        assert (
            response.status_code == 422
            and response.json()["code"] == "delivery_required"
        ), response.text
        response = await client.post(
            path, json={**body, **delivery, "readyForReview": True}, headers=headers()
        )
        assert response.status_code == 201, response.text
        direct = response.json()
        assert direct["deliveryContact"]["name"] == "Reception"
        assert direct["totalMinor"] > 2  # Ignore the client quote.
        draft_headers = headers()
        response = await client.post(path, json=body, headers=draft_headers)
        assert response.status_code == 201, response.text
        draft = response.json()
        replay = await client.post(path, json=body, headers=draft_headers)
        assert replay.status_code == 201 and replay.json()["replayed"], replay.text
        order_path = f"{path}/{draft['id']}"
        complete_path = f"{order_path}/complete"
        response = await client.get(order_path)
        assert (
            response.status_code == 200
            and response.headers["cache-control"] == "private, no-store"
        )
        # Another assigned acquirer still cannot retrieve/complete Anna's order.
        identity.current = actor(colleague_id, ActionRole.ACQUIRER)
        assert (
            await client.post(path, json=body, headers=draft_headers)
        ).status_code == 403
        assert (await client.get(order_path)).status_code == 403
        assert (
            await client.post(complete_path, json=delivery, headers=headers())
        ).status_code == 403
        identity.current = actor(admin_id, ActionRole.CHARITY_ADMIN, uuid4())
        assert (await client.get(order_path)).status_code == 403
        identity.current = actor(anna_id, ActionRole.DRIVER)
        assert (
            await client.post(complete_path, json=delivery, headers=headers())
        ).status_code == 403
        identity.current = anna
        assert (
            await client.post(complete_path, json={}, headers=headers())
        ).status_code == 422
        assert (
            await client.post(
                complete_path,
                json={**delivery, "deliveryWindowId": str(uuid4())},
                headers=headers(),
            )
        ).status_code == 422
        assert (
            await client.post(
                complete_path, json={**delivery, "totalMinor": 1}, headers=headers()
            )
        ).status_code == 422
        assert (await client.get(order_path)).json()["status"] == "draft"
        # Reassignment revokes access even if Anna retained the URL.
        await pool.execute(
            "DELETE FROM acquisition_assignment WHERE action_id=$1 AND acquirer_user_id=$2",
            action_id,
            anna_id,
        )
        assert (
            await client.post(path, json=body, headers=draft_headers)
        ).status_code == 403
        assert (
            await client.post(path, json=body, headers=headers())
        ).status_code == 403
        assert (await client.get(order_path)).status_code == 403
        assert (
            await client.post(complete_path, json=delivery, headers=headers())
        ).status_code == 403
        await pool.execute(
            "INSERT INTO acquisition_assignment(id,action_id,twenty_person_id,acquirer_user_id) VALUES($1,$2,$3,$4)",
            uuid4(),
            action_id,
            person_id,
            anna_id,
        )
        # Competing different commands: one transition, one conflict, one event.
        first_headers, second_headers = headers(), headers()
        results = await asyncio.gather(
            client.post(complete_path, json=delivery, headers=first_headers),
            client.post(complete_path, json=delivery, headers=second_headers),
        )
        assert sorted(r.status_code for r in results) == [200, 409], [
            r.text for r in results
        ]
        winner_index = next(
            i for i, response in enumerate(results) if response.status_code == 200
        )
        winning_headers = (first_headers, second_headers)[winner_index]
        completed = results[winner_index].json()
        assert completed["status"] == "review_ready"
        for key in ("id", "buyer", "invoiceRecipient", "lines", "totalMinor"):
            assert completed[key] == draft[key]
        assert completed["deliveryWindowSnapshot"] == window.snapshot(
            configuration.timezone
        )
        assert completed["deliveryContact"]["name"] == "Reception"
        events = await pool.fetch(
            "SELECT payload FROM audit_event WHERE entity_id=$1 AND event_type='commitment_completed'",
            UUID(draft["id"]),
        )
        assert len(events) == 1 and "Reception" not in str(events)
        assert json.loads(events[0]["payload"]) == {
            "previousStatus": "draft",
            "status": "review_ready",
        }
        configuration = await schedules.get(action_id)
        await schedules.save(
            replace(
                configuration,
                windows=tuple(
                    replace(w, retired=True) if w.id == window.id else w
                    for w in configuration.windows
                ),
            )
        )
        replay = await client.post(
            complete_path, json=delivery, headers=winning_headers
        )
        assert replay.status_code == 200 and replay.json()["replayed"], replay.text
        changed = {**delivery, "deliveryContact": {"phone": "123"}}
        assert (
            await client.post(complete_path, json=changed, headers=winning_headers)
        ).status_code == 409
        identity.current = None
        assert (await client.get(order_path)).status_code == 401
        assert (
            await client.post(complete_path, json=delivery, headers=headers())
        ).status_code == 401
        # The manager may complete another internal draft, including pre-feature drafts.
        identity.current = anna
        response = await client.post(path, json=body, headers=headers())
        another = response.json()
        identity.current = admin
        available = next(
            w for w in configuration.windows if not w.retired and w.id != window.id
        )
        response = await client.post(
            f"{path}/{another['id']}/complete",
            json={**delivery, "deliveryWindowId": str(available.id)},
            headers=headers(),
        )
        assert response.status_code == 200, response.text
        assert (await client.get(f"{path}/{uuid4()}")).status_code == 404
    print(
        "KLF-030 completion PASS: direct HTTP required fields and snapshots, ownership/assignment/role isolation, atomic draft transition, stable prices, concurrent conflict, contact-free audit, replay after retirement (synthetic identity)"
    )
