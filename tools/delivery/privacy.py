"""Real PostgreSQL delivery export/erasure proof using synthetic identities."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.legal_configuration import (
    AsyncpgLegalConfigurationRepository,
)
from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
from leonaid.adapters.postgres.order_cancellation import (
    AsyncpgOrderCancellationRepository,
)
from leonaid.adapters.postgres.delivery_geo import AsyncpgDeliveryGeoRepository
from leonaid.adapters.postgres.privacy import AsyncpgPrivacyRepository
from leonaid.application.delivery_completion import delivery_completion_version
from leonaid.application.order_cancellation import OrderCancellationRequest
from leonaid.application.privacy import PrivacyService
from leonaid.domain.delivery_geo import GeoPoint
from leonaid.domain.identity import (
    AccountStatus,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from tests.unit.test_legal_configuration import valid_draft
from tools.delivery.http_configuration import http_app


async def prove_privacy(pool: asyncpg.Pool, admin_id: UUID) -> None:
    now = datetime.now(timezone.utc)
    legal = AsyncpgLegalConfigurationRepository(pool)
    state = await legal.state()
    state = await legal.save_draft(
        configuration=valid_draft(),
        actor_user_id=admin_id,
        expected_revision=state.revision,
        request_id="delivery-privacy-proof",
        occurred_at=now,
    )
    approver = uuid4()
    await pool.execute(
        "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,'approver@example.invalid','Test approver','active')",
        approver,
    )
    assert state.draft is not None
    version_id = state.draft.id
    state = await legal.approve(
        version_id=version_id,
        actor_user_id=approver,
        evidence_id="SYNTHETIC-DELIVERY-TEST",
        expected_revision=state.revision,
        request_id="delivery-privacy-proof",
        occurred_at=now,
    )
    await legal.activate(
        version_id=version_id,
        actor_user_id=admin_id,
        expected_revision=state.revision,
        request_id="delivery-privacy-proof",
        occurred_at=now,
    )

    repo = AsyncpgPrivacyRepository(pool, subject_hmac_secret="synthetic-proof-" * 4)
    actor = IdentityPrincipal(
        UserAccount(admin_id, "admin@example.invalid", "Test", AccountStatus.ACTIVE),
        frozenset({GlobalRole.SYSTEM_ADMIN}),
        (),
    )
    app, identity = http_app(actor)
    app.state.privacy_service = PrivacyService(repo)
    email = "customer@example.invalid"
    # A pinned delivery address: its coordinates are personal data too.
    pinned = await pool.fetchrow(
        """
        SELECT id, action_id FROM commitment
        WHERE lower(customer_snapshot ->> 'email') = $1
          AND delivery_recipient_snapshot IS NOT NULL
        ORDER BY created_at, id LIMIT 1
        """,
        email,
    )
    assert pinned is not None
    await AsyncpgDeliveryGeoRepository(pool).set_pin(
        action_id=pinned["action_id"],
        commitment_id=pinned["id"],
        point=GeoPoint(Decimal("48.137154"), Decimal("11.576124")),
        at=now,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/admin/privacy/lookup", json={"email": email}
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        details = response.json()["orderDeliveries"]
        with_contact = [item for item in details if item["deliveryContact"]]
        assert len(with_contact) == 2
        assert all(
            item["deliveryContact"]
            == {
                "name": "Reception",
                "phone": "+49 123-45",
                "driverNote": "Hintereingang im Hof",
            }
            and item["deliveryWindowSnapshot"]["windowId"] == item["deliveryWindowId"]
            for item in with_contact
        )
        assert any(item["deliveryWindowId"] is None for item in details)
        assert [
            item["coordinates"]
            for item in details
            if item["commitmentId"] == str(pinned["id"])
        ] == [{"lat": 48.137154, "lon": 11.576124}]
        identity.current = replace(actor, global_roles=frozenset())
        assert (
            await client.post("/api/v1/admin/privacy/lookup", json={"email": email})
        ).status_code == 403
        identity.current = None
        assert (
            await client.post("/api/v1/admin/privacy/lookup", json={"email": email})
        ).status_code == 401

    # The same service value feeds the fresh-login protected JSON export.
    exported = await app.state.privacy_service.export(actor, email=email)
    assert len(exported.order_deliveries) == len(details)
    assert exported.retention.legal_configuration_version_id == version_id
    before = {
        row["id"]: (row["delivery_window_id"], row["delivery_window_snapshot"])
        for row in await pool.fetch(
            "SELECT id,delivery_window_id,delivery_window_snapshot FROM commitment WHERE id=ANY($1::uuid[])",
            [item.commitment_id for item in exported.order_deliveries],
        )
    }
    # A cancelled order's free-text note goes with the erasure; the reason
    # stays, like an invoice cancellation reason (ADR-0009).
    cancelled_id = exported.order_deliveries[0].commitment_id
    async with pool.acquire() as connection:
        cancelled_order = await AsyncpgCommitmentRepository._get(
            connection, cancelled_id, replayed=False
        )
    cancel_request = OrderCancellationRequest(
        delivery_completion_version(cancelled_order),
        "Sponsor hat die Bestellung zurückgezogen",
        "Rückruf bei customer@example.invalid, Tel. +49 123-45",
    )
    await AsyncpgOrderCancellationRepository(pool).cancel(
        action_id=cancelled_order.action_id,
        commitment_id=cancelled_id,
        actor_user_id=admin_id,
        request=cancel_request,
        fresh_login=True,
        idempotency_key=f"privacy-cancel:{cancelled_id}",
        request_hash=cancel_request.fingerprint(
            action_id=cancelled_order.action_id,
            commitment_id=cancelled_id,
            actor_user_id=admin_id,
        ),
        request_id="delivery-privacy-proof",
        occurred_at=now,
    )
    # No retained invoice is changed by the delivery extension or erasure path.
    invoices = await pool.fetch(
        "SELECT id,to_jsonb(invoice)::text AS snapshot FROM invoice"
    )
    result = await app.state.privacy_service.erase(
        actor,
        email=email,
        confirmation=email,
        request_id="delivery-privacy-proof",
    )
    assert result.anonymized_commitments == len(details)
    for row in await pool.fetch(
        "SELECT * FROM commitment WHERE id=ANY($1::uuid[])", list(before)
    ):
        assert row["delivery_contact_snapshot"] is None
        assert (row["delivery_window_id"], row["delivery_window_snapshot"]) == before[
            row["id"]
        ]
        if row["delivery_recipient_snapshot"]:
            assert (
                json.loads(row["delivery_recipient_snapshot"])["recipientName"]
                == "Anonymisiert"
            )
    assert (
        await pool.fetch("SELECT id,to_jsonb(invoice)::text AS snapshot FROM invoice")
        == invoices
    )
    cancellation = await pool.fetchrow(
        "SELECT reason_snapshot, note_snapshot FROM commitment_cancellation"
        " WHERE commitment_id=$1",
        cancelled_id,
    )
    assert cancellation["note_snapshot"] is None
    assert cancellation["reason_snapshot"] == cancel_request.reason
    assert not (await repo.subject_report(email)).order_deliveries
    assert not await pool.fetchval(
        "SELECT count(*) FROM delivery_geo WHERE commitment_id = ANY($1::uuid[])",
        list(before),
    )
    legacy_result = await app.state.privacy_service.erase(
        actor,
        email="legacy@leonaid.invalid",
        confirmation="legacy@leonaid.invalid",
        request_id="delivery-privacy-legacy-proof",
    )
    assert legacy_result.retained_invoice_ids
    assert (
        await pool.fetch("SELECT id,to_jsonb(invoice)::text AS snapshot FROM invoice")
        == invoices
    )
    print(
        "KLF-030 privacy PASS: scoped HTTP lookup, export delivery snapshots/contact, historical nulls, 401/403, erasure removes contacts, coordinates and the cancellation note, windows and invoice snapshots retained"
    )
