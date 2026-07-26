from __future__ import annotations

from dataclasses import fields, replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from leonaid.domain.actions import (
    ALLOWED_ACTION_TRANSITIONS,
    ActionCapability,
    ActionGoal,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
)
from leonaid.domain.errors import DomainInvariantError

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
BENEFICIARY_ID = UUID("30000000-0000-4000-8000-000000000001")


def neutral_action(
    *,
    status: CharityActionStatus = CharityActionStatus.DRAFT,
    capabilities: frozenset[ActionCapability] = frozenset(),
    beneficiaries: tuple[Beneficiary, ...] | None = None,
) -> CharityAction:
    return CharityAction(
        id=ACTION_ID,
        carrier_name="Lions Hilfswerk Beispielstadt",
        name="Quartalsaktion 2027",
        purpose="Förderung lokaler Bildungsangebote.",
        status=status,
        starts_on=date(2027, 2, 1),
        ends_on=date(2027, 3, 31),
        archive_slug="quartalsaktion-01-2027",
        capabilities=capabilities,
        beneficiaries=(
            beneficiaries
            if beneficiaries is not None
            else (
                Beneficiary(
                    id=BENEFICIARY_ID,
                    action_id=ACTION_ID,
                    organization_name="Bildungshafen Beispielstadt",
                    public_description="Finanziert Lernmaterial für Kinder.",
                    sort_order=0,
                ),
            )
        ),
        goal=ActionGoal(
            goal_value=Decimal("12500"),
            actual_value=Decimal("250.50"),
            unit="EUR",
            currency="EUR",
        ),
    )


def test_every_lifecycle_transition_is_explicitly_allowed_or_rejected() -> None:
    for source in CharityActionStatus:
        action = neutral_action(status=source)
        for target in CharityActionStatus:
            if target is source:
                assert action.transition_to(target) is action
            elif target in ALLOWED_ACTION_TRANSITIONS[source]:
                assert action.transition_to(target).status is target
            else:
                with pytest.raises(DomainInvariantError) as captured:
                    action.transition_to(target)
                assert captured.value.code == "action_status_transition_invalid"


def test_capability_and_beneficiary_invariants_stay_action_neutral() -> None:
    complete = neutral_action(
        capabilities=frozenset(
            {
                ActionCapability.ACQUISITION,
                ActionCapability.OFFERINGS,
                ActionCapability.ORDERING,
                ActionCapability.INVOICING,
            }
        )
    )
    assert complete.capabilities == frozenset(ActionCapability)

    with pytest.raises(DomainInvariantError) as missing_offering:
        neutral_action(
            capabilities=frozenset({ActionCapability.ORDERING}),
        )
    assert missing_offering.value.code == "action_capability_dependency_invalid"

    with pytest.raises(DomainInvariantError) as no_beneficiary:
        neutral_action(beneficiaries=())
    assert no_beneficiary.value.code == "action_beneficiary_required"

    duplicate = replace(
        complete.beneficiaries[0],
        id=UUID("30000000-0000-4000-8000-000000000002"),
        organization_name="  BILDUNGSHAFEN   BEISPIELSTADT ",
        sort_order=1,
    )
    with pytest.raises(DomainInvariantError) as duplicate_beneficiary:
        neutral_action(beneficiaries=(*complete.beneficiaries, duplicate))
    assert duplicate_beneficiary.value.code == "action_beneficiary_duplicate"

    assert {field.name for field in fields(CharityAction)} == {
        "id",
        "carrier_name",
        "name",
        "purpose",
        "status",
        "starts_on",
        "ends_on",
        "archive_slug",
        "capabilities",
        "beneficiaries",
        "goal",
    }


def test_goal_requires_nonnegative_values_and_a_paired_unit() -> None:
    with pytest.raises(DomainInvariantError) as missing_unit:
        ActionGoal(
            goal_value=Decimal("100"),
            actual_value=Decimal("0"),
            unit=None,
        )
    assert missing_unit.value.code == "action_goal_unit_incomplete"

    with pytest.raises(DomainInvariantError) as negative_actual:
        ActionGoal(
            goal_value=Decimal("100"),
            actual_value=Decimal("-0.01"),
            unit="Teilnehmende",
        )
    assert negative_actual.value.code == "action_actual_negative"

    with pytest.raises(DomainInvariantError) as excess_precision:
        ActionGoal(
            goal_value=Decimal("100.00001"),
            actual_value=Decimal("0"),
            unit="EUR",
        )
    assert excess_precision.value.code == "action_goal_precision"
