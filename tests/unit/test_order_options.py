"""Order options (E-068): delivery area, form consents, offering edits."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from leonaid.domain.action_templates import (
    ConfiguredOffering,
    OfferingStatus,
    OfferingUnit,
    OrderFormConfiguration,
    TemplateOffering,
    consent_text_version,
)
from leonaid.domain.actions import ActionCapability
from leonaid.domain.delivery import DeliveryConfiguration
from leonaid.domain.errors import DomainInvariantError
from tests.unit.test_action_template_domain import ACTION_ID, krapfentaxi_template
from tests.unit.test_public_orders import public_order

CODES = frozenset({"97070", "97 080", "97299"})


def test_the_delivery_area_normalizes_codes_and_allows_all_when_empty() -> None:
    area = DeliveryConfiguration(
        action_id=ACTION_ID,
        postal_codes=CODES,
        area_label="  Stadt und Landkreis Würzburg ",
    )
    assert area.postal_codes == frozenset({"97070", "97080", "97299"})
    assert area.area_label == "Stadt und Landkreis Würzburg"
    assert area.delivers_to("97 070")
    assert not area.delivers_to("86150")
    assert DeliveryConfiguration(action_id=ACTION_ID).delivers_to("86150")


def test_an_address_outside_the_area_names_the_area() -> None:
    area = DeliveryConfiguration(
        action_id=ACTION_ID, postal_codes=CODES, area_label="Würzburg"
    )
    area.require_delivery_area("97299")
    with pytest.raises(DomainInvariantError) as error:
        area.require_delivery_area("86150")
    assert error.value.code == "delivery_postal_code_outside_area"
    assert "(Würzburg)" in error.value.message


@pytest.mark.parametrize("code", ["12", "97070!", "1234567890A"])
def test_an_invalid_postal_code_is_refused(code: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        DeliveryConfiguration(action_id=ACTION_ID, postal_codes=frozenset({code}))
    assert error.value.code == "delivery_postal_code_invalid"


def test_a_multiline_area_label_is_refused() -> None:
    with pytest.raises(DomainInvariantError) as error:
        DeliveryConfiguration(action_id=ACTION_ID, area_label="Stadt\nLand")
    assert error.value.code == "delivery_area_label_invalid"


def test_form_options_are_trimmed_and_left_out_of_old_snapshots() -> None:
    form = krapfentaxi_template().order_form
    assert form is not None
    # Unset options keep the snapshot byte-identical.
    assert "newsletterConsentText" not in form.payload()
    with_options = replace(
        form,
        newsletter_consent_text="  Ja, informieren Sie mich per E-Mail.  ",
        photo_consent_text="Fotos der Lieferung dürfen veröffentlicht werden.",
        withdrawal_notice="",
    )
    assert with_options.newsletter_consent_text == (
        "Ja, informieren Sie mich per E-Mail."
    )
    assert with_options.withdrawal_notice is None
    assert OrderFormConfiguration.from_payload(with_options.payload()) == (with_options)
    with pytest.raises(DomainInvariantError) as error:
        replace(form, photo_consent_text="Ja.")
    assert error.value.code == "order_form_photo_consent_text_invalid"


def test_the_consent_version_names_the_wording() -> None:
    first = consent_text_version("newsletter", "Ja, bitte informieren.")
    assert first.startswith("newsletter-") and len(first) == len("newsletter-") + 16
    assert first == consent_text_version("newsletter", "Ja, bitte informieren.")
    assert first != consent_text_version("newsletter", "Ja, bitte informieren!")


def test_consents_enter_the_order_hash_only_when_given() -> None:
    order = public_order()
    plain = order.request_hash(action_id=ACTION_ID, public_alias="krapfentaxi")
    # An order without the new fields keeps its pre-upgrade hash.
    assert plain == replace(order, newsletter_consent=False).request_hash(
        action_id=ACTION_ID, public_alias="krapfentaxi"
    )
    assert plain != replace(order, newsletter_consent=True).request_hash(
        action_id=ACTION_ID, public_alias="krapfentaxi"
    )
    assert plain != replace(order, photo_consent=True).request_hash(
        action_id=ACTION_ID, public_alias="krapfentaxi"
    )


def offering(code: str, name: str, pieces: int, price: int) -> ConfiguredOffering:
    deadline = datetime(2027, 2, 2, 16, tzinfo=timezone.utc)
    return ConfiguredOffering(
        id=UUID(int=pieces),
        action_id=ACTION_ID,
        definition=TemplateOffering(
            code=code,
            name=name,
            status=OfferingStatus.ACTIVE,
            unit=OfferingUnit.BOX,
            pieces_per_unit=pieces,
            unit_price_minor=price,
            currency="EUR",
        ),
        allowed_quantity_units=frozenset({OfferingUnit.BOX}),
        available_from=datetime(2026, 11, 16, tzinfo=timezone.utc),
        available_until=deadline,
    )


def test_offerings_are_replaced_with_unique_names() -> None:
    configuration = krapfentaxi_template().configure(ACTION_ID)
    sizes = (
        offering("krapfenbox-10", "Krapfenbox 10 Stück", 10, 2_000),
        offering("krapfenbox-20", "Krapfenbox 20 Stück", 20, 4_000),
    )
    replaced = configuration.with_offerings(sizes, frozenset(ActionCapability))
    assert replaced.offerings == sizes
    twin = replace(
        sizes[1],
        definition=replace(sizes[1].definition, name="krapfenbox 10 stück"),
    )
    with pytest.raises(DomainInvariantError) as error:
        configuration.with_offerings((sizes[0], twin), frozenset(ActionCapability))
    assert error.value.code == "offering_name_duplicate"
    with pytest.raises(DomainInvariantError) as error:
        configuration.with_offerings(
            sizes, frozenset(ActionCapability) - {ActionCapability.OFFERINGS}
        )
    assert error.value.code == "template_offerings_capability_missing"


def test_an_offering_outside_its_period_is_not_offered() -> None:
    box = offering("krapfenbox-10", "Krapfenbox 10 Stück", 10, 2_000)
    assert box.available_at(datetime(2027, 2, 2, 15, 59, tzinfo=timezone.utc))
    assert not box.available_at(datetime(2027, 2, 2, 16, tzinfo=timezone.utc))


def test_the_donation_share_is_at_most_the_price() -> None:
    box = offering("krapfenbox-10", "Krapfenbox 10 Stück", 10, 2_000).definition
    shared = replace(box, donation_share_minor=1_000)
    assert TemplateOffering.from_payload(shared.payload()) == shared
    assert "donationShareMinor" not in box.payload()
    with pytest.raises(DomainInvariantError) as error:
        replace(box, donation_share_minor=2_001)
    assert error.value.code == "offering_donation_share_invalid"
