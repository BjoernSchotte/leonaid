"""Donation receipt rules: amount in words, notice age, issue and void."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.commitments import Money
from leonaid.domain.donation_receipts import (
    DonationReceipt,
    DonationReceiptDocument,
    ReceiptVoidEvidence,
    amount_in_words,
    notice_valid_until,
    number_in_words,
    require_no_valid_receipt,
)
from leonaid.domain.donations import ExemptionNoticeKind, ReceiptSigning
from leonaid.domain.errors import DomainInvariantError
from tests.unit.test_donations import PLEDGED_AT, USER_ID, body, paid, pledged

RECEIPT_ID = UUID("d3000000-0000-4000-8000-000000000001")
# The payment of `paid()` arrived on 12 November 2026.
ISSUED_AT = datetime(2026, 12, 10, 9, 0, tzinfo=timezone.utc)


def document(**changes: object) -> DonationReceiptDocument:
    values: dict[str, object] = {
        "receipt_id": RECEIPT_ID,
        "number": "ZB26-0001",
        "body": body(),
        "issued_at": ISSUED_AT,
    }
    values.update(changes)
    donation = values.pop("donation", paid(5000))
    return DonationReceiptDocument.issue(donation, **values)  # type: ignore[arg-type]


def code_of(error: pytest.ExceptionInfo[DomainInvariantError]) -> str:
    return error.value.code


@pytest.mark.parametrize(
    ("value", "words"),
    (
        (0, "null"),
        (1, "eins"),
        (7, "sieben"),
        (10, "zehn"),
        (11, "elf"),
        (12, "zwölf"),
        (16, "sechzehn"),
        (17, "siebzehn"),
        (20, "zwanzig"),
        (21, "einundzwanzig"),
        (30, "dreißig"),
        (66, "sechsundsechzig"),
        (70, "siebzig"),
        (99, "neunundneunzig"),
        (100, "einhundert"),
        (101, "einhunderteins"),
        (111, "einhundertelf"),
        (121, "einhunderteinundzwanzig"),
        (200, "zweihundert"),
        (999, "neunhundertneunundneunzig"),
        (1_000, "eintausend"),
        (1_001, "eintausendeins"),
        (1_100, "eintausendeinhundert"),
        (2_500, "zweitausendfünfhundert"),
        (10_000, "zehntausend"),
        (21_001, "einundzwanzigtausendeins"),
        (100_000, "einhunderttausend"),
        (999_999, "neunhundertneunundneunzigtausendneunhundertneunundneunzig"),
        (1_000_000, "eine Million"),
        (1_000_001, "eine Million eins"),
        (2_000_000, "zwei Millionen"),
        (21_300_000, "einundzwanzig Millionen dreihunderttausend"),
        (
            999_999_999,
            "neunhundertneunundneunzig Millionen "
            "neunhundertneunundneunzigtausendneunhundertneunundneunzig",
        ),
    ),
)
def test_numbers_are_spelled_in_german(value: int, words: str) -> None:
    assert number_in_words(value) == words


@pytest.mark.parametrize("value", (-1, 1_000_000_000))
def test_numbers_outside_the_range_are_refused(value: int) -> None:
    with pytest.raises(ValueError):
        number_in_words(value)


@pytest.mark.parametrize(
    ("minor", "words"),
    (
        (5_000, "fünfzig Euro"),
        (100, "ein Euro"),
        (101, "ein Euro 01/100"),
        (50, "null Euro 50/100"),
        (1_250, "zwölf Euro 50/100"),
        (2_100, "einundzwanzig Euro"),
        (100_100, "eintausendeins Euro"),
        (100_000_000, "eine Million Euro"),
        (
            123_456_789,
            "eine Million zweihundertvierunddreißigtausend"
            "fünfhundertsiebenundsechzig Euro 89/100",
        ),
    ),
)
def test_the_amount_is_spelled_with_cents_as_a_fraction(minor: int, words: str) -> None:
    assert amount_in_words(Money(minor, "EUR")) == words


def test_only_euro_amounts_are_spelled() -> None:
    with pytest.raises(DomainInvariantError) as error:
        amount_in_words(Money(5_000, "CHF"))
    assert code_of(error) == "donation_receipt_currency_unsupported"


@pytest.mark.parametrize(
    ("kind", "notice", "until"),
    (
        (
            ExemptionNoticeKind.FREISTELLUNGSBESCHEID,
            date(2025, 3, 15),
            date(2030, 3, 15),
        ),
        (
            ExemptionNoticeKind.KOERPERSCHAFTSTEUER_ANLAGE,
            date(2025, 3, 15),
            date(2030, 3, 15),
        ),
        (ExemptionNoticeKind.FESTSTELLUNG_60A, date(2025, 3, 15), date(2028, 3, 15)),
        # A notice of 29 February ends on 28 February.
        (ExemptionNoticeKind.FESTSTELLUNG_60A, date(2024, 2, 29), date(2027, 2, 28)),
    ),
)
def test_a_notice_carries_receipts_for_five_or_three_years(
    kind: ExemptionNoticeKind, notice: date, until: date
) -> None:
    with_period = kind is not ExemptionNoticeKind.FESTSTELLUNG_60A
    value = body(
        notice_kind=kind,
        notice_date=notice,
        assessment_period_from=2021 if with_period else None,
        assessment_period_to=2023 if with_period else None,
    )
    assert notice_valid_until(value) == until


def test_a_receipt_confirms_what_arrived_on_the_day_it_arrived() -> None:
    receipt = document(donation=paid(6_000))
    assert receipt.number == "ZB26-0001"
    assert receipt.donation_number == "SP26-0001"
    # Pledged 50,00 €, received 60,00 €: the receipt says 60,00 €.
    assert receipt.amount == Money(6_000, "EUR")
    assert receipt.received_on == date(2026, 11, 12)
    assert receipt.issued_on == date(2026, 12, 10)
    assert receipt.signed_by_machine is True
    assert DonationReceiptDocument.from_payload(receipt.payload()) == receipt


def test_no_receipt_without_a_payment() -> None:
    with pytest.raises(DomainInvariantError) as error:
        document(donation=pledged())
    assert code_of(error) == "donation_receipt_requires_payment"


def test_no_receipt_from_a_notice_that_is_too_old() -> None:
    # Freistellungsbescheid of 15 March 2025: the last day is 15 March 2030.
    last_day = datetime(2030, 3, 15, 10, 0, tzinfo=timezone.utc)
    late = paid().payment
    assert late is not None
    assert document(issued_at=last_day).issued_on == date(2030, 3, 15)
    with pytest.raises(DomainInvariantError) as error:
        document(issued_at=last_day + timedelta(days=1))
    assert code_of(error) == "donation_receipt_notice_expired"
    # After § 60a AO the same notice date carries three years only.
    feststellung = body(
        notice_kind=ExemptionNoticeKind.FESTSTELLUNG_60A,
        assessment_period_from=None,
        assessment_period_to=None,
    )
    with pytest.raises(DomainInvariantError) as error:
        document(
            body=feststellung,
            issued_at=datetime(2028, 3, 16, 10, 0, tzinfo=timezone.utc),
        )
    assert code_of(error) == "donation_receipt_notice_expired"


def test_the_notice_paragraph_follows_the_kind_of_notice() -> None:
    assert document().notice_paragraph() == (
        "Wir sind wegen Förderung der Jugendhilfe, der Bildung und mildtätiger "
        "Zwecke nach dem Freistellungsbescheid des Finanzamtes Musterstadt, "
        "StNr. 123/456/78901, vom 15.03.2025 für den letzten "
        "Veranlagungszeitraum 2021 bis 2023 nach § 5 Abs. 1 Nr. 9 des "
        "Körperschaftsteuergesetzes von der Körperschaftsteuer und nach § 3 "
        "Nr. 6 des Gewerbesteuergesetzes von der Gewerbesteuer befreit."
    )
    anlage = document(
        body=body(
            notice_kind=ExemptionNoticeKind.KOERPERSCHAFTSTEUER_ANLAGE,
            assessment_period_from=2023,
            assessment_period_to=2023,
        )
    ).notice_paragraph()
    assert "nach der Anlage zum Körperschaftsteuerbescheid des Finanzamtes" in anlage
    assert "für den letzten Veranlagungszeitraum 2023 nach § 5" in anlage
    feststellung = document(
        body=body(
            notice_kind=ExemptionNoticeKind.FESTSTELLUNG_60A,
            assessment_period_from=None,
            assessment_period_to=None,
        )
    ).notice_paragraph()
    assert feststellung == (
        "Die Einhaltung der satzungsmäßigen Voraussetzungen nach den §§ 51, 59, "
        "60 und 61 AO wurde vom Finanzamt Musterstadt, StNr. 123/456/78901, mit "
        "Bescheid vom 15.03.2025 nach § 60a AO gesondert festgestellt. Wir "
        "fördern nach unserer Satzung: Förderung der Jugendhilfe, der Bildung "
        "und mildtätiger Zwecke."
    )


def test_a_receipt_signed_by_hand_is_marked_so() -> None:
    by_hand = document(
        body=body(signing=ReceiptSigning.BY_HAND, machine_notified_on=None)
    )
    assert by_hand.signed_by_machine is False


def test_the_snapshot_refuses_unknown_versions() -> None:
    payload = document().payload()
    with pytest.raises(DomainInvariantError) as error:
        DonationReceiptDocument.from_payload({**payload, "schemaVersion": 2})
    assert code_of(error) == "donation_receipt_document_schema_unsupported"
    with pytest.raises(DomainInvariantError) as error:
        DonationReceiptDocument.from_payload({**payload, "donor": None})
    assert code_of(error) == "donation_receipt_document_payload_invalid"


def receipt() -> DonationReceipt:
    value = document()
    return DonationReceipt(
        id=RECEIPT_ID,
        donation_id=value.donation_id,
        action_id=paid().action_id,
        number=value.number,
        document_version=1,
        document=value,
        issued_by_user_id=USER_ID,
    )


def test_a_receipt_is_declared_void_once_with_reason_and_evidence() -> None:
    issued = receipt()
    assert issued.valid
    with pytest.raises(DomainInvariantError) as error:
        require_no_valid_receipt((issued,))
    assert code_of(error) == "donation_receipt_already_issued"
    void = issued.declare_void(
        reason="  Anschrift des Spenders   war falsch ",
        evidence=ReceiptVoidEvidence.ORIGINAL_RETURNED,
        voided_by_user_id=USER_ID,
        voided_at=ISSUED_AT + timedelta(days=2),
    )
    assert not void.valid
    assert void.void is not None
    assert void.void.reason == "Anschrift des Spenders war falsch"
    assert void.void.evidence is ReceiptVoidEvidence.ORIGINAL_RETURNED
    # The document itself is untouched, and a new receipt may follow.
    assert void.document == issued.document
    require_no_valid_receipt((void,))
    with pytest.raises(DomainInvariantError) as error:
        void.declare_void(
            reason="Anschrift des Spenders war falsch",
            evidence=ReceiptVoidEvidence.TAX_OFFICE_INFORMED,
            voided_by_user_id=USER_ID,
            voided_at=ISSUED_AT + timedelta(days=3),
        )
    assert code_of(error) == "donation_receipt_already_void"
    with pytest.raises(DomainInvariantError) as error:
        issued.declare_void(
            reason="kurz",
            evidence=ReceiptVoidEvidence.ORIGINAL_RETURNED,
            voided_by_user_id=USER_ID,
            voided_at=ISSUED_AT + timedelta(days=2),
        )
    assert code_of(error) == "donation_receipt_void_reason_too_short"
    assert PLEDGED_AT < ISSUED_AT
