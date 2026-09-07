"""Prove persisted template defaults and effective form projections."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.adapters.postgres.delivery import AsyncpgDeliveryRepository
from leonaid.domain.actions import (
    ActionGoal,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
)
from leonaid.domain.delivery import DeliveryWindow
from leonaid.domain.action_templates import ActionTemplateKey
from leonaid.application.errors import Conflict
from leonaid.domain.errors import DomainInvariantError
from leonaid.entrypoints.fastapi.routes import delivery_order_form_response


async def prove_form_configuration(pool: asyncpg.Pool[Any], actor: UUID) -> None:
    actions = AsyncpgCharityActionRepository(pool)
    schedules = AsyncpgDeliveryRepository(pool)
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    for key in ("krapfentaxi", "blank"):
        template = await actions.get_template(ActionTemplateKey(key), None)
        assert template is not None
        identifier = uuid4()
        action = CharityAction(
            identifier,
            "Test",
            "Test",
            "Test",
            CharityActionStatus.DRAFT,
            date(2027, 2, 1),
            date(2027, 2, 28),
            f"test-{identifier}",
            template.capabilities,
            (Beneficiary(uuid4(), identifier, "Test beneficiary", "Test purpose", 0),),
            ActionGoal(None, Decimal(0), None, "EUR"),
        )
        await actions.create(
            action,
            responsible_admin_user_id=actor,
            request_id="delivery-live",
            occurred_at=now,
            configuration=template.configure(identifier),
        )
        config = await schedules.get(identifier)
        assert config.enabled == (key == "krapfentaxi")
        form = delivery_order_form_response(config, evaluated_at=now)
        assert form.require_window == config.enabled
        assert form.windows == []
        if key == "blank":
            await prove_non_delivery_order(pool, identifier, actor, now)
            continue
        window = DeliveryWindow(
            uuid4(), identifier, date(2027, 2, 5), time(9), time(11)
        )
        config = await schedules.save(replace(config, windows=(window,)))
        form = delivery_order_form_response(
            await schedules.get(identifier), evaluated_at=now
        )
        assert form.allow_contact and form.allow_instructions
        assert form.windows[0].id == window.id
        assert form.instructions_max_length == 1000
        try:
            await actions.update_details(
                replace(action, starts_on=date(2027, 2, 6)),
                actor_user_id=actor,
                request_id="delivery-live",
                occurred_at=now,
            )
        except DomainInvariantError:
            pass
        else:
            raise AssertionError("Action period excluded a configured delivery date")
        loaded = await actions.get(identifier)
        assert loaded is not None and loaded.starts_on == action.starts_on
        future_form = delivery_order_form_response(
            config, evaluated_at=datetime(2027, 3, 1, tzinfo=timezone.utc)
        )
        assert future_form.windows == [] and future_form.require_window
        async with pool.acquire() as connection:
            for status in ("scheduled", "active", "completed", "archived"):
                await connection.execute(
                    "UPDATE charity_action SET status = $2 WHERE id = $1",
                    identifier,
                    status,
                )
        try:
            await schedules.save(replace(config, enabled=False))
        except Conflict as error:
            assert error.code == "delivery_action_archived"
        else:
            raise AssertionError("Archived action accepted a schedule change")
        assert (await schedules.get(identifier)).enabled
    print(
        "delivery-form: PASS: persisted Krapfentaxi/blank defaults, effective fields, available windows, period protection"
    )


async def prove_non_delivery_order(
    pool: asyncpg.Pool[Any], action_id: UUID, actor: UUID, now: datetime
) -> None:
    from leonaid.adapters.postgres.commitments import AsyncpgCommitmentRepository
    from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
    from leonaid.domain.commitments import (
        BuyerSnapshot,
        Commitment,
        CommitmentPartyKind,
        CommitmentSource,
        CommitmentStatus,
        InvoiceRecipientSnapshot,
    )
    from leonaid.domain.action_templates import OfferingUnit

    offering = uuid4()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO charity_action_capability(action_id, capability) VALUES ($1, 'ordering') ON CONFLICT DO NOTHING",
            action_id,
        )
        await connection.execute(
            """INSERT INTO offering(id, action_id, code, name, status, unit, unit_price_minor, currency, allowed_quantity_units)
            VALUES ($1, $2, 'sponsor', 'Synthetic sponsorship', 'active', 'sponsoring', 500, 'EUR', ARRAY['sponsoring'])""",
            offering,
            action_id,
        )
    draft = CommitmentDraft(
        buyer=BuyerSnapshot(CommitmentPartyKind.COMPANY, uuid4(), "Synthetic sponsor"),
        invoice_recipient=InvoiceRecipientSnapshot(
            "Sponsor invoice", "Testweg 1", "00000", "Teststadt"
        ),
        delivery_recipient=None,
        lines=(CommitmentLineDraft(offering, 1, OfferingUnit.SPONSORING),),
        delivery_window_id=None,
    )
    repository = AsyncpgCommitmentRepository(pool)
    key = str(uuid4())

    async def create() -> Commitment:
        return await repository.create(
            action_id=action_id,
            actor_user_id=actor,
            source=CommitmentSource.ADMIN,
            status=CommitmentStatus.REVIEW_READY,
            draft=draft,
            idempotency_key=key,
            request_hash=draft.fingerprint(
                action_id=action_id,
                source=CommitmentSource.ADMIN,
                status=CommitmentStatus.REVIEW_READY,
            ),
            request_id="non-delivery-proof",
            occurred_at=now,
        )

    saved = await create()
    replay = await create()
    assert saved.status is CommitmentStatus.REVIEW_READY
    assert (
        saved.total.amount_minor == 500
        and saved.invoice_recipient == draft.invoice_recipient
    )
    assert replay.id == saved.id and replay.replayed
    async with pool.acquire() as connection:
        loaded = await repository._get(connection, saved.id, replayed=False)
    assert loaded.delivery_recipient is None
    assert loaded.delivery_window_id is None and loaded.delivery_window_snapshot is None
    assert loaded.lines == saved.lines and loaded.total == saved.total
    print(
        "non-delivery-order: PASS: persisted blank action, sponsorship pricing, review-ready create/readback and exact replay without delivery fields"
    )
