"""Immutable invoice snapshots and issuing rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    Commitment,
    CommitmentStatus,
    InvoiceRecipientSnapshot,
    Money,
)
from leonaid.domain.errors import DomainInvariantError

INVOICE_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")
NUMBER_PREFIX = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,23}$")
TAX_IDENTIFIER = re.compile(r"^[A-Z0-9 /.-]{3,32}$")
IBAN = re.compile(r"^[A-Z]{2}[0-9A-Z]{13,32}$")
BIC = re.compile(r"^[A-Z0-9]{8}(?:[A-Z0-9]{3})?$")


class TaxTreatment(StrEnum):
    STANDARD_VAT = "standard_vat"
    SMALL_BUSINESS = "small_business"
    TAX_EXEMPT = "tax_exempt"


class InvoiceStatus(StrEnum):
    ISSUED = "issued"
    SENT = "sent"
    PAID = "paid"
    CANCELLED = "cancelled"


ALLOWED_INVOICE_TRANSITIONS: dict[InvoiceStatus, frozenset[InvoiceStatus]] = {
    InvoiceStatus.ISSUED: frozenset(
        {InvoiceStatus.SENT, InvoiceStatus.PAID, InvoiceStatus.CANCELLED}
    ),
    InvoiceStatus.SENT: frozenset({InvoiceStatus.PAID, InvoiceStatus.CANCELLED}),
    InvoiceStatus.PAID: frozenset({InvoiceStatus.CANCELLED}),
    InvoiceStatus.CANCELLED: frozenset(),
}


def _required(value: str, *, code: str, label: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainInvariantError(code, f"{label} darf nicht leer sein.")
    return normalized


def _payload_integer(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise DomainInvariantError(
            "invoice_snapshot_integer_invalid",
            "Der gespeicherte Rechnungssnapshot enthält keine gültige Ganzzahl.",
        )
    try:
        return int(value)
    except ValueError as error:
        raise DomainInvariantError(
            "invoice_snapshot_integer_invalid",
            "Der gespeicherte Rechnungssnapshot enthält keine gültige Ganzzahl.",
        ) from error


@dataclass(frozen=True, slots=True)
class InvoiceIssuerSnapshot:
    legal_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str
    tax_identifier: str
    email: str

    def __post_init__(self) -> None:
        for field, code, label in (
            ("legal_name", "invoice_issuer_name_empty", "Name des Trägers"),
            ("street_line_1", "invoice_issuer_street_empty", "Straße des Trägers"),
            ("postal_code", "invoice_issuer_postal_empty", "Postleitzahl des Trägers"),
            ("city", "invoice_issuer_city_empty", "Ort des Trägers"),
        ):
            object.__setattr__(
                self,
                field,
                _required(getattr(self, field), code=code, label=label),
            )
        if not re.fullmatch(r"^[A-Z]{2}$", self.country_code):
            raise DomainInvariantError(
                "invoice_issuer_country_invalid",
                "Der Ländercode des Trägers muss aus zwei Großbuchstaben bestehen.",
            )
        if not TAX_IDENTIFIER.fullmatch(self.tax_identifier):
            raise DomainInvariantError(
                "invoice_issuer_tax_identifier_invalid",
                "Die Steuernummer oder Umsatzsteuer-ID besitzt ein ungültiges Format.",
            )
        if (
            self.email != self.email.casefold()
            or self.email.count("@") != 1
            or any(character.isspace() for character in self.email)
        ):
            raise DomainInvariantError(
                "invoice_issuer_email_invalid",
                "Die E-Mail des Rechnungsausstellers ist ungültig.",
            )

    def payload(self) -> dict[str, str]:
        return {
            "legalName": self.legal_name,
            "streetLine1": self.street_line_1,
            "postalCode": self.postal_code,
            "city": self.city,
            "countryCode": self.country_code,
            "taxIdentifier": self.tax_identifier,
            "email": self.email,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> InvoiceIssuerSnapshot:
        return cls(
            legal_name=str(payload["legalName"]),
            street_line_1=str(payload["streetLine1"]),
            postal_code=str(payload["postalCode"]),
            city=str(payload["city"]),
            country_code=str(payload["countryCode"]),
            tax_identifier=str(payload["taxIdentifier"]),
            email=str(payload["email"]),
        )


@dataclass(frozen=True, slots=True)
class InvoicePaymentDetailsSnapshot:
    account_holder: str
    iban: str
    bic: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_holder",
            _required(
                self.account_holder,
                code="invoice_payment_account_holder_empty",
                label="Kontoinhaber",
            ),
        )
        normalized_iban = "".join(self.iban.split()).upper()
        if IBAN.fullmatch(normalized_iban) is None:
            raise DomainInvariantError(
                "invoice_payment_iban_invalid",
                "Die IBAN besitzt kein gültiges Format.",
            )
        object.__setattr__(self, "iban", normalized_iban)
        if self.bic is not None:
            normalized_bic = "".join(self.bic.split()).upper()
            if BIC.fullmatch(normalized_bic) is None:
                raise DomainInvariantError(
                    "invoice_payment_bic_invalid",
                    "Die BIC besitzt kein gültiges Format.",
                )
            object.__setattr__(self, "bic", normalized_bic)

    def payload(self) -> dict[str, str | None]:
        return {
            "accountHolder": self.account_holder,
            "iban": self.iban,
            "bic": self.bic,
        }

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
    ) -> InvoicePaymentDetailsSnapshot:
        bic = payload.get("bic")
        return cls(
            account_holder=str(payload["accountHolder"]),
            iban=str(payload["iban"]),
            bic=str(bic) if bic is not None else None,
        )


@dataclass(frozen=True, slots=True)
class InvoiceProfile:
    id: UUID
    action_id: UUID
    issuer: InvoiceIssuerSnapshot
    tax_treatment: TaxTreatment
    tax_rate_basis_points: int
    tax_note: str
    number_prefix: str
    next_number: int
    number_width: int
    payment_terms_days: int
    confirmed_at: datetime | None
    legal_configuration_version_id: UUID | None = None
    payment_details: InvoicePaymentDetailsSnapshot | None = None

    def __post_init__(self) -> None:
        if self.tax_treatment is TaxTreatment.STANDARD_VAT:
            if not 1 <= self.tax_rate_basis_points <= 10_000:
                raise DomainInvariantError(
                    "invoice_tax_rate_required",
                    "Regelbesteuerung benötigt einen Steuersatz.",
                )
        elif self.tax_rate_basis_points != 0:
            raise DomainInvariantError(
                "invoice_tax_rate_forbidden",
                "Ohne Umsatzsteuerausweis muss der Steuersatz null sein.",
            )
        object.__setattr__(
            self,
            "tax_note",
            _required(
                self.tax_note,
                code="invoice_tax_note_empty",
                label="Steuerhinweis",
            ),
        )
        if not NUMBER_PREFIX.fullmatch(self.number_prefix):
            raise DomainInvariantError(
                "invoice_number_prefix_invalid",
                "Das Rechnungspräfix darf nur Großbuchstaben, Zahlen und Bindestriche enthalten.",
            )
        if self.next_number <= 0 or not 3 <= self.number_width <= 8:
            raise DomainInvariantError(
                "invoice_sequence_invalid",
                "Der Nummernkreis benötigt eine positive Nummer und drei bis acht Stellen.",
            )
        if not 1 <= self.payment_terms_days <= 120:
            raise DomainInvariantError(
                "invoice_payment_terms_invalid",
                "Das Zahlungsziel muss zwischen einem und 120 Tagen liegen.",
            )
        if self.confirmed_at is not None and (
            self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None
        ):
            raise DomainInvariantError(
                "invoice_profile_confirmation_timezone_required",
                "Die fachliche Bestätigung benötigt eine eindeutige Zeitzone.",
            )

    @property
    def next_invoice_number(self) -> str:
        return f"{self.number_prefix}{self.next_number:0{self.number_width}d}"

    @property
    def ready_to_issue(self) -> bool:
        return (
            self.confirmed_at is not None
            and self.legal_configuration_version_id is not None
            and self.payment_details is not None
        )


@dataclass(frozen=True, slots=True)
class InvoiceLineSnapshot:
    description: str
    quantity: int
    unit: OfferingUnit
    unit_price_gross: Money
    tax_rate_basis_points: int
    net: Money
    tax: Money
    gross: Money

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "description",
            _required(
                self.description,
                code="invoice_line_description_empty",
                label="Positionsbeschreibung",
            ),
        )
        if self.quantity <= 0 or isinstance(self.quantity, bool):
            raise DomainInvariantError(
                "invoice_line_quantity_invalid",
                "Eine Rechnungsposition benötigt eine positive Menge.",
            )
        if not 0 <= self.tax_rate_basis_points <= 10_000:
            raise DomainInvariantError(
                "invoice_line_tax_rate_invalid",
                "Der Steuersatz der Rechnungsposition ist ungültig.",
            )
        if self.gross != self.unit_price_gross.multiply(self.quantity):
            raise DomainInvariantError(
                "invoice_line_gross_invalid",
                "Der Bruttobetrag muss aus Menge und Preis entstehen.",
            )
        if self.net.plus(self.tax) != self.gross:
            raise DomainInvariantError(
                "invoice_line_amounts_invalid",
                "Netto und Steuer müssen zusammen den Bruttobetrag ergeben.",
            )

    def payload(self) -> dict[str, object]:
        return {
            "description": self.description,
            "quantity": self.quantity,
            "unit": self.unit.value,
            "unitPriceGrossMinor": self.unit_price_gross.amount_minor,
            "taxRateBasisPoints": self.tax_rate_basis_points,
            "netMinor": self.net.amount_minor,
            "taxMinor": self.tax.amount_minor,
            "grossMinor": self.gross.amount_minor,
            "currency": self.gross.currency,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> InvoiceLineSnapshot:
        currency = str(payload["currency"])
        return cls(
            description=str(payload["description"]),
            quantity=_payload_integer(payload, "quantity"),
            unit=OfferingUnit(str(payload["unit"])),
            unit_price_gross=Money(
                _payload_integer(payload, "unitPriceGrossMinor"),
                currency,
            ),
            tax_rate_basis_points=_payload_integer(
                payload,
                "taxRateBasisPoints",
            ),
            net=Money(_payload_integer(payload, "netMinor"), currency),
            tax=Money(_payload_integer(payload, "taxMinor"), currency),
            gross=Money(_payload_integer(payload, "grossMinor"), currency),
        )


@dataclass(frozen=True, slots=True)
class Invoice:
    id: UUID
    action_id: UUID
    commitment_id: UUID
    number: str
    status: InvoiceStatus
    issued_at: datetime
    service_on: date
    due_on: date
    issuer: InvoiceIssuerSnapshot
    payment_details: InvoicePaymentDetailsSnapshot
    recipient: InvoiceRecipientSnapshot
    lines: tuple[InvoiceLineSnapshot, ...]
    tax_treatment: TaxTreatment
    tax_note: str
    net: Money
    tax: Money
    gross: Money
    payment_reference: str
    approved_by_user_id: UUID
    replayed: bool = False

    def __post_init__(self) -> None:
        if not INVOICE_NUMBER.fullmatch(self.number):
            raise DomainInvariantError(
                "invoice_number_invalid",
                "Die Rechnungsnummer besitzt ein ungültiges Format.",
            )
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise DomainInvariantError(
                "invoice_issued_at_timezone_required",
                "Der Freigabezeitpunkt benötigt eine eindeutige Zeitzone.",
            )
        if self.due_on < self.issued_at.date():
            raise DomainInvariantError(
                "invoice_due_date_invalid",
                "Das Zahlungsziel darf nicht vor dem Rechnungsdatum liegen.",
            )
        if not self.lines:
            raise DomainInvariantError(
                "invoice_lines_required",
                "Eine Rechnung benötigt mindestens eine Position.",
            )
        calculated_net = Money(0, self.gross.currency)
        calculated_tax = Money(0, self.gross.currency)
        calculated_gross = Money(0, self.gross.currency)
        for line in self.lines:
            calculated_net = calculated_net.plus(line.net)
            calculated_tax = calculated_tax.plus(line.tax)
            calculated_gross = calculated_gross.plus(line.gross)
        if (
            calculated_net != self.net
            or calculated_tax != self.tax
            or calculated_gross != self.gross
            or self.net.plus(self.tax) != self.gross
        ):
            raise DomainInvariantError(
                "invoice_totals_invalid",
                "Die Rechnungsbeträge stimmen nicht mit den Positionen überein.",
            )
        object.__setattr__(
            self,
            "tax_note",
            _required(
                self.tax_note,
                code="invoice_tax_note_empty",
                label="Steuerhinweis",
            ),
        )
        object.__setattr__(
            self,
            "payment_reference",
            _required(
                self.payment_reference,
                code="invoice_payment_reference_empty",
                label="Zahlungsreferenz",
            ),
        )

    def transition_to(self, target: InvoiceStatus) -> Invoice:
        if target is self.status:
            return self
        if target not in ALLOWED_INVOICE_TRANSITIONS[self.status]:
            raise DomainInvariantError(
                "invoice_status_transition_invalid",
                f"Die Rechnung darf nicht von {self.status.value} nach {target.value} wechseln.",
            )
        return replace(self, status=target)

    @classmethod
    def issue(
        cls,
        *,
        id: UUID,
        number: str,
        commitment: Commitment,
        profile: InvoiceProfile,
        approved_by_user_id: UUID,
        issued_at: datetime,
        service_on: date,
    ) -> Invoice:
        if commitment.status is not CommitmentStatus.REVIEW_READY:
            raise DomainInvariantError(
                "invoice_commitment_not_review_ready",
                "Nur eine prüfbereite Bestellung kann freigegeben werden.",
            )
        if commitment.invoice_recipient is None:
            raise DomainInvariantError(
                "invoice_recipient_required",
                "Vor der Freigabe wird ein vollständiger Rechnungsempfänger benötigt.",
            )
        if not profile.ready_to_issue:
            raise DomainInvariantError(
                "invoice_profile_not_confirmed",
                "Der rechtliche Träger und Steuerfall müssen vor der Freigabe bestätigt sein.",
            )
        payment_details = profile.payment_details
        if payment_details is None:
            raise DomainInvariantError(
                "invoice_payment_details_missing",
                "Vor der Freigabe müssen vollständige Zahlungsdaten bestätigt sein.",
            )
        if profile.action_id != commitment.action_id:
            raise DomainInvariantError(
                "invoice_profile_action_mismatch",
                "Der Rechnungsnummernkreis gehört nicht zu dieser Charity-Aktion.",
            )
        rate = (
            profile.tax_rate_basis_points
            if profile.tax_treatment is TaxTreatment.STANDARD_VAT
            else 0
        )
        lines = tuple(
            _snapshot_line(
                description=line.description_snapshot,
                quantity=line.quantity,
                unit=line.unit_snapshot,
                unit_price_gross=line.unit_price,
                rate_basis_points=rate,
            )
            for line in commitment.lines
        )
        currency = commitment.total.currency
        net = Money(sum(line.net.amount_minor for line in lines), currency)
        tax = Money(sum(line.tax.amount_minor for line in lines), currency)
        gross = Money(sum(line.gross.amount_minor for line in lines), currency)
        return cls(
            id=id,
            action_id=commitment.action_id,
            commitment_id=commitment.id,
            number=number,
            status=InvoiceStatus.ISSUED,
            issued_at=issued_at,
            service_on=service_on,
            due_on=issued_at.date() + timedelta(days=profile.payment_terms_days),
            issuer=profile.issuer,
            payment_details=payment_details,
            recipient=commitment.invoice_recipient,
            lines=lines,
            tax_treatment=profile.tax_treatment,
            tax_note=profile.tax_note,
            net=net,
            tax=tax,
            gross=gross,
            payment_reference=number,
            approved_by_user_id=approved_by_user_id,
        )


def _snapshot_line(
    *,
    description: str,
    quantity: int,
    unit: OfferingUnit,
    unit_price_gross: Money,
    rate_basis_points: int,
) -> InvoiceLineSnapshot:
    gross = unit_price_gross.multiply(quantity)
    if rate_basis_points:
        divisor = 10_000 + rate_basis_points
        net_minor = (gross.amount_minor * 10_000 + divisor // 2) // divisor
    else:
        net_minor = gross.amount_minor
    net = Money(net_minor, gross.currency)
    tax = Money(gross.amount_minor - net_minor, gross.currency)
    return InvoiceLineSnapshot(
        description=description,
        quantity=quantity,
        unit=unit,
        unit_price_gross=unit_price_gross,
        tax_rate_basis_points=rate_basis_points,
        net=net,
        tax=tax,
        gross=gross,
    )
