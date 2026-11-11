"""The donation receipt ("Zuwendungsbestätigung", ADR-0016, spec §8.5).

One receipt per paid donation, for the amount and the day that arrived. A
receipt is never edited: it is declared void, with a reason and with what
happened to the paper the donor holds, and a new one is issued.

The tax points (official sample, § 63 Abs. 5 AO, R 10b.1 Abs. 4 EStR) rest
on the implementation's knowledge; a club has its tax adviser read them
(spec §13, P3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.calendar import local_day
from leonaid.domain.commitments import Money
from leonaid.domain.donations import (
    NOTICE_KINDS_WITH_ASSESSMENT_PERIOD,
    Donation,
    DonationStatus,
    DonorSnapshot,
    ExemptionNoticeKind,
    ReceiptSigning,
    ReceivingBody,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware
from leonaid.domain.invoices import INVOICE_NUMBER

DONATION_RECEIPT_DOCUMENT_SCHEMA_VERSION = 1

# § 63 Abs. 5 AO: a receipt may rest on a Freistellungsbescheid or on the
# Anlage zum Körperschaftsteuerbescheid for five years after its date, on a
# notice after § 60a AO for three.
NOTICE_VALID_YEARS = {
    ExemptionNoticeKind.FREISTELLUNGSBESCHEID: 5,
    ExemptionNoticeKind.KOERPERSCHAFTSTEUER_ANLAGE: 5,
    ExemptionNoticeKind.FESTSTELLUNG_60A: 3,
}

_UNITS = (
    "null",
    "ein",
    "zwei",
    "drei",
    "vier",
    "fünf",
    "sechs",
    "sieben",
    "acht",
    "neun",
    "zehn",
    "elf",
    "zwölf",
    "dreizehn",
    "vierzehn",
    "fünfzehn",
    "sechzehn",
    "siebzehn",
    "achtzehn",
    "neunzehn",
)
_TENS = (
    "",
    "",
    "zwanzig",
    "dreißig",
    "vierzig",
    "fünfzig",
    "sechzig",
    "siebzig",
    "achtzig",
    "neunzig",
)


def _below_thousand(value: int) -> str:
    hundreds, rest = divmod(value, 100)
    words = f"{_UNITS[hundreds]}hundert" if hundreds else ""
    if rest == 0:
        return words
    if rest < 20:
        return words + _UNITS[rest]
    tens, units = divmod(rest, 10)
    if units == 0:
        return words + _TENS[tens]
    return f"{words}{_UNITS[units]}und{_TENS[tens]}"


def number_in_words(value: int) -> str:
    """A whole number from 0 to 999 999 999 in German words.

    "ein" as part of a larger word ("einundzwanzig", "einhundert",
    "eintausend"), "eins" when it stands alone, "eine Million".
    """

    if not 0 <= value <= 999_999_999:
        raise ValueError("Zahlwort nur für 0 bis 999.999.999.")
    if value == 0:
        return "null"
    if value == 1:
        return "eins"
    millions, rest = divmod(value, 1_000_000)
    thousands, below = divmod(rest, 1_000)
    parts: list[str] = []
    if millions == 1:
        parts.append("eine Million")
    elif millions:
        parts.append(f"{_below_thousand(millions)} Millionen")
    tail = ""
    if thousands:
        tail += f"{_below_thousand(thousands)}tausend"
    if below:
        # "eins" only when nothing follows it: 1001 is "eintausendeins".
        tail += (
            _below_thousand(below - 1) + "eins"
            if below % 100 == 1
            else _below_thousand(below)
        )
    if tail:
        parts.append(tail)
    return " ".join(parts)


def amount_in_words(amount: Money) -> str:
    """The amount as the receipt spells it: "fünfzig Euro",
    "ein Euro", "zwölf Euro 50/100". Cents are a fraction of a hundred."""

    if amount.currency != "EUR":
        raise DomainInvariantError(
            "donation_receipt_currency_unsupported",
            "Eine Zuwendungsbestätigung lautet auf Euro.",
        )
    euros, cents = divmod(amount.amount_minor, 100)
    if not 0 <= euros <= 999_999_999:
        raise DomainInvariantError(
            "donation_receipt_amount_unsupported",
            "Der Betrag lässt sich nicht in Worten ausschreiben.",
        )
    words = "ein" if euros == 1 else number_in_words(euros)
    text = f"{words} Euro"
    return f"{text} {cents:02d}/100" if cents else text


def notice_valid_until(body: ReceivingBody) -> date:
    """The last day a receipt may rest on the body's notice (§ 63 Abs. 5 AO)."""

    years = NOTICE_VALID_YEARS[body.notice_kind]
    notice = body.notice_date
    try:
        return notice.replace(year=notice.year + years)
    except ValueError:
        # 29 February: the period ends on 28 February of the last year.
        return notice.replace(year=notice.year + years, day=28)


class ReceiptVoidEvidence(StrEnum):
    """What happened to the paper the donor holds."""

    ORIGINAL_RETURNED = "original_returned"
    TAX_OFFICE_INFORMED = "tax_office_informed"


@dataclass(frozen=True, slots=True)
class DonationReceiptDocument:
    """What the receipt says, frozen when it gets its number.

    Receiving body, donor, the amount that arrived and its day, and the
    wording blocks in force. The PDF is rendered from this alone.
    """

    receipt_id: UUID
    donation_id: UUID
    number: str
    donation_number: str
    issued_at: datetime
    issued_on: date
    donor: DonorSnapshot
    amount: Money
    received_on: date
    body: ReceivingBody

    def __post_init__(self) -> None:
        require_aware(self.issued_at, "issued_at")
        if not INVOICE_NUMBER.fullmatch(self.number):
            raise DomainInvariantError(
                "donation_receipt_number_invalid",
                "Die Nummer der Zuwendungsbestätigung besitzt ein ungültiges Format.",
            )
        if self.amount.amount_minor <= 0:
            raise DomainInvariantError(
                "donation_receipt_amount_invalid",
                "Eine Zuwendungsbestätigung bestätigt einen Betrag über 0,00 €.",
            )
        # Fails early for an amount the words cannot spell.
        amount_in_words(self.amount)
        if self.received_on > self.issued_on:
            raise DomainInvariantError(
                "donation_receipt_before_payment",
                "Die Zuwendungsbestätigung kann nicht vor dem Tag der Zuwendung "
                "ausgestellt werden.",
            )
        if self.issued_on > notice_valid_until(self.body):
            raise DomainInvariantError(
                "donation_receipt_notice_expired",
                "Der Bescheid der empfangenden Körperschaft ist für eine "
                "Zuwendungsbestätigung zu alt (§ 63 Abs. 5 AO).",
            )

    @classmethod
    def issue(
        cls,
        donation: Donation,
        *,
        receipt_id: UUID,
        number: str,
        body: ReceivingBody,
        issued_at: datetime,
    ) -> DonationReceiptDocument:
        """A receipt for a paid donation: what arrived, on the day it arrived."""

        if donation.status is not DonationStatus.PAID or donation.payment is None:
            raise DomainInvariantError(
                "donation_receipt_requires_payment",
                "Eine Zuwendungsbestätigung gibt es erst nach dem Zahlungseingang.",
            )
        return cls(
            receipt_id=receipt_id,
            donation_id=donation.id,
            number=number,
            donation_number=donation.number,
            issued_at=issued_at,
            issued_on=local_day(issued_at),
            donor=donation.donor,
            amount=donation.payment.amount,
            received_on=donation.payment.received_on,
            body=body,
        )

    @property
    def signed_by_machine(self) -> bool:
        return self.body.signing is ReceiptSigning.MACHINE

    def notice_paragraph(self) -> str:
        """The paragraph of the official sample for the body's kind of notice."""

        body = self.body
        notice_date = body.notice_date.strftime("%d.%m.%Y")
        if body.notice_kind in NOTICE_KINDS_WITH_ASSESSMENT_PERIOD:
            source = (
                "dem Freistellungsbescheid"
                if body.notice_kind is ExemptionNoticeKind.FREISTELLUNGSBESCHEID
                else "der Anlage zum Körperschaftsteuerbescheid"
            )
            period = (
                str(body.assessment_period_from)
                if body.assessment_period_from == body.assessment_period_to
                else f"{body.assessment_period_from} bis {body.assessment_period_to}"
            )
            return (
                f"Wir sind wegen {body.purposes} nach {source} des Finanzamtes "
                f"{_office_name(body.tax_office)}, StNr. {body.tax_number}, vom "
                f"{notice_date} für den letzten Veranlagungszeitraum {period} "
                "nach § 5 Abs. 1 Nr. 9 des Körperschaftsteuergesetzes von der "
                "Körperschaftsteuer und nach § 3 Nr. 6 des Gewerbesteuergesetzes "
                "von der Gewerbesteuer befreit."
            )
        return (
            "Die Einhaltung der satzungsmäßigen Voraussetzungen nach den §§ 51, "
            "59, 60 und 61 AO wurde vom Finanzamt "
            f"{_office_name(body.tax_office)}, StNr. {body.tax_number}, mit "
            f"Bescheid vom {notice_date} nach § 60a AO gesondert festgestellt. "
            f"Wir fördern nach unserer Satzung: {body.purposes}."
        )

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": DONATION_RECEIPT_DOCUMENT_SCHEMA_VERSION,
            "receiptId": str(self.receipt_id),
            "donationId": str(self.donation_id),
            "number": self.number,
            "donationNumber": self.donation_number,
            "issuedAt": self.issued_at.isoformat(),
            "issuedOn": self.issued_on.isoformat(),
            "donor": self.donor.payload(),
            "amountMinor": self.amount.amount_minor,
            "currency": self.amount.currency,
            "receivedOn": self.received_on.isoformat(),
            "body": self.body.payload(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> DonationReceiptDocument:
        version = payload.get("schemaVersion")
        if version != DONATION_RECEIPT_DOCUMENT_SCHEMA_VERSION:
            raise DomainInvariantError(
                "donation_receipt_document_schema_unsupported",
                f"Dokumentschema {version} wird nicht unterstützt.",
            )
        donor = payload.get("donor")
        body = payload.get("body")
        if not isinstance(donor, dict) or not isinstance(body, dict):
            raise DomainInvariantError(
                "donation_receipt_document_payload_invalid",
                "Der Snapshot der Zuwendungsbestätigung ist ungültig.",
            )
        return cls(
            receipt_id=UUID(str(payload["receiptId"])),
            donation_id=UUID(str(payload["donationId"])),
            number=str(payload["number"]),
            donation_number=str(payload["donationNumber"]),
            issued_at=datetime.fromisoformat(str(payload["issuedAt"])),
            issued_on=date.fromisoformat(str(payload["issuedOn"])),
            donor=DonorSnapshot.from_payload(donor),
            amount=Money(int(str(payload["amountMinor"])), str(payload["currency"])),
            received_on=date.fromisoformat(str(payload["receivedOn"])),
            body=ReceivingBody.from_payload(body),
        )


def _office_name(tax_office: str) -> str:
    """ "Finanzamt Musterstadt" reads "des Finanzamtes Musterstadt"."""

    prefix = "Finanzamt "
    return tax_office[len(prefix) :] if tax_office.startswith(prefix) else tax_office


def _void_reason(value: str) -> str:
    reason = " ".join(value.split())
    if len(reason) < 8:
        raise DomainInvariantError(
            "donation_receipt_void_reason_too_short",
            "Der Grund muss mindestens 8 Zeichen enthalten.",
        )
    if len(reason) > 500:
        raise DomainInvariantError(
            "donation_receipt_void_reason_too_long",
            "Der Grund darf höchstens 500 Zeichen enthalten.",
        )
    return reason


@dataclass(frozen=True, slots=True)
class DonationReceiptVoid:
    reason: str
    evidence: ReceiptVoidEvidence
    voided_by_user_id: UUID
    voided_at: datetime
    voided_by_display_name: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.voided_at, "voided_at")
        object.__setattr__(self, "reason", _void_reason(self.reason))


@dataclass(frozen=True, slots=True)
class DonationReceipt:
    """An issued receipt and, when it was declared void, why."""

    id: UUID
    donation_id: UUID
    action_id: UUID
    number: str
    # Which receipt of the donation this is (1, 2, ...): the version of its
    # PDF among the donation's receipt documents.
    document_version: int
    document: DonationReceiptDocument
    issued_by_user_id: UUID
    void: DonationReceiptVoid | None = None
    issued_by_display_name: str | None = None

    @property
    def valid(self) -> bool:
        return self.void is None

    def declare_void(
        self,
        *,
        reason: str,
        evidence: ReceiptVoidEvidence,
        voided_by_user_id: UUID,
        voided_at: datetime,
    ) -> DonationReceipt:
        """Void, never edited. The PDF stays stored."""

        if self.void is not None:
            raise DomainInvariantError(
                "donation_receipt_already_void",
                "Diese Zuwendungsbestätigung ist bereits für ungültig erklärt.",
            )
        return DonationReceipt(
            id=self.id,
            donation_id=self.donation_id,
            action_id=self.action_id,
            number=self.number,
            document_version=self.document_version,
            document=self.document,
            issued_by_user_id=self.issued_by_user_id,
            void=DonationReceiptVoid(
                reason=reason,
                evidence=evidence,
                voided_by_user_id=voided_by_user_id,
                voided_at=voided_at,
            ),
            issued_by_display_name=self.issued_by_display_name,
        )


def require_no_valid_receipt(receipts: tuple[DonationReceipt, ...]) -> None:
    """One valid receipt per donation."""

    if any(item.valid for item in receipts):
        raise DomainInvariantError(
            "donation_receipt_already_issued",
            "Für diese Spende gibt es bereits eine gültige "
            "Zuwendungsbestätigung. Erklären Sie sie zuerst für ungültig.",
        )
