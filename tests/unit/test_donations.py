"""Donation rules: receiving body, donor, pledge, one payment, cancellation."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.adapters.typst.donation_pledge_renderer import (
    PLEDGE_RENDER_VERSION,
    pledge_render_payload,
)
from leonaid.application.donations import (
    DonationPledgeDeliveryContext,
    pledge_delivery_draft,
)
from leonaid.application.identity import navigation_for
from leonaid.domain.actions import ActionCapability
from leonaid.domain.commitments import Money
from leonaid.domain.documents import GeneratedDocumentType
from leonaid.domain.donations import (
    Donation,
    DonationPledgeDocument,
    DonationSource,
    DonationStatus,
    DonorPartyKind,
    DonorSnapshot,
    ExemptionNoticeKind,
    ReceiptSigning,
    ReceivingBody,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from tests.unit.test_legal_configuration import production_draft, valid_draft

DONATION_ID = UUID("d0000000-0000-4000-8000-000000000001")
ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
USER_ID = UUID("10000000-0000-4000-8000-000000000002")
OTHER_USER_ID = UUID("10000000-0000-4000-8000-000000000003")
# 10 November 2026, 09:00 in Berlin.
PLEDGED_AT = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
PLEDGE_TEXT = (
    "Ihre Spende ist freiwillig. Sie erhalten dafür keine Gegenleistung. "
    "Dieses Schreiben ist keine Rechnung. Nach Eingang Ihrer Zahlung senden "
    "wir Ihnen eine Zuwendungsbestätigung für Ihre Steuererklärung."
)
LIABILITY_TEXT = (
    "Hinweis: Wer vorsätzlich oder grob fahrlässig eine unrichtige "
    "Zuwendungsbestätigung erstellt oder veranlasst, dass Zuwendungen nicht "
    "zu den angegebenen Zwecken verwendet werden, haftet für die entgangene "
    "Steuer."
)


def body(**changes: object) -> ReceivingBody:
    values: dict[str, object] = {
        "legal_name": " Förderverein Lions Club  Musterstadt e. V. ",
        "street_line_1": "Marktplatz 1",
        "postal_code": "12345",
        "city": "Musterstadt",
        "country_code": "DE",
        "legal_form": "registered_association",
        "tax_office": "Finanzamt Musterstadt",
        "tax_number": "123/456/78901",
        "notice_kind": ExemptionNoticeKind.FREISTELLUNGSBESCHEID,
        "notice_date": date(2025, 3, 15),
        "assessment_period_from": 2021,
        "assessment_period_to": 2023,
        "purposes": "Förderung der Jugendhilfe, der Bildung und mildtätiger Zwecke",
        "bank_account_holder": "Förderverein Lions Club Musterstadt e. V.",
        "iban": "de02 1203 0000 0000 2020 51",
        "bic": "byladem1001",
        "signatory_name": "Erika Mustermann",
        "signatory_function": "Schatzmeisterin",
        "signing": ReceiptSigning.MACHINE,
        "machine_notified_on": date(2025, 4, 1),
        "pledge_prefix": "SP26-",
        "receipt_prefix": "ZB26-",
        "number_width": 4,
        "pledge_text": PLEDGE_TEXT,
        "receipt_liability_text": LIABILITY_TEXT,
    }
    values.update(changes)
    return ReceivingBody(**values)  # type: ignore[arg-type]


def donor(**changes: object) -> DonorSnapshot:
    values: dict[str, object] = {
        "name": "Bäckerei Sonnenschein GmbH",
        "street_line_1": "Hauptstraße 5",
        "postal_code": "12345",
        "city": "Musterstadt",
        "country_code": "DE",
        "email": " Kontakt@Sonnenschein.Example ",
        "party_kind": None,
        "twenty_id": None,
    }
    values.update(changes)
    return DonorSnapshot(**values)  # type: ignore[arg-type]


def pledged(**changes: object) -> Donation:
    values: dict[str, object] = {
        "id": DONATION_ID,
        "action_id": ACTION_ID,
        "number": "SP26-0001",
        "donor": donor(),
        "pledged": Money(5000, "EUR"),
        "source": DonationSource.ADMIN,
        "pledged_at": PLEDGED_AT,
        "created_by_user_id": USER_ID,
    }
    values.update(changes)
    return Donation.pledge(**values)  # type: ignore[arg-type]


def paid(amount_minor: int = 5000) -> Donation:
    return pledged().record_payment(
        amount=Money(amount_minor, "EUR"),
        received_on=date(2026, 11, 12),
        note="  Überweisung   Geschäftskonto ",
        recorded_by_user_id=USER_ID,
        recorded_at=PLEDGED_AT + timedelta(days=3),
    )


def code_of(error: pytest.ExceptionInfo[DomainInvariantError]) -> str:
    return error.value.code


# --- receiving body ---------------------------------------------------------


def test_the_receiving_body_is_normalized_and_round_trips() -> None:
    value = body()
    assert value.legal_name == "Förderverein Lions Club Musterstadt e. V."
    assert value.iban == "DE02120300000000202051"
    assert value.bic == "BYLADEM1001"
    assert value.series_prefixes() == ("SP26-", "ZB26-")
    assert ReceivingBody.from_payload(value.payload()) == value
    assert value.payload()["noticeKind"] == "freistellungsbescheid"
    assert value.payload()["machineNotifiedOn"] == "2025-04-01"


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        ({"legal_name": " "}, "donation_body_legal_name_invalid"),
        ({"tax_office": "FA"}, "donation_body_tax_office_invalid"),
        ({"country_code": "de"}, "donation_body_country_invalid"),
        ({"tax_number": "keine"}, "donation_body_tax_number_invalid"),
        ({"iban": "DE02"}, "donation_body_iban_invalid"),
        ({"bic": "X"}, "donation_body_bic_invalid"),
        ({"pledge_prefix": "sp26-"}, "donation_body_prefix_invalid"),
        ({"receipt_prefix": "ZB 26"}, "donation_body_prefix_invalid"),
        ({"number_width": 2}, "donation_body_number_width_invalid"),
        ({"number_width": 9}, "donation_body_number_width_invalid"),
        ({"pledge_text": "Danke."}, "donation_body_pledge_text_invalid"),
        ({"receipt_liability_text": "Hinweis."}, "donation_body_receipt_text_invalid"),
        # A notice with an assessment period: both years, in order, not
        # after the notice.
        ({"assessment_period_from": None}, "donation_body_assessment_period_invalid"),
        (
            {"assessment_period_from": 2023, "assessment_period_to": 2021},
            "donation_body_assessment_period_invalid",
        ),
        ({"assessment_period_to": 2026}, "donation_body_assessment_period_invalid"),
        # § 60a AO states no assessment period.
        (
            {"notice_kind": ExemptionNoticeKind.FESTSTELLUNG_60A},
            "donation_body_assessment_period_forbidden",
        ),
        # The machine procedure and the date of its notice go together.
        ({"machine_notified_on": None}, "donation_body_machine_notice_invalid"),
        ({"signing": ReceiptSigning.BY_HAND}, "donation_body_machine_notice_invalid"),
    ),
)
def test_an_invalid_receiving_body_is_rejected(
    changes: dict[str, object], code: str
) -> None:
    with pytest.raises(DomainInvariantError) as error:
        body(**changes)
    assert code_of(error) == code


def test_a_feststellung_and_a_signature_by_hand_are_valid() -> None:
    value = body(
        notice_kind=ExemptionNoticeKind.FESTSTELLUNG_60A,
        assessment_period_from=None,
        assessment_period_to=None,
        signing=ReceiptSigning.BY_HAND,
        machine_notified_on=None,
        bic="  ",
    )
    assert value.bic is None
    assert ReceivingBody.from_payload(value.payload()) == value


# --- the part "Spenden" of the legal configuration ---------------------------


def test_a_legal_configuration_without_donations_is_complete() -> None:
    assert valid_draft().donations is None
    assert production_draft().activation_blockers(production=True) == ()


def test_the_three_series_need_three_prefixes() -> None:
    draft = replace(valid_draft(), donations=body())
    assert draft.donations is not None
    for changes in (
        {"pledge_prefix": "KT26-"},
        {"receipt_prefix": "KT26-"},
        {"receipt_prefix": "SP26-"},
    ):
        with pytest.raises(DomainInvariantError) as error:
            replace(valid_draft(), donations=body(**changes))
        assert code_of(error) == "legal_number_prefixes_not_distinct"


def test_the_body_takes_a_known_legal_form() -> None:
    with pytest.raises(DomainInvariantError) as error:
        replace(valid_draft(), donations=body(legal_form="verein"))
    assert code_of(error) == "donation_body_legal_form_invalid"


def test_template_placeholders_in_the_body_block_production() -> None:
    clean = replace(production_draft(), donations=body())
    assert clean.activation_blockers(production=True) == ()
    draft = replace(
        production_draft(),
        donations=body(pledge_text=PLEDGE_TEXT + " [[Name des Vereins]]"),
    )
    assert draft.activation_blockers(production=True) == ("template_placeholder_open",)
    assert draft.activation_blockers(production=False) == ()
    synthetic = replace(
        production_draft(), donations=body(legal_name="Golden Förderverein e. V.")
    )
    assert synthetic.activation_blockers(production=True) == (
        "synthetic_or_placeholder_value",
    )


# --- donor -------------------------------------------------------------------


def test_the_donor_is_normalized_and_round_trips() -> None:
    value = donor()
    assert value.email == "kontakt@sonnenschein.example"
    assert DonorSnapshot.from_payload(value.payload()) == value
    linked = donor(
        party_kind=DonorPartyKind.COMPANY,
        twenty_id=UUID("30000000-0000-4000-8000-000000000001"),
        email=None,
    )
    assert DonorSnapshot.from_payload(linked.payload()) == linked


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        ({"name": "A"}, "donation_donor_name_invalid"),
        ({"street_line_1": ""}, "donation_donor_street_line_1_invalid"),
        ({"country_code": "Deutschland"}, "donation_donor_country_invalid"),
        ({"email": "keine-adresse"}, "donation_donor_email_invalid"),
        # A CRM link names kind and id together.
        ({"party_kind": DonorPartyKind.PERSON}, "donation_donor_party_incomplete"),
        (
            {"twenty_id": UUID("30000000-0000-4000-8000-000000000001")},
            "donation_donor_party_incomplete",
        ),
    ),
)
def test_an_invalid_donor_is_rejected(changes: dict[str, object], code: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        donor(**changes)
    assert code_of(error) == code


# --- donation ----------------------------------------------------------------


def test_a_pledge_is_open_and_carries_no_payment() -> None:
    donation = pledged(note="  Barspende   beim Sommerfest ")
    assert donation.status is DonationStatus.PLEDGED
    assert donation.received is None
    assert donation.note == "Barspende beim Sommerfest"


@pytest.mark.parametrize("amount", (99, 100_000_001))
def test_a_donation_is_between_one_euro_and_a_million(amount: int) -> None:
    with pytest.raises(DomainInvariantError) as error:
        pledged(pledged=Money(amount, "EUR"))
    assert code_of(error) == "donation_amount_invalid"
    assert pledged(pledged=Money(100, "EUR")).pledged.amount_minor == 100
    assert pledged(pledged=Money(100_000_000, "EUR")).status is DonationStatus.PLEDGED


def test_a_donation_number_has_the_document_number_format() -> None:
    with pytest.raises(DomainInvariantError) as error:
        pledged(number="sp 1")
    assert code_of(error) == "donation_number_invalid"


@pytest.mark.parametrize("amount", (4000, 5000, 7500))
def test_the_payment_may_differ_from_the_pledge(amount: int) -> None:
    donation = paid(amount)
    assert donation.status is DonationStatus.PAID
    assert donation.pledged == Money(5000, "EUR")
    assert donation.received == Money(amount, "EUR")
    assert donation.payment is not None
    assert donation.payment.note == "Überweisung Geschäftskonto"


def test_a_donation_takes_one_payment() -> None:
    with pytest.raises(DomainInvariantError) as error:
        paid().record_payment(
            amount=Money(1000, "EUR"),
            received_on=date(2026, 11, 13),
            note=None,
            recorded_by_user_id=USER_ID,
            recorded_at=PLEDGED_AT + timedelta(days=4),
        )
    assert code_of(error) == "donation_payment_already_recorded"


@pytest.mark.parametrize(
    ("received_on", "amount", "code"),
    (
        # The pledge was made on 10 November, the payment is recorded on 13.
        (date(2026, 11, 9), Money(5000, "EUR"), "donation_payment_before_pledge"),
        (date(2026, 11, 14), Money(5000, "EUR"), "donation_payment_future_date"),
        (date(2026, 11, 12), Money(5000, "CHF"), "donation_payment_currency_mismatch"),
        (date(2026, 11, 12), Money(0, "EUR"), "donation_payment_amount_invalid"),
    ),
)
def test_an_invalid_payment_is_rejected(
    received_on: date, amount: Money, code: str
) -> None:
    with pytest.raises(DomainInvariantError) as error:
        pledged().record_payment(
            amount=amount,
            received_on=received_on,
            note=None,
            recorded_by_user_id=USER_ID,
            recorded_at=PLEDGED_AT + timedelta(days=3),
        )
    assert code_of(error) == code


def test_the_pledge_day_and_today_are_valid_payment_days() -> None:
    for received_on in (date(2026, 11, 10), date(2026, 11, 13)):
        donation = pledged().record_payment(
            amount=Money(5000, "EUR"),
            received_on=received_on,
            note=None,
            recorded_by_user_id=USER_ID,
            recorded_at=PLEDGED_AT + timedelta(days=3),
        )
        assert donation.status is DonationStatus.PAID


def test_withdrawing_a_payment_keeps_what_was_recorded() -> None:
    withdrawn_at = PLEDGED_AT + timedelta(days=5)
    donation, withdrawal = paid(6000).withdraw_payment(
        id=UUID("d1000000-0000-4000-8000-000000000001"),
        reason="  Zahlung gehörte   zu einer anderen Spende ",
        withdrawn_by_user_id=OTHER_USER_ID,
        withdrawn_at=withdrawn_at,
    )
    assert donation.status is DonationStatus.PLEDGED
    assert donation.payment is None
    assert donation.payment_withdrawals == (withdrawal,)
    assert withdrawal.amount == Money(6000, "EUR")
    assert withdrawal.received_on == date(2026, 11, 12)
    assert withdrawal.recorded_by_user_id == USER_ID
    assert withdrawal.withdrawn_by_user_id == OTHER_USER_ID
    assert withdrawal.reason == "Zahlung gehörte zu einer anderen Spende"
    # It can be paid again, and the history stays.
    again = donation.record_payment(
        amount=Money(5000, "EUR"),
        received_on=date(2026, 11, 15),
        note=None,
        recorded_by_user_id=USER_ID,
        recorded_at=withdrawn_at,
    )
    assert again.status is DonationStatus.PAID
    assert again.payment_withdrawals == (withdrawal,)


@pytest.mark.parametrize(
    ("donation", "reason", "receipt", "code"),
    (
        (pledged(), "Zahlung war ein Irrtum", False, "donation_payment_not_recorded"),
        (paid(), "zu kurz", False, "donation_payment_withdrawal_reason_too_short"),
        (paid(), "x" * 501, False, "donation_payment_withdrawal_reason_too_long"),
        # A valid receipt confirms the money: it goes first (stage 5).
        (paid(), "Zahlung war ein Irrtum", True, "donation_receipt_issued"),
    ),
)
def test_a_payment_withdrawal_needs_a_payment_and_a_reason(
    donation: Donation, reason: str, receipt: bool, code: str
) -> None:
    with pytest.raises(DomainInvariantError) as error:
        donation.withdraw_payment(
            id=UUID("d1000000-0000-4000-8000-000000000002"),
            reason=reason,
            withdrawn_by_user_id=USER_ID,
            withdrawn_at=PLEDGED_AT + timedelta(days=5),
            has_valid_receipt=receipt,
        )
    assert code_of(error) == code


def test_only_an_unpaid_donation_is_cancelled() -> None:
    cancelled_at = PLEDGED_AT + timedelta(days=1)
    cancelled = pledged().cancel(
        reason="Spender hat die Zusage zurückgezogen",
        cancelled_by_user_id=USER_ID,
        cancelled_at=cancelled_at,
    )
    assert cancelled.status is DonationStatus.CANCELLED
    assert cancelled.number == "SP26-0001"
    assert cancelled.cancellation is not None
    assert cancelled.cancellation.cancelled_at == cancelled_at
    for donation, reason, code in (
        (paid(), "Spender hat die Zusage zurückgezogen", "donation_paid"),
        (
            cancelled,
            "Spender hat die Zusage zurückgezogen",
            "donation_already_cancelled",
        ),
        (pledged(), "kurz", "donation_cancellation_reason_too_short"),
    ):
        with pytest.raises(DomainInvariantError) as error:
            donation.cancel(
                reason=reason, cancelled_by_user_id=USER_ID, cancelled_at=cancelled_at
            )
        assert code_of(error) == code
    with pytest.raises(DomainInvariantError) as error:
        cancelled.record_payment(
            amount=Money(5000, "EUR"),
            received_on=date(2026, 11, 12),
            note=None,
            recorded_by_user_id=USER_ID,
            recorded_at=PLEDGED_AT + timedelta(days=3),
        )
    assert code_of(error) == "donation_cancelled"


def test_status_and_payment_or_cancellation_belong_together() -> None:
    with pytest.raises(DomainInvariantError) as error:
        replace(pledged(), status=DonationStatus.PAID)
    assert code_of(error) == "donation_payment_state_invalid"
    with pytest.raises(DomainInvariantError) as error:
        replace(pledged(), status=DonationStatus.CANCELLED)
    assert code_of(error) == "donation_cancellation_state_invalid"


# --- pledge document ---------------------------------------------------------


def pledge_document() -> DonationPledgeDocument:
    return DonationPledgeDocument.issue(
        pledged(),
        body=body(),
        action_name="Krapfentaxi 2026",
        action_purpose="Erlös für die Jugendarbeit im Ort",
        carrier_name="Lions Club Musterstadt",
    )


def test_the_pledge_document_freezes_the_day_and_round_trips() -> None:
    document = pledge_document()
    assert document.issued_on == date(2026, 11, 10)
    assert document.amount == Money(5000, "EUR")
    assert DonationPledgeDocument.from_payload(document.payload()) == document
    # A pledge late in the evening in UTC is the next day in Berlin.
    late = DonationPledgeDocument.issue(
        pledged(pledged_at=datetime(2026, 11, 10, 23, 30, tzinfo=timezone.utc)),
        body=body(),
        action_name="Krapfentaxi 2026",
        action_purpose="Erlös für die Jugendarbeit im Ort",
        carrier_name="Lions Club Musterstadt",
    )
    assert late.issued_on == date(2026, 11, 11)


def test_the_pledge_document_refuses_unknown_snapshots() -> None:
    payload = pledge_document().payload()
    with pytest.raises(DomainInvariantError) as error:
        DonationPledgeDocument.from_payload({**payload, "schemaVersion": 2})
    assert code_of(error) == "donation_pledge_document_schema_unsupported"
    with pytest.raises(DomainInvariantError) as error:
        DonationPledgeDocument.from_payload({**payload, "body": None})
    assert code_of(error) == "donation_pledge_document_payload_invalid"
    with pytest.raises(DomainInvariantError) as error:
        DonationPledgeDocument.issue(
            pledged(),
            body=body(),
            action_name="Krapfentaxi 2026",
            action_purpose=" ",
            carrier_name="Lions Club Musterstadt",
        )
    assert code_of(error) == "donation_pledge_action_incomplete"


def test_the_pledge_pdf_shows_the_receiving_body_and_is_no_invoice() -> None:
    payload = pledge_render_payload(pledge_document())
    assert payload["renderVersion"] == PLEDGE_RENDER_VERSION
    assert payload["title"] == "Spendenzusage SP26-0001"
    assert payload["issuedOn"] == "10.11.2026"
    assert payload["amount"] == "50,00 €"
    assert payload["thanks"] == (
        "Vielen Dank für Ihre Spende von 50,00 € für die Aktion "
        "„Krapfentaxi 2026“ (Lions Club Musterstadt)."
    )
    assert payload["notice"] == PLEDGE_TEXT
    assert payload["bank"] == {
        "accountHolder": "Förderverein Lions Club Musterstadt e. V.",
        "iban": "DE02 1203 0000 0000 2020 51",
        "bic": "BYLADEM1001",
        "reference": "SP26-0001",
    }
    body_block = payload["body"]
    assert isinstance(body_block, dict)
    assert body_block["legalName"] == "Förderverein Lions Club Musterstadt e. V."
    assert body_block["taxNumber"] == "123/456/78901"
    # No tax line and no invoice wording besides the body's own notice.
    assert not {"lines", "tax", "taxNote", "totals", "dueOn"} & set(payload)
    without_notice = {key: value for key, value in payload.items() if key != "notice"}
    assert "Rechnung" not in str(without_notice)
    assert "Umsatzsteuer" not in str(payload)


def test_the_pledge_mail_names_number_amount_and_body() -> None:
    draft = pledge_delivery_draft(
        DonationPledgeDeliveryContext(
            action_id=ACTION_ID,
            action_name="Krapfentaxi 2026",
            donation_id=DONATION_ID,
            number="SP26-0001",
            document_id=UUID("d2000000-0000-4000-8000-000000000001"),
            donor_name="Bäckerei Sonnenschein GmbH",
            donor_email="kontakt@sonnenschein.example",
            body_name="Förderverein Lions Club Musterstadt e. V.",
            amount_minor=5000,
            currency="EUR",
        ),
        idempotency_key="donation-pledge:0001",
        requested_by_user_id=USER_ID,
        requested_at=PLEDGED_AT,
    )
    assert draft.subject == "Spendenzusage SP26-0001 · Krapfentaxi 2026"
    assert draft.recipient_email == "kontakt@sonnenschein.example"
    assert "Guten Tag Bäckerei Sonnenschein GmbH," in draft.text
    assert "50,00 €" in draft.text
    assert "Verwendungszweck SP26-0001" in draft.text
    assert "Dieses Schreiben ist keine Rechnung." in draft.text
    assert draft.text.endswith("Förderverein Lions Club Musterstadt e. V.")
    # The same donation and key give the same command, whoever asks when.
    again = pledge_delivery_draft(
        DonationPledgeDeliveryContext(
            action_id=ACTION_ID,
            action_name="Krapfentaxi 2026",
            donation_id=DONATION_ID,
            number="SP26-0001",
            document_id=UUID("d2000000-0000-4000-8000-000000000001"),
            donor_name="Bäckerei Sonnenschein GmbH",
            donor_email="kontakt@sonnenschein.example",
            body_name="Förderverein Lions Club Musterstadt e. V.",
            amount_minor=5000,
            currency="EUR",
        ),
        idempotency_key="donation-pledge:0001",
        requested_by_user_id=OTHER_USER_ID,
        requested_at=PLEDGED_AT + timedelta(hours=1),
    )
    assert again.request_hash == draft.request_hash
    assert again.id != draft.id


# --- capability, document type, navigation -----------------------------------


def test_donations_is_a_capability_without_a_dependency() -> None:
    assert ActionCapability("donations") is ActionCapability.DONATIONS
    assert GeneratedDocumentType("donation_pledge_pdf") is (
        GeneratedDocumentType.DONATION_PLEDGE_PDF
    )


@pytest.mark.parametrize("donations", (True, False))
def test_the_navigation_shows_spenden_only_with_the_flag(donations: bool) -> None:
    principal = IdentityPrincipal(
        account=UserAccount(
            id=USER_ID,
            email="klara@example.test",
            display_name="Klara",
            status=AccountStatus.ACTIVE,
        ),
        global_roles=frozenset(),
        action_memberships=(),
    )
    items = [
        item
        for item in navigation_for(principal, donations=donations)
        if item.key == "donations"
    ]
    assert len(items) == int(donations)
    if items:
        assert (items[0].label, items[0].surface, items[0].href) == (
            "Spenden",
            "web",
            "/admin/donations",
        )
