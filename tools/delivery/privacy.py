"""Real PostgreSQL delivery export/erasure proof using synthetic identities."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.adapters.postgres.legal_configuration import (
    AsyncpgLegalConfigurationRepository,
)
from leonaid.adapters.postgres.privacy import AsyncpgPrivacyRepository
from leonaid.application.privacy import PrivacyService
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
            item["deliveryContact"] == {"name": "Reception", "phone": "+49 123-45"}
            and item["deliveryWindowSnapshot"]["windowId"] == item["deliveryWindowId"]
            for item in with_contact
        )
        assert any(item["deliveryWindowId"] is None for item in details)
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
    assert not (await repo.subject_report(email)).order_deliveries
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
        "KLF-030 privacy PASS: scoped HTTP lookup, export delivery snapshots/contact, historical nulls, 401/403, erasure removes contacts, windows and invoice snapshots retained"
    )
