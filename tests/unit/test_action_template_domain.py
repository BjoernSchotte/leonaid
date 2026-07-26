from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from uuid import UUID

import pytest

from leonaid.application.actions import CharityActionService
from leonaid.domain.action_templates import (
    ActionConfiguration,
    ActionTemplate,
    ActionTemplateKey,
    ConfiguredOffering,
    OfferingStatus,
    OfferingUnit,
    OrderFormConfiguration,
    TemplateOffering,
)
from leonaid.domain.actions import ActionCapability, CharityAction
from leonaid.domain.errors import DomainInvariantError

ACTION_ID = UUID("20000000-0000-4000-8000-000000000051")
COPY_ID = UUID("20000000-0000-4000-8000-000000000052")


def krapfentaxi_template(
    *,
    version: int = 1,
    price: int = 3600,
) -> ActionTemplate:
    return ActionTemplate(
        key=ActionTemplateKey.KRAPFENTAXI,
        version=version,
        display_name="Krapfentaxi",
        description="Bestellaktion für Krapfenboxen.",
        capabilities=frozenset(ActionCapability),
        offerings=(
            TemplateOffering(
                code="krapfenbox-24",
                name="Krapfenbox",
                status=OfferingStatus.DRAFT,
                unit=OfferingUnit.BOX,
                pieces_per_unit=24,
                unit_price_minor=price,
                currency="EUR",
            ),
        ),
        order_form=OrderFormConfiguration(
            form_key="sponsor-bestellung",
            title="Krapfenboxen bestellen",
            introduction="Unterstützen Sie die Begünstigten.",
            submit_label="Bestellung absenden",
            require_company_name=True,
            require_contact_name=True,
            require_email=True,
            require_phone=False,
            require_delivery_address=True,
            require_billing_address=True,
            allow_message=True,
        ),
    )


def test_template_snapshot_is_detached_from_later_versions() -> None:
    version_one = krapfentaxi_template()
    configured = version_one.configure(ACTION_ID)
    version_two = krapfentaxi_template(version=2, price=4200)

    assert configured.snapshot.template_version == 1
    assert configured.snapshot.offerings[0].unit_price_minor == 3600
    assert version_two.offerings[0].unit_price_minor == 4200
    assert configured.snapshot.payload()["offerings"] == [
        version_one.offerings[0].payload()
    ]


def test_previous_year_copy_rekeys_configuration_without_operational_data() -> None:
    source = krapfentaxi_template().configure(ACTION_ID)
    copied = source.copy_for(
        COPY_ID,
        source_action_id=ACTION_ID,
        capabilities=frozenset(ActionCapability),
    )

    assert copied.action_id == COPY_ID
    assert copied.snapshot.copied_from_action_id == ACTION_ID
    assert copied.snapshot.template_version == 1
    assert copied.offerings[0].id != source.offerings[0].id
    assert copied.offerings[0].action_id == COPY_ID
    assert copied.order_form is not None
    assert source.order_form is not None
    assert copied.order_form.id != source.order_form.id
    assert {field.name for field in fields(ActionConfiguration)} == {
        "action_id",
        "snapshot",
        "offerings",
        "order_form",
    }


def test_template_capability_modules_are_typed_and_consistent() -> None:
    template = krapfentaxi_template()
    with pytest.raises(DomainInvariantError) as captured:
        replace(
            template,
            capabilities=frozenset(
                {
                    ActionCapability.ACQUISITION,
                    ActionCapability.INVOICING,
                }
            ),
        )
    assert captured.value.code == "template_offerings_capability_missing"

    with pytest.raises(DomainInvariantError) as missing_pieces:
        replace(template.offerings[0], pieces_per_unit=None)
    assert missing_pieces.value.code == "template_box_pieces_required"


def test_only_active_configured_offerings_are_public() -> None:
    configured = krapfentaxi_template().configure(ACTION_ID)
    draft = configured.offerings[0]
    active = ConfiguredOffering(
        id=draft.id,
        action_id=draft.action_id,
        definition=replace(draft.definition, status=OfferingStatus.ACTIVE),
        allowed_quantity_units=draft.allowed_quantity_units,
        available_from=draft.available_from,
        available_until=draft.available_until,
    )
    inactive = ConfiguredOffering(
        id=UUID("50000000-0000-4000-8000-000000000052"),
        action_id=ACTION_ID,
        definition=replace(
            draft.definition,
            code="krapfenbox-familie",
            name="Familienbox",
            status=OfferingStatus.INACTIVE,
        ),
        allowed_quantity_units=draft.allowed_quantity_units,
        available_from=draft.available_from,
        available_until=draft.available_until,
    )
    effective = replace(configured, offerings=(active, inactive))

    assert CharityActionService._public_offerings(effective) == (active.definition,)
    assert CharityActionService._public_offerings(None) == ()


def test_krapfentaxi_configuration_does_not_leak_into_charity_action() -> None:
    project_root = Path(__file__).resolve().parents[2]
    action_source = (project_root / "src/leonaid/domain/actions.py").read_text(
        encoding="utf-8"
    )
    template_source = (
        project_root / "src/leonaid/domain/action_templates.py"
    ).read_text(encoding="utf-8")

    assert "krapfen" not in action_source.casefold()
    assert "krapfentaxi" in template_source.casefold()
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
