"""Offerings, quantities, money and commitment aggregate rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from uuid import UUID, uuid4

from leonaid.domain.action_templates import OfferingStatus, OfferingUnit
from leonaid.domain.errors import DomainInvariantError

CURRENCY = re.compile(r"^[A-Z]{3}$")
COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
PUBLIC_REFERENCE = re.compile(r"^LA-[A-F0-9]{32}$")


class CommitmentSource(StrEnum):
    ACQUISITION = "acquisition"
    PUBLIC_FORM = "public_form"
    ADMIN = "admin"


class CommitmentStatus(StrEnum):
    DRAFT = "draft"
    REVIEW_READY = "review_ready"
    CONFIRMED = "confirmed"
    INVOICED = "invoiced"
    CANCELLED = "cancelled"


class CommitmentPartyKind(StrEnum):
    COMPANY = "company"
    PERSON = "person"


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.amount_minor, int)
            or isinstance(self.amount_minor, bool)
            or self.amount_minor < 0
        ):
            raise DomainInvariantError(
                "money_amount_invalid",
                "Ein Geldbetrag muss als nicht-negative ganze Untereinheit vorliegen.",
            )
        if not CURRENCY.fullmatch(self.currency):
            raise DomainInvariantError(
                "money_currency_invalid",
                "Die Währung muss aus drei Großbuchstaben bestehen.",
            )

    @classmethod
    def from_major(cls, amount: Decimal, currency: str) -> Money:
        if not amount.is_finite() or amount < 0:
            raise DomainInvariantError(
                "money_amount_invalid",
                "Ein Geldbetrag muss endlich und nicht negativ sein.",
            )
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return cls(
            amount_minor=int(rounded * 100),
            currency=currency,
        )

    def multiply(self, quantity: int) -> Money:
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise DomainInvariantError(
                "money_quantity_invalid",
                "Ein Geldbetrag kann nur mit einer positiven Menge berechnet werden.",
            )
        return Money(self.amount_minor * quantity, self.currency)

    def plus(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise DomainInvariantError(
                "money_currency_mismatch",
                "Geldbeträge unterschiedlicher Währungen dürfen nicht addiert werden.",
            )
        return Money(self.amount_minor + other.amount_minor, self.currency)


@dataclass(frozen=True, slots=True)
class BuyerSnapshot:
    party_kind: CommitmentPartyKind
    twenty_id: UUID
    display_name: str
    email: str | None = None

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise DomainInvariantError(
                "commitment_buyer_name_empty",
                "Der Besteller benötigt einen Namen.",
            )
        if self.email is not None and (
            self.email != self.email.casefold()
            or self.email.count("@") != 1
            or any(character.isspace() for character in self.email)
        ):
            raise DomainInvariantError(
                "commitment_buyer_email_invalid",
                "Die Besteller-E-Mail ist ungültig.",
            )

    @property
    def company_id(self) -> UUID | None:
        return (
            self.twenty_id if self.party_kind is CommitmentPartyKind.COMPANY else None
        )

    @property
    def person_id(self) -> UUID | None:
        return self.twenty_id if self.party_kind is CommitmentPartyKind.PERSON else None

    def payload(self) -> dict[str, object]:
        return {
            "partyKind": self.party_kind.value,
            "twentyId": str(self.twenty_id),
            "displayName": self.display_name,
            "email": self.email,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> BuyerSnapshot:
        return cls(
            party_kind=CommitmentPartyKind(str(payload["partyKind"])),
            twenty_id=UUID(str(payload["twentyId"])),
            display_name=str(payload["displayName"]),
            email=(str(payload["email"]) if payload.get("email") is not None else None),
        )


@dataclass(frozen=True, slots=True)
class InvoiceRecipientSnapshot:
    recipient_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str = "DE"
    email: str | None = None

    def __post_init__(self) -> None:
        for value, code, label in (
            (self.recipient_name, "invoice_recipient_name_empty", "Name"),
            (self.street_line_1, "invoice_recipient_street_empty", "Straße"),
            (self.postal_code, "invoice_recipient_postal_code_empty", "Postleitzahl"),
            (self.city, "invoice_recipient_city_empty", "Ort"),
        ):
            if not value.strip():
                raise DomainInvariantError(
                    code,
                    f"{label} des Rechnungsempfängers darf nicht leer sein.",
                )
        if not COUNTRY_CODE.fullmatch(self.country_code):
            raise DomainInvariantError(
                "invoice_recipient_country_invalid",
                "Der Ländercode muss aus zwei Großbuchstaben bestehen.",
            )
        if self.email is not None and (
            self.email != self.email.casefold()
            or self.email.count("@") != 1
            or any(character.isspace() for character in self.email)
        ):
            raise DomainInvariantError(
                "invoice_recipient_email_invalid",
                "Die E-Mail des Rechnungsempfängers ist ungültig.",
            )

    def payload(self) -> dict[str, object]:
        return {
            "recipientName": self.recipient_name,
            "streetLine1": self.street_line_1,
            "postalCode": self.postal_code,
            "city": self.city,
            "countryCode": self.country_code,
            "email": self.email,
        }

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
    ) -> InvoiceRecipientSnapshot:
        return cls(
            recipient_name=str(payload["recipientName"]),
            street_line_1=str(payload["streetLine1"]),
            postal_code=str(payload["postalCode"]),
            city=str(payload["city"]),
            country_code=str(payload["countryCode"]),
            email=(str(payload["email"]) if payload.get("email") is not None else None),
        )


@dataclass(frozen=True, slots=True)
class DeliveryRecipientSnapshot:
    recipient_name: str
    street_line_1: str
    postal_code: str
    city: str
    country_code: str = "DE"

    def __post_init__(self) -> None:
        for value, code, label in (
            (self.recipient_name, "delivery_recipient_name_empty", "Name"),
            (self.street_line_1, "delivery_recipient_street_empty", "Straße"),
            (
                self.postal_code,
                "delivery_recipient_postal_code_empty",
                "Postleitzahl",
            ),
            (self.city, "delivery_recipient_city_empty", "Ort"),
        ):
            if not value.strip():
                raise DomainInvariantError(
                    code,
                    f"{label} des Lieferempfängers darf nicht leer sein.",
                )
        if not COUNTRY_CODE.fullmatch(self.country_code):
            raise DomainInvariantError(
                "delivery_recipient_country_invalid",
                "Der Ländercode muss aus zwei Großbuchstaben bestehen.",
            )

    def payload(self) -> dict[str, object]:
        return {
            "recipientName": self.recipient_name,
            "streetLine1": self.street_line_1,
            "postalCode": self.postal_code,
            "city": self.city,
            "countryCode": self.country_code,
        }

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
    ) -> DeliveryRecipientSnapshot:
        return cls(
            recipient_name=str(payload["recipientName"]),
            street_line_1=str(payload["streetLine1"]),
            postal_code=str(payload["postalCode"]),
            city=str(payload["city"]),
            country_code=str(payload["countryCode"]),
        )


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantError(
            "offering_time_timezone_required",
            f"{field} benötigt eine eindeutige Zeitzone.",
        )


@dataclass(frozen=True, slots=True)
class Offering:
    id: UUID
    action_id: UUID
    code: str
    name: str
    status: OfferingStatus
    pricing_unit: OfferingUnit
    allowed_quantity_units: frozenset[OfferingUnit]
    pieces_per_unit: int | None
    unit_price: Money
    available_from: datetime | None
    available_until: datetime | None

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.name.strip():
            raise DomainInvariantError(
                "offering_identity_empty",
                "Angebotsschlüssel und Name dürfen nicht leer sein.",
            )
        if (
            not self.allowed_quantity_units
            or self.pricing_unit not in self.allowed_quantity_units
        ):
            raise DomainInvariantError(
                "offering_quantity_units_invalid",
                "Die Preiseinheit muss als erlaubte Mengeneinheit enthalten sein.",
            )
        if self.pieces_per_unit is not None and self.pieces_per_unit <= 0:
            raise DomainInvariantError(
                "offering_pieces_invalid",
                "Die Stückzahl je Einheit muss positiv sein.",
            )
        if self.pricing_unit is OfferingUnit.BOX and self.pieces_per_unit is None:
            raise DomainInvariantError(
                "offering_box_pieces_required",
                "Eine Box benötigt eine nachvollziehbare Stückzahl.",
            )
        if (self.available_from is None) != (self.available_until is None):
            raise DomainInvariantError(
                "offering_period_incomplete",
                "Der Angebotszeitraum benötigt Beginn und Ende.",
            )
        if self.available_from is not None and self.available_until is not None:
            _aware(self.available_from, "Angebotsbeginn")
            _aware(self.available_until, "Angebotsende")
            if self.available_from >= self.available_until:
                raise DomainInvariantError(
                    "offering_period_invalid",
                    "Der Angebotsbeginn muss vor dem Angebotsende liegen.",
                )

    def available_at(self, moment: datetime) -> bool:
        _aware(moment, "Prüfzeitpunkt")
        return self.status is OfferingStatus.ACTIVE and (
            self.available_from is None
            or (
                self.available_until is not None
                and self.available_from <= moment < self.available_until
            )
        )


@dataclass(frozen=True, slots=True)
class CommitmentLine:
    id: UUID
    offering_id: UUID
    description_snapshot: str
    quantity: int
    unit_snapshot: OfferingUnit
    pieces_per_unit_snapshot: int | None
    unit_price: Money
    line_total: Money

    def __post_init__(self) -> None:
        if not self.description_snapshot.strip():
            raise DomainInvariantError(
                "commitment_line_description_empty",
                "Eine Bestellposition benötigt eine Beschreibung.",
            )
        if isinstance(self.quantity, bool) or self.quantity <= 0:
            raise DomainInvariantError(
                "commitment_line_quantity_invalid",
                "Die Bestellmenge muss positiv sein.",
            )
        if self.line_total != self.unit_price.multiply(self.quantity):
            raise DomainInvariantError(
                "commitment_line_total_invalid",
                "Der Positionsbetrag muss aus Serverpreis und Menge entstehen.",
            )

    @property
    def piece_count(self) -> int:
        if self.unit_snapshot is OfferingUnit.PIECE:
            return self.quantity
        if self.pieces_per_unit_snapshot is not None:
            return self.quantity * self.pieces_per_unit_snapshot
        return 0

    @property
    def box_count(self) -> int:
        return self.quantity if self.unit_snapshot is OfferingUnit.BOX else 0

    @classmethod
    def price_from(
        cls,
        offering: Offering,
        *,
        quantity: int,
        unit: OfferingUnit,
        evaluated_at: datetime,
    ) -> CommitmentLine:
        if not offering.available_at(evaluated_at):
            raise DomainInvariantError(
                "offering_not_available",
                "Dieses Angebot ist derzeit nicht bestellbar.",
            )
        if unit not in offering.allowed_quantity_units:
            raise DomainInvariantError(
                "offering_quantity_unit_not_allowed",
                "Diese Mengeneinheit ist für das Angebot nicht erlaubt.",
            )
        if unit is not offering.pricing_unit:
            raise DomainInvariantError(
                "offering_quantity_conversion_unsupported",
                "Diese Mengeneinheit besitzt noch keine eindeutige Preisumrechnung.",
            )
        total = offering.unit_price.multiply(quantity)
        return cls(
            id=uuid4(),
            offering_id=offering.id,
            description_snapshot=offering.name,
            quantity=quantity,
            unit_snapshot=unit,
            pieces_per_unit_snapshot=offering.pieces_per_unit,
            unit_price=offering.unit_price,
            line_total=total,
        )


@dataclass(frozen=True, slots=True)
class Commitment:
    id: UUID
    action_id: UUID
    source: CommitmentSource
    status: CommitmentStatus
    buyer: BuyerSnapshot
    invoice_recipient: InvoiceRecipientSnapshot | None
    lines: tuple[CommitmentLine, ...]
    total: Money
    delivery_recipient: DeliveryRecipientSnapshot | None = None
    message: str | None = None
    public_reference: str | None = None
    idempotency_key: str | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        if not self.lines:
            raise DomainInvariantError(
                "commitment_lines_required",
                "Eine Bestellung benötigt mindestens eine Position.",
            )
        offering_ids = [line.offering_id for line in self.lines]
        if len(offering_ids) != len(set(offering_ids)):
            raise DomainInvariantError(
                "commitment_offering_duplicate",
                "Ein Angebot darf nur einmal je Bestellung vorkommen.",
            )
        calculated = Money(0, self.total.currency)
        for line in self.lines:
            calculated = calculated.plus(line.line_total)
        if calculated != self.total:
            raise DomainInvariantError(
                "commitment_total_invalid",
                "Der Gesamtbetrag muss der Summe der Serverpositionen entsprechen.",
            )
        if self.message is not None:
            normalized_message = " ".join(self.message.split())
            if len(normalized_message) > 1000:
                raise DomainInvariantError(
                    "commitment_message_too_long",
                    "Die Nachricht darf höchstens 1000 Zeichen enthalten.",
                )
            object.__setattr__(self, "message", normalized_message or None)
        if self.source is CommitmentSource.PUBLIC_FORM:
            if self.public_reference is None or not PUBLIC_REFERENCE.fullmatch(
                self.public_reference
            ):
                raise DomainInvariantError(
                    "commitment_public_reference_invalid",
                    "Eine öffentliche Bestellung benötigt eine gültige Referenz.",
                )
            if self.delivery_recipient is None:
                raise DomainInvariantError(
                    "commitment_delivery_recipient_required",
                    "Eine öffentliche Bestellung benötigt eine Lieferanschrift.",
                )
        elif self.public_reference is not None:
            raise DomainInvariantError(
                "commitment_public_reference_forbidden",
                "Nur öffentliche Bestellungen besitzen eine öffentliche Referenz.",
            )

    @property
    def total_pieces(self) -> int:
        return sum(line.piece_count for line in self.lines)

    @property
    def total_boxes(self) -> int:
        return sum(line.box_count for line in self.lines)
