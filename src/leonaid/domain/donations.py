"""Donations: money given without anything in return (ADR-0016).

A donation is never a line of an invoice. It has its own number from the
``donation`` series, its own document (the donation pledge,
"Spendenzusage") and one payment. The receiving body is configured once for
the installation in the legal configuration and may be another legal entity
than the invoice issuer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.calendar import local_day
from leonaid.domain.commitments import Money
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware
from leonaid.domain.invoices import (
    BIC,
    IBAN,
    INVOICE_NUMBER,
    NUMBER_PREFIX,
)

MINIMUM_PLEDGE_MINOR = 100
MAXIMUM_PLEDGE_MINOR = 100_000_000
# What a buyer may add to an order as an extra donation (spec §8.6).
ORDER_DONATION_MINIMUM_MINOR = 100
ORDER_DONATION_MAXIMUM_MINOR = 1_000_000
REASON_MINIMUM = 8
TAX_NUMBER = re.compile(r"^[0-9][0-9 /]{5,24}[0-9]$")


def _line(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _required(value: str, *, code: str, label: str, minimum: int, maximum: int) -> str:
    normalized = _line(value) or ""
    if not minimum <= len(normalized) <= maximum:
        raise DomainInvariantError(code, f"{label} fehlt oder ist zu lang.")
    return normalized


def _block(value: str, *, code: str, label: str, minimum: int, maximum: int) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not minimum <= len(text) <= maximum:
        raise DomainInvariantError(code, f"{label} fehlt oder ist zu lang.")
    return text


class ExemptionNoticeKind(StrEnum):
    """The notice the receiving body's tax privilege rests on."""

    FREISTELLUNGSBESCHEID = "freistellungsbescheid"
    KOERPERSCHAFTSTEUER_ANLAGE = "koerperschaftsteuer_anlage"
    FESTSTELLUNG_60A = "feststellung_60a"


# Kinds that name the last assessment period ("Veranlagungszeitraum").
NOTICE_KINDS_WITH_ASSESSMENT_PERIOD = frozenset(
    {
        ExemptionNoticeKind.FREISTELLUNGSBESCHEID,
        ExemptionNoticeKind.KOERPERSCHAFTSTEUER_ANLAGE,
    }
)


class ReceiptSigning(StrEnum):
    BY_HAND = "by_hand"
    # The body notified its tax office of the machine procedure
    # (R 10b.1 Abs. 4 EStR).
    MACHINE = "machine"


@dataclass(frozen=True, slots=True)
class ReceivingBody:
    """The tax-privileged body that receives donations and signs receipts."""

    legal_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    legal_form: str
    tax_office: str
    tax_number: str
    notice_kind: ExemptionNoticeKind
    notice_date: date
    assessment_period_from: int | None
    assessment_period_to: int | None
    purposes: str
    bank_account_holder: str
    iban: str
    bic: str | None
    signatory_name: str
    signatory_function: str
    signing: ReceiptSigning
    machine_notified_on: date | None
    pledge_prefix: str
    receipt_prefix: str
    number_width: int
    # Wording blocks: proposals from the legal templates, "LEGAL REVIEW
    # PENDING" until the club's tax adviser has read them.
    pledge_text: str
    receipt_liability_text: str

    def __post_init__(self) -> None:
        for name, label, minimum, maximum in (
            ("legal_name", "Name der empfangenden Körperschaft", 2, 200),
            ("street_line_1", "Straße der empfangenden Körperschaft", 2, 200),
            ("postal_code", "Postleitzahl der empfangenden Körperschaft", 2, 20),
            ("city", "Ort der empfangenden Körperschaft", 2, 120),
            ("legal_form", "Rechtsform der empfangenden Körperschaft", 2, 80),
            ("tax_office", "Finanzamt", 3, 120),
            ("purposes", "Begünstigte Zwecke", 5, 600),
            ("bank_account_holder", "Kontoinhaber des Spendenkontos", 2, 200),
            ("signatory_name", "Name der unterzeichnenden Person", 3, 120),
            ("signatory_function", "Funktion der unterzeichnenden Person", 2, 120),
        ):
            object.__setattr__(
                self,
                name,
                _required(
                    getattr(self, name),
                    code=f"donation_body_{name}_invalid",
                    label=label,
                    minimum=minimum,
                    maximum=maximum,
                ),
            )
        if not re.fullmatch(r"^[A-Z]{2}$", self.country_code):
            raise DomainInvariantError(
                "donation_body_country_invalid",
                "Der Ländercode der empfangenden Körperschaft muss aus zwei "
                "Großbuchstaben bestehen.",
            )
        tax_number = _line(self.tax_number) or ""
        if TAX_NUMBER.fullmatch(tax_number) is None:
            raise DomainInvariantError(
                "donation_body_tax_number_invalid",
                "Die Steuernummer der empfangenden Körperschaft ist ungültig "
                "(z. B. 123/456/78901).",
            )
        object.__setattr__(self, "tax_number", tax_number)
        needs_period = self.notice_kind in NOTICE_KINDS_WITH_ASSESSMENT_PERIOD
        period = (self.assessment_period_from, self.assessment_period_to)
        if needs_period:
            if (
                period[0] is None
                or period[1] is None
                or not 1990 <= period[0] <= period[1] <= self.notice_date.year
            ):
                raise DomainInvariantError(
                    "donation_body_assessment_period_invalid",
                    "Für diesen Bescheid wird der Veranlagungszeitraum benötigt "
                    "(von Jahr bis Jahr, nicht nach dem Bescheiddatum).",
                )
        elif period != (None, None):
            raise DomainInvariantError(
                "donation_body_assessment_period_forbidden",
                "Ein Feststellungsbescheid nach § 60a AO nennt keinen "
                "Veranlagungszeitraum.",
            )
        iban = "".join(self.iban.split()).upper()
        if IBAN.fullmatch(iban) is None:
            raise DomainInvariantError(
                "donation_body_iban_invalid",
                "Die IBAN des Spendenkontos besitzt kein gültiges Format.",
            )
        object.__setattr__(self, "iban", iban)
        if self.bic is not None:
            bic: str | None = "".join(self.bic.split()).upper()
            if not bic:
                bic = None
            elif BIC.fullmatch(bic) is None:
                raise DomainInvariantError(
                    "donation_body_bic_invalid",
                    "Die BIC des Spendenkontos besitzt kein gültiges Format.",
                )
            object.__setattr__(self, "bic", bic)
        if (self.signing is ReceiptSigning.MACHINE) != (
            self.machine_notified_on is not None
        ):
            raise DomainInvariantError(
                "donation_body_machine_notice_invalid",
                "Das maschinelle Verfahren benötigt das Datum der Anzeige beim "
                "Finanzamt; ohne dieses Verfahren entfällt das Datum.",
            )
        for name, label in (
            ("pledge_prefix", "Spendenzusagen"),
            ("receipt_prefix", "Zuwendungsbestätigungen"),
        ):
            if NUMBER_PREFIX.fullmatch(getattr(self, name)) is None:
                raise DomainInvariantError(
                    "donation_body_prefix_invalid",
                    f"Das Präfix für {label} darf nur Großbuchstaben, Zahlen und "
                    "Bindestriche enthalten.",
                )
        if not 3 <= self.number_width <= 8:
            raise DomainInvariantError(
                "donation_body_number_width_invalid",
                "Spendennummern benötigen drei bis acht Stellen.",
            )
        object.__setattr__(
            self,
            "pledge_text",
            _block(
                self.pledge_text,
                code="donation_body_pledge_text_invalid",
                label="Text der Spendenzusage",
                minimum=40,
                maximum=2_000,
            ),
        )
        object.__setattr__(
            self,
            "receipt_liability_text",
            _block(
                self.receipt_liability_text,
                code="donation_body_receipt_text_invalid",
                label="Haftungshinweis der Zuwendungsbestätigung",
                minimum=40,
                maximum=3_000,
            ),
        )

    def series_prefixes(self) -> tuple[str, str]:
        return self.pledge_prefix, self.receipt_prefix

    def texts(self) -> tuple[str, ...]:
        """Every free text, for the placeholder and synthetic-value checks."""

        return (
            self.legal_name,
            self.street_line_1,
            self.city,
            self.tax_office,
            self.purposes,
            self.bank_account_holder,
            self.signatory_name,
            self.signatory_function,
            self.pledge_text,
            self.receipt_liability_text,
        )

    def payload(self) -> dict[str, object]:
        return {
            "legalName": self.legal_name,
            "streetLine1": self.street_line_1,
            "postalCode": self.postal_code,
            "city": self.city,
            "countryCode": self.country_code,
            "legalForm": self.legal_form,
            "taxOffice": self.tax_office,
            "taxNumber": self.tax_number,
            "noticeKind": self.notice_kind.value,
            "noticeDate": self.notice_date.isoformat(),
            "assessmentPeriodFrom": self.assessment_period_from,
            "assessmentPeriodTo": self.assessment_period_to,
            "purposes": self.purposes,
            "bankAccountHolder": self.bank_account_holder,
            "iban": self.iban,
            "bic": self.bic,
            "signatoryName": self.signatory_name,
            "signatoryFunction": self.signatory_function,
            "signing": self.signing.value,
            "machineNotifiedOn": (
                self.machine_notified_on.isoformat()
                if self.machine_notified_on is not None
                else None
            ),
            "pledgePrefix": self.pledge_prefix,
            "receiptPrefix": self.receipt_prefix,
            "numberWidth": self.number_width,
            "pledgeText": self.pledge_text,
            "receiptLiabilityText": self.receipt_liability_text,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> ReceivingBody:
        def text(key: str) -> str:
            return str(payload[key])

        def optional_int(key: str) -> int | None:
            value = payload.get(key)
            return int(str(value)) if value is not None else None

        notified = payload.get("machineNotifiedOn")
        bic = payload.get("bic")
        return cls(
            legal_name=text("legalName"),
            street_line_1=text("streetLine1"),
            postal_code=text("postalCode"),
            city=text("city"),
            country_code=text("countryCode"),
            legal_form=text("legalForm"),
            tax_office=text("taxOffice"),
            tax_number=text("taxNumber"),
            notice_kind=ExemptionNoticeKind(text("noticeKind")),
            notice_date=date.fromisoformat(text("noticeDate")),
            assessment_period_from=optional_int("assessmentPeriodFrom"),
            assessment_period_to=optional_int("assessmentPeriodTo"),
            purposes=text("purposes"),
            bank_account_holder=text("bankAccountHolder"),
            iban=text("iban"),
            bic=str(bic) if bic is not None else None,
            signatory_name=text("signatoryName"),
            signatory_function=text("signatoryFunction"),
            signing=ReceiptSigning(text("signing")),
            machine_notified_on=(
                date.fromisoformat(str(notified)) if notified is not None else None
            ),
            pledge_prefix=text("pledgePrefix"),
            receipt_prefix=text("receiptPrefix"),
            number_width=int(text("numberWidth")),
            pledge_text=text("pledgeText"),
            receipt_liability_text=text("receiptLiabilityText"),
        )


class DonorPartyKind(StrEnum):
    COMPANY = "company"
    PERSON = "person"


@dataclass(frozen=True, slots=True)
class DonorSnapshot:
    """Who gives: the postal address a receipt needs, frozen at the pledge."""

    name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    email: str | None = None
    party_kind: DonorPartyKind | None = None
    twenty_id: UUID | None = None

    def __post_init__(self) -> None:
        for name, label, minimum, maximum in (
            ("name", "Name des Spenders", 2, 200),
            ("street_line_1", "Straße des Spenders", 2, 200),
            ("postal_code", "Postleitzahl des Spenders", 2, 20),
            ("city", "Ort des Spenders", 2, 120),
        ):
            object.__setattr__(
                self,
                name,
                _required(
                    getattr(self, name),
                    code=f"donation_donor_{name}_invalid",
                    label=label,
                    minimum=minimum,
                    maximum=maximum,
                ),
            )
        if not re.fullmatch(r"^[A-Z]{2}$", self.country_code):
            raise DomainInvariantError(
                "donation_donor_country_invalid",
                "Der Ländercode des Spenders muss aus zwei Großbuchstaben bestehen.",
            )
        if self.email is not None:
            email: str | None = self.email.strip().casefold()
            if not email:
                email = None
            elif email.count("@") != 1 or any(item.isspace() for item in email):
                raise DomainInvariantError(
                    "donation_donor_email_invalid",
                    "Die E-Mail-Adresse des Spenders ist ungültig.",
                )
            object.__setattr__(self, "email", email)
        if (self.party_kind is None) != (self.twenty_id is None):
            raise DomainInvariantError(
                "donation_donor_party_incomplete",
                "Ein CRM-Bezug benötigt Art und ID des Kontakts.",
            )

    def payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "streetLine1": self.street_line_1,
            "postalCode": self.postal_code,
            "city": self.city,
            "countryCode": self.country_code,
            "email": self.email,
            "partyKind": self.party_kind.value if self.party_kind else None,
            "twentyId": str(self.twenty_id) if self.twenty_id else None,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> DonorSnapshot:
        email = payload.get("email")
        kind = payload.get("partyKind")
        twenty_id = payload.get("twentyId")
        return cls(
            name=str(payload["name"]),
            street_line_1=str(payload["streetLine1"]),
            postal_code=str(payload["postalCode"]),
            city=str(payload["city"]),
            country_code=str(payload["countryCode"]),
            email=str(email) if email is not None else None,
            party_kind=DonorPartyKind(str(kind)) if kind is not None else None,
            twenty_id=UUID(str(twenty_id)) if twenty_id is not None else None,
        )


class DonationSource(StrEnum):
    PUBLIC_FORM = "public_form"
    ADMIN = "admin"
    ACQUISITION = "acquisition"


class DonationStatus(StrEnum):
    PLEDGED = "pledged"
    PAID = "paid"
    CANCELLED = "cancelled"


def _reason(value: str, *, code: str, label: str) -> str:
    reason = " ".join(value.split())
    if len(reason) < REASON_MINIMUM:
        raise DomainInvariantError(
            f"{code}_too_short",
            f"{label} muss mindestens acht Zeichen enthalten.",
        )
    if len(reason) > 500:
        raise DomainInvariantError(
            f"{code}_too_long", f"{label} darf höchstens 500 Zeichen enthalten."
        )
    return reason


@dataclass(frozen=True, slots=True)
class DonationPayment:
    """The one payment of a donation: what arrived, and when (D-D7)."""

    amount: Money
    received_on: date
    note: str | None
    recorded_by_user_id: UUID
    recorded_at: datetime
    recorded_by_display_name: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.recorded_at, "recorded_at")
        if self.amount.amount_minor <= 0:
            raise DomainInvariantError(
                "donation_payment_amount_invalid",
                "Der Zahlungseingang muss größer als null sein.",
            )
        note = _line(self.note)
        if note is not None and len(note) > 500:
            raise DomainInvariantError(
                "donation_payment_note_too_long",
                "Die Notiz darf höchstens 500 Zeichen enthalten.",
            )
        object.__setattr__(self, "note", note)


@dataclass(frozen=True, slots=True)
class DonationPaymentWithdrawal:
    """A payment that was taken back, with what it had said."""

    id: UUID
    amount: Money
    received_on: date
    note: str | None
    recorded_by_user_id: UUID
    recorded_at: datetime
    reason: str
    withdrawn_by_user_id: UUID
    withdrawn_at: datetime
    recorded_by_display_name: str | None = None
    withdrawn_by_display_name: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.withdrawn_at, "withdrawn_at")
        object.__setattr__(
            self,
            "reason",
            _reason(
                self.reason,
                code="donation_payment_withdrawal_reason",
                label="Der Grund der Rücknahme",
            ),
        )


@dataclass(frozen=True, slots=True)
class DonationCancellation:
    reason: str
    cancelled_by_user_id: UUID
    cancelled_at: datetime
    cancelled_by_display_name: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.cancelled_at, "cancelled_at")
        object.__setattr__(
            self,
            "reason",
            _reason(
                self.reason,
                code="donation_cancellation_reason",
                label="Der Stornogrund",
            ),
        )


@dataclass(frozen=True, slots=True)
class Donation:
    id: UUID
    action_id: UUID
    number: str
    donor: DonorSnapshot
    pledged: Money
    source: DonationSource
    status: DonationStatus
    pledged_at: datetime
    created_by_user_id: UUID | None
    commitment_id: UUID | None = None
    note: str | None = None
    payment: DonationPayment | None = None
    cancellation: DonationCancellation | None = None
    payment_withdrawals: tuple[DonationPaymentWithdrawal, ...] = ()
    created_by_display_name: str | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        require_aware(self.pledged_at, "pledged_at")
        if not INVOICE_NUMBER.fullmatch(self.number):
            raise DomainInvariantError(
                "donation_number_invalid",
                "Die Spendennummer besitzt ein ungültiges Format.",
            )
        if (
            self.pledged.currency != "EUR"
            or not MINIMUM_PLEDGE_MINOR
            <= self.pledged.amount_minor
            <= MAXIMUM_PLEDGE_MINOR
        ):
            raise DomainInvariantError(
                "donation_amount_invalid",
                "Eine Spende beträgt zwischen 1,00 € und 1.000.000,00 €.",
            )
        note = _line(self.note)
        if note is not None and len(note) > 500:
            raise DomainInvariantError(
                "donation_note_too_long",
                "Die Notiz darf höchstens 500 Zeichen enthalten.",
            )
        object.__setattr__(self, "note", note)
        if (self.status is DonationStatus.PAID) != (self.payment is not None):
            raise DomainInvariantError(
                "donation_payment_state_invalid",
                "Genau eine bezahlte Spende besitzt einen Zahlungseingang.",
            )
        if (self.status is DonationStatus.CANCELLED) != (self.cancellation is not None):
            raise DomainInvariantError(
                "donation_cancellation_state_invalid",
                "Genau eine stornierte Spende besitzt ein Storno.",
            )
        if self.payment is not None and (
            self.payment.amount.currency != self.pledged.currency
        ):
            raise DomainInvariantError(
                "donation_payment_currency_mismatch",
                "Die Zahlungswährung muss der Währung der Spende entsprechen.",
            )

    @classmethod
    def pledge(
        cls,
        *,
        id: UUID,
        action_id: UUID,
        number: str,
        donor: DonorSnapshot,
        pledged: Money,
        source: DonationSource,
        pledged_at: datetime,
        created_by_user_id: UUID | None,
        commitment_id: UUID | None = None,
        note: str | None = None,
    ) -> Donation:
        return cls(
            id=id,
            action_id=action_id,
            number=number,
            donor=donor,
            pledged=pledged,
            source=source,
            status=DonationStatus.PLEDGED,
            pledged_at=pledged_at,
            created_by_user_id=created_by_user_id,
            commitment_id=commitment_id,
            note=note,
        )

    @property
    def received(self) -> Money | None:
        return self.payment.amount if self.payment is not None else None

    def record_payment(
        self,
        *,
        amount: Money,
        received_on: date,
        note: str | None,
        recorded_by_user_id: UUID,
        recorded_at: datetime,
    ) -> Donation:
        """What arrived, once. It may differ from the pledge in either
        direction; the receipt later confirms this amount."""

        if self.status is DonationStatus.CANCELLED:
            raise DomainInvariantError(
                "donation_cancelled",
                "Für eine stornierte Spende kann keine Zahlung erfasst werden.",
            )
        if self.payment is not None:
            raise DomainInvariantError(
                "donation_payment_already_recorded",
                "Für diese Spende ist bereits ein Zahlungseingang erfasst. Eine "
                "zweite Teilzahlung erfassen Sie als eigene Spende.",
            )
        if amount.currency != self.pledged.currency:
            raise DomainInvariantError(
                "donation_payment_currency_mismatch",
                "Die Zahlungswährung muss der Währung der Spende entsprechen.",
            )
        if received_on < local_day(self.pledged_at):
            raise DomainInvariantError(
                "donation_payment_before_pledge",
                "Der Zahlungseingang darf nicht vor der Spendenzusage liegen.",
            )
        if received_on > local_day(recorded_at):
            raise DomainInvariantError(
                "donation_payment_future_date",
                "Ein zukünftiger Zahlungseingang kann nicht erfasst werden.",
            )
        return replace(
            self,
            status=DonationStatus.PAID,
            payment=DonationPayment(
                amount=amount,
                received_on=received_on,
                note=note,
                recorded_by_user_id=recorded_by_user_id,
                recorded_at=recorded_at,
            ),
        )

    def withdraw_payment(
        self,
        *,
        id: UUID,
        reason: str,
        withdrawn_by_user_id: UUID,
        withdrawn_at: datetime,
        has_valid_receipt: bool = False,
    ) -> tuple[Donation, DonationPaymentWithdrawal]:
        """Back to pledged, as long as no valid receipt confirms the money."""

        if self.payment is None:
            raise DomainInvariantError(
                "donation_payment_not_recorded",
                "Für diese Spende ist kein Zahlungseingang erfasst.",
            )
        if has_valid_receipt:
            raise DomainInvariantError(
                "donation_receipt_issued",
                "Für diese Spende ist eine Zuwendungsbestätigung ausgestellt. "
                "Erklären Sie sie zuerst für ungültig.",
            )
        withdrawal = DonationPaymentWithdrawal(
            id=id,
            amount=self.payment.amount,
            received_on=self.payment.received_on,
            note=self.payment.note,
            recorded_by_user_id=self.payment.recorded_by_user_id,
            recorded_at=self.payment.recorded_at,
            reason=reason,
            withdrawn_by_user_id=withdrawn_by_user_id,
            withdrawn_at=withdrawn_at,
        )
        return (
            replace(
                self,
                status=DonationStatus.PLEDGED,
                payment=None,
                payment_withdrawals=(*self.payment_withdrawals, withdrawal),
            ),
            withdrawal,
        )

    def cancel(
        self,
        *,
        reason: str,
        cancelled_by_user_id: UUID,
        cancelled_at: datetime,
    ) -> Donation:
        """Only an unpaid donation is cancelled; received money stays."""

        if self.status is DonationStatus.CANCELLED:
            raise DomainInvariantError(
                "donation_already_cancelled", "Diese Spende ist bereits storniert."
            )
        if self.status is DonationStatus.PAID:
            raise DomainInvariantError(
                "donation_paid",
                "Eine bezahlte Spende kann nicht storniert werden. Nehmen Sie "
                "zuerst die Zahlung zurück, wenn sie irrtümlich erfasst wurde.",
            )
        return replace(
            self,
            status=DonationStatus.CANCELLED,
            cancellation=DonationCancellation(
                reason=reason,
                cancelled_by_user_id=cancelled_by_user_id,
                cancelled_at=cancelled_at,
            ),
        )


DONATION_PLEDGE_DOCUMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class DonationPledgeDocument:
    """The donation pledge ("Spendenzusage"): asks the donor to pay.

    Not an invoice: no tax lines, nothing given in return. It shows the
    receiving body's name, address and bank details, never the invoice
    issuer's. Frozen when the donation gets its number.
    """

    donation_id: UUID
    number: str
    issued_at: datetime
    issued_on: date
    donor: DonorSnapshot
    amount: Money
    action_name: str
    action_purpose: str
    carrier_name: str
    body: ReceivingBody

    def __post_init__(self) -> None:
        require_aware(self.issued_at, "issued_at")
        if not INVOICE_NUMBER.fullmatch(self.number):
            raise DomainInvariantError(
                "donation_number_invalid",
                "Die Spendennummer besitzt ein ungültiges Format.",
            )
        for name in ("action_name", "action_purpose", "carrier_name"):
            if not (_line(getattr(self, name)) or ""):
                raise DomainInvariantError(
                    "donation_pledge_action_incomplete",
                    "Die Spendenzusage benötigt Name, Zweck und Träger der Aktion.",
                )

    @classmethod
    def issue(
        cls,
        donation: Donation,
        *,
        body: ReceivingBody,
        action_name: str,
        action_purpose: str,
        carrier_name: str,
    ) -> DonationPledgeDocument:
        return cls(
            donation_id=donation.id,
            number=donation.number,
            issued_at=donation.pledged_at,
            issued_on=local_day(donation.pledged_at),
            donor=donation.donor,
            amount=donation.pledged,
            action_name=action_name,
            action_purpose=action_purpose,
            carrier_name=carrier_name,
            body=body,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": DONATION_PLEDGE_DOCUMENT_SCHEMA_VERSION,
            "donationId": str(self.donation_id),
            "number": self.number,
            "issuedAt": self.issued_at.isoformat(),
            "issuedOn": self.issued_on.isoformat(),
            "donor": self.donor.payload(),
            "amountMinor": self.amount.amount_minor,
            "currency": self.amount.currency,
            "actionName": self.action_name,
            "actionPurpose": self.action_purpose,
            "carrierName": self.carrier_name,
            "body": self.body.payload(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> DonationPledgeDocument:
        version = payload.get("schemaVersion")
        if version != DONATION_PLEDGE_DOCUMENT_SCHEMA_VERSION:
            raise DomainInvariantError(
                "donation_pledge_document_schema_unsupported",
                f"Dokumentschema {version} wird nicht unterstützt.",
            )
        donor = payload.get("donor")
        body = payload.get("body")
        if not isinstance(donor, dict) or not isinstance(body, dict):
            raise DomainInvariantError(
                "donation_pledge_document_payload_invalid",
                "Der Snapshot der Spendenzusage ist ungültig.",
            )
        return cls(
            donation_id=UUID(str(payload["donationId"])),
            number=str(payload["number"]),
            issued_at=datetime.fromisoformat(str(payload["issuedAt"])),
            issued_on=date.fromisoformat(str(payload["issuedOn"])),
            donor=DonorSnapshot.from_payload(donor),
            amount=Money(int(str(payload["amountMinor"])), str(payload["currency"])),
            action_name=str(payload["actionName"]),
            action_purpose=str(payload["actionPurpose"]),
            carrier_name=str(payload["carrierName"]),
            body=ReceivingBody.from_payload(body),
        )
