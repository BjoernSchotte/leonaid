"""Extra donation with an order (spec §8.6): form flag, amounts, mail."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from leonaid.application.commitments import CommitmentDraft, CommitmentLineDraft
from leonaid.application.order_cancellation import OrderCancellationRequest
from leonaid.application.order_mails import (
    OrderDonationFacts,
    render_order_confirmation,
)
from leonaid.domain.action_templates import OfferingUnit, OrderFormConfiguration
from leonaid.domain.actions import ActionCapability
from leonaid.domain.commitments import (
    BuyerSnapshot,
    CommitmentPartyKind,
    CommitmentSource,
    CommitmentStatus,
    Money,
)
from leonaid.domain.errors import DomainInvariantError
from tests.unit.test_action_template_domain import ACTION_ID, krapfentaxi_template
from tests.unit.test_order_mails import LINKS, facts, legal, order
from tests.unit.test_public_orders import public_order

OFFERING_ID = UUID("70000000-0000-4000-8000-000000000001")
ACTOR_ID = UUID("10000000-0000-4000-8000-000000000002")


def test_the_form_flag_is_off_by_default_and_survives_old_snapshots() -> None:
    form = krapfentaxi_template().order_form
    assert form is not None
    assert form.allow_donation is False
    payload = form.payload()
    assert payload["allowDonation"] is False
    # A snapshot written before the flag existed has no such key.
    del payload["allowDonation"]
    assert OrderFormConfiguration.from_payload(payload).allow_donation is False
    on = replace(form, allow_donation=True)
    assert OrderFormConfiguration.from_payload(on.payload()) == on


def test_the_extra_donation_needs_the_donations_capability() -> None:
    template = krapfentaxi_template()
    assert template.order_form is not None
    with_donation = replace(
        template, order_form=replace(template.order_form, allow_donation=True)
    )
    configured = with_donation.configure(ACTION_ID)
    configured.require_compatible_capabilities(frozenset(ActionCapability))
    without = frozenset(ActionCapability) - {ActionCapability.DONATIONS}
    with pytest.raises(DomainInvariantError) as error:
        configured.require_compatible_capabilities(without)
    assert error.value.code == "order_form_donation_capability_missing"
    # With the switch off the capability may go.
    template.configure(ACTION_ID).require_compatible_capabilities(without)


@pytest.mark.parametrize("amount", (99, 1_000_001))
def test_an_extra_donation_is_between_one_and_ten_thousand_euro(amount: int) -> None:
    with pytest.raises(DomainInvariantError) as error:
        replace(public_order(), donation_amount_minor=amount)
    assert error.value.code == "public_order_donation_amount_invalid"
    with pytest.raises(DomainInvariantError) as error:
        internal_draft(amount)
    assert error.value.code == "commitment_donation_amount_invalid"


def internal_draft(donation: int | None) -> CommitmentDraft:
    return CommitmentDraft(
        buyer=BuyerSnapshot(
            party_kind=CommitmentPartyKind.COMPANY,
            twenty_id=UUID("40000000-0000-4000-8000-000000000001"),
            display_name="Bäckerei Sonnenschein GmbH",
        ),
        invoice_recipient=None,
        lines=(
            CommitmentLineDraft(
                offering_id=OFFERING_ID, quantity=2, unit=OfferingUnit.BOX
            ),
        ),
        donation_amount_minor=donation,
    )


def test_the_donation_amount_is_part_of_the_command_only_when_present() -> None:
    public = public_order()
    arguments = {"action_id": ACTION_ID, "public_alias": "krapfentaxi"}
    without = public.request_hash(**arguments)
    # An absent amount keeps the hash a request had before the field existed.
    assert replace(public, donation_amount_minor=None).request_hash(**arguments) == (
        without
    )
    with_amount = replace(public, donation_amount_minor=2500).request_hash(**arguments)
    assert with_amount != without
    assert (
        replace(public, donation_amount_minor=2600).request_hash(**arguments)
        != with_amount
    )
    for amount in (100, 1_000_000):
        assert replace(public, donation_amount_minor=amount).donation_amount_minor
    hashes = {
        internal_draft(amount).fingerprint(
            action_id=ACTION_ID,
            source=CommitmentSource.ADMIN,
            status=CommitmentStatus.REVIEW_READY,
        )
        for amount in (None, 2500, 2600)
    }
    assert len(hashes) == 3


def test_keeping_the_donation_is_part_of_the_cancellation_command() -> None:
    arguments = {
        "action_id": ACTION_ID,
        "commitment_id": UUID("30000000-0000-4000-8000-0000000000aa"),
        "actor_user_id": ACTOR_ID,
    }
    default = OrderCancellationRequest(
        expected_version="a" * 64, reason="Sponsor hat die Bestellung zurückgezogen"
    )
    assert default.cancel_donation is True
    keep = replace(default, cancel_donation=False)
    # Commands from before the option keep their fingerprint.
    assert default.fingerprint(**arguments) != keep.fingerprint(**arguments)
    assert default.fingerprint(**arguments) == (
        replace(default, cancel_donation=True).fingerprint(**arguments)
    )


def donation_facts() -> OrderDonationFacts:
    return OrderDonationFacts(
        amount=Money(5000, "EUR"),
        number="SP26-0007",
        receiving_body="Förderverein Lions Club Musterstadt e. V.",
    )


def test_the_confirmation_names_the_donation_in_its_own_paragraph() -> None:
    plain = render_order_confirmation(facts(), legal(), LINKS).text
    assert "Ihre Spende" not in plain
    mail = render_order_confirmation(
        replace(facts(), donation=donation_facts()), legal(), LINKS
    ).text
    paragraph = (
        "Ihre Spende\n"
        "Sie haben zusätzlich eine Spende von 50,00 € an Förderverein Lions "
        "Club Musterstadt e. V. zugesagt. Die Spende ist freiwillig, ohne "
        "Gegenleistung und nicht Teil Ihrer Bestellung oder der Rechnung. Die "
        "Spendenzusage SP26-0007 mit der Bankverbindung erhalten Sie in einer "
        "eigenen E-Mail.\n"
    )
    assert paragraph in mail
    # The order itself is unchanged: the donation is no order line.
    assert mail.replace(paragraph + "\n", "") == plain
    # An order a member recorded: the pledge is sent by a manager.
    internal = render_order_confirmation(
        replace(facts(order(source=CommitmentSource.ADMIN)), donation=donation_facts()),
        legal(),
        LINKS,
    ).text
    assert "Spendenzusage SP26-0007 mit der Bankverbindung erhalten Sie gesondert." in (
        internal
    )
