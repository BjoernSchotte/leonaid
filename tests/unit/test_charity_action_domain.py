from __future__ import annotations

from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from leonaid.domain.actions import (
    ALLOWED_ACTION_TRANSITIONS,
    ActionManagementState,
    ActionCapability,
    ActionGoal,
    AdministratorOption,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
    PublicationWindow,
    PublicActionAlias,
)
from leonaid.domain.errors import DomainInvariantError

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
BENEFICIARY_ID = UUID("30000000-0000-4000-8000-000000000001")


def neutral_action(
    *,
    status: CharityActionStatus = CharityActionStatus.DRAFT,
    capabilities: frozenset[ActionCapability] = frozenset(),
    beneficiaries: tuple[Beneficiary, ...] | None = None,
    archive_slug: str = "quartalsaktion-01-2027",
) -> CharityAction:
    return CharityAction(
        id=ACTION_ID,
        carrier_name="Lions Hilfswerk Beispielstadt",
        name="Quartalsaktion 2027",
        purpose="Förderung lokaler Bildungsangebote.",
        status=status,
        starts_on=date(2027, 2, 1),
        ends_on=date(2027, 3, 31),
        archive_slug=archive_slug,
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
        "publication_window",
        "revision",
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


def test_publication_details_and_revision_are_server_side_invariants() -> None:
    starts_at = datetime(2027, 1, 10, 8, tzinfo=timezone.utc)
    window = PublicationWindow(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(days=90),
    )
    published = neutral_action().with_publication_window(window)
    changed = published.with_details(
        carrier_name="Lions Hilfswerk Beispielstadt e. V.",
        name="Quartalsaktion Frühjahr 2027",
        purpose="Förderung lokaler Lernorte.",
        starts_on=date(2027, 2, 2),
        ends_on=date(2027, 4, 1),
    )

    assert changed.publication_window == window
    assert changed.next_revision().revision == 2
    assert PublicActionAlias("quartalsaktion").value == "quartalsaktion"
    assert (
        neutral_action(status=CharityActionStatus.ACTIVE)
        .with_publication_window(window)
        .is_published_at(starts_at + timedelta(days=1))
    )
    assert not published.is_published_at(starts_at + timedelta(days=1))

    with pytest.raises(DomainInvariantError) as naive:
        PublicationWindow(
            starts_at=datetime(2027, 1, 1),
            ends_at=datetime(2027, 2, 1),
        )
    assert naive.value.code == "action_publication_timezone_required"

    with pytest.raises(DomainInvariantError) as backwards:
        PublicationWindow(
            starts_at=starts_at,
            ends_at=starts_at - timedelta(seconds=1),
        )
    assert backwards.value.code == "action_publication_period_invalid"

    with pytest.raises(DomainInvariantError) as alias:
        PublicActionAlias("Quartals Aktion")
    assert alias.value.code == "action_public_alias_invalid"

    with pytest.raises(DomainInvariantError) as reserved_alias:
        PublicActionAlias("archive")
    assert reserved_alias.value.code == "action_public_alias_reserved"

    with pytest.raises(DomainInvariantError) as archive_slug:
        neutral_action(archive_slug="Quartals Aktion")
    assert archive_slug.value.code == "action_archive_slug_invalid"

    with pytest.raises(DomainInvariantError) as naive_evaluation:
        neutral_action(status=CharityActionStatus.ACTIVE).is_published_at(
            datetime(2027, 1, 1)
        )
    assert (
        naive_evaluation.value.code == "action_publication_evaluation_timezone_required"
    )

    archived = neutral_action(status=CharityActionStatus.ARCHIVED)
    with pytest.raises(DomainInvariantError) as immutable:
        archived.with_details(
            carrier_name=archived.carrier_name,
            name="Nachträgliche Änderung",
            purpose=archived.purpose,
            starts_on=archived.starts_on,
            ends_on=archived.ends_on,
        )
    assert immutable.value.code == "action_archived_immutable"


def test_management_state_requires_one_unique_responsible_admin() -> None:
    option = AdministratorOption(
        user_id=UUID("10000000-0000-4000-8000-000000000002"),
        display_name="Klara Koordination",
        email="klara@leonaid.invalid",
        is_available=True,
        is_responsible=True,
    )
    state = ActionManagementState(
        action=neutral_action(),
        public_alias=PublicActionAlias("quartalsaktion"),
        administrator_options=(option,),
    )
    assert state.administrator_options == (option,)

    with pytest.raises(DomainInvariantError) as duplicate:
        ActionManagementState(
            action=neutral_action(),
            public_alias=None,
            administrator_options=(option, option),
        )
    assert duplicate.value.code == "action_administrator_duplicate"

    with pytest.raises(DomainInvariantError) as missing:
        ActionManagementState(
            action=neutral_action(),
            public_alias=None,
            administrator_options=(replace(option, is_responsible=False),),
        )
    assert missing.value.code == "action_responsible_administrator_required"
