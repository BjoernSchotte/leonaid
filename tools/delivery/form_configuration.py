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
    print(
        "delivery-form: PASS: persisted Krapfentaxi/blank defaults, effective fields, available windows, period protection"
    )
