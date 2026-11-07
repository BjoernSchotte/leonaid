"""Versioned organization, invoice and privacy configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoices import (
    InvoiceIssuerSnapshot,
    InvoicePaymentDetailsSnapshot,
    TaxTreatment,
)

EVIDENCE_ID = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{2,119}$")
TEXT_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
NUMBER_PREFIX = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,23}$")
# § 5 Abs. 1 Nr. 2 DDG: a second fast channel next to e-mail; digits with
# the usual separators, optionally international.
PHONE = re.compile(r"^\+?[0-9][0-9 ()/.-]{4,28}[0-9]$")
# § 27a UStG identification number: country prefix and 2–12 characters.
VAT_ID = re.compile(r"^[A-Z]{2}[A-Z0-9]{2,12}$")
# "e. V.", "e.V." or "eingetragener Verein" in the carrier's name: such a
# carrier is in the Vereinsregister, so § 5 Abs. 1 Nr. 4 DDG applies.
REGISTERED_ASSOCIATION = re.compile(
    r"(?:\be\.\s*v\.?(?=$|[\s,;)])|eingetragener verein)"
)
# Template texts mark what the club must still fill in as [[...]].
TEMPLATE_PLACEHOLDER = "[["
PRIVACY_POLICY_LIMITS = (200, 60_000)
MEMBER_NOTICE_LIMITS = (100, 30_000)


def _single_line(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _block_text(value: str | None) -> str | None:
    """Keep paragraphs: trim lines, at most one empty line between blocks."""
    if value is None:
        return None
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text or None


class EInvoiceDecision(StrEnum):
    PENDING = "pending"
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True)
class RetentionSchedule:
    invoice_days: int
    commitment_days: int
    contact_days: int
    consent_evidence_days: int
    audit_days: int

    def __post_init__(self) -> None:
        for field_name, label in (
            ("invoice_days", "Rechnungen"),
            ("commitment_days", "Bestellungen und Zusagen"),
            ("contact_days", "Kontakte"),
            ("consent_evidence_days", "Einwilligungsnachweise"),
            ("audit_days", "Audit-Ereignisse"),
        ):
            value = getattr(self, field_name)
            if not 1 <= value <= 36_500:
                raise DomainInvariantError(
                    "legal_retention_invalid",
                    f"Die Aufbewahrungsfrist für {label} muss zwischen 1 und "
                    "36.500 Tagen liegen.",
                )


@dataclass(frozen=True, slots=True)
class LegalConfigurationDraft:
    issuer: InvoiceIssuerSnapshot
    bank_account_holder: str
    iban: str
    bic: str | None
    tax_treatment: TaxTreatment
    tax_rate_basis_points: int
    tax_note: str
    number_prefix: str
    number_width: int
    payment_terms_days: int
    public_order_legal_basis: str
    public_order_notice_text: str
    consent_text_version: str
    privacy_contact_email: str
    retention: RetentionSchedule
    e_invoice_decision: EInvoiceDecision
    tax_evidence_id: str
    privacy_evidence_id: str
    e_invoice_evidence_id: str | None
    # Impressum (§ 5 DDG, § 18 Abs. 2 MStV). Optional in the type because
    # versions before 0052 have none; production activation requires the
    # mandatory ones (activation_blockers).
    imprint_representatives: str | None = None
    imprint_phone: str | None = None
    imprint_register_court: str | None = None
    imprint_register_number: str | None = None
    imprint_vat_id: str | None = None
    imprint_content_responsible_name: str | None = None
    imprint_content_responsible_address: str | None = None
    # The full privacy policy (/datenschutz) and the members' notice in it.
    privacy_policy_text: str | None = None
    member_privacy_notice_text: str | None = None

    def __post_init__(self) -> None:
        self._normalize_imprint()
        for field_name, label, (minimum, maximum) in (
            ("privacy_policy_text", "Datenschutzerklärung", PRIVACY_POLICY_LIMITS),
            (
                "member_privacy_notice_text",
                "Datenschutzhinweis für Mitglieder",
                MEMBER_NOTICE_LIMITS,
            ),
        ):
            text = _block_text(getattr(self, field_name))
            if text is not None and not minimum <= len(text) <= maximum:
                raise DomainInvariantError(
                    f"legal_{field_name}_invalid",
                    f"{label} muss zwischen {minimum} und {maximum} Zeichen lang sein.",
                )
            object.__setattr__(self, field_name, text)
        for field_name, label, minimum in (
            ("bank_account_holder", "Kontoinhaber", 2),
            ("tax_note", "Steuerhinweis", 8),
            ("public_order_legal_basis", "Rechtsgrundlage", 12),
            ("public_order_notice_text", "Datenschutzinformation", 40),
        ):
            normalized = " ".join(getattr(self, field_name).split())
            if len(normalized) < minimum:
                raise DomainInvariantError(
                    f"legal_{field_name}_invalid",
                    f"{label} ist zu kurz oder fehlt.",
                )
            object.__setattr__(self, field_name, normalized)

        try:
            payment_details = InvoicePaymentDetailsSnapshot(
                account_holder=self.bank_account_holder,
                iban=self.iban,
                bic=self.bic,
            )
        except DomainInvariantError as error:
            code = error.code.replace("invoice_payment_", "legal_", 1)
            raise DomainInvariantError(code, error.message) from error
        object.__setattr__(
            self,
            "bank_account_holder",
            payment_details.account_holder,
        )
        object.__setattr__(self, "iban", payment_details.iban)
        object.__setattr__(self, "bic", payment_details.bic)

        if self.tax_treatment is TaxTreatment.STANDARD_VAT:
            if not 1 <= self.tax_rate_basis_points <= 10_000:
                raise DomainInvariantError(
                    "legal_tax_rate_required",
                    "Regelbesteuerung benötigt einen Steuersatz.",
                )
        elif self.tax_rate_basis_points != 0:
            raise DomainInvariantError(
                "legal_tax_rate_forbidden",
                "Ohne Umsatzsteuerausweis muss der Steuersatz null sein.",
            )
        if NUMBER_PREFIX.fullmatch(self.number_prefix) is None:
            raise DomainInvariantError(
                "legal_number_prefix_invalid",
                "Das Rechnungspräfix darf nur Großbuchstaben, Zahlen und "
                "Bindestriche enthalten.",
            )
        if not 3 <= self.number_width <= 8:
            raise DomainInvariantError(
                "legal_number_width_invalid",
                "Rechnungsnummern benötigen drei bis acht Stellen.",
            )
        if not 1 <= self.payment_terms_days <= 120:
            raise DomainInvariantError(
                "legal_payment_terms_invalid",
                "Das Zahlungsziel muss zwischen einem und 120 Tagen liegen.",
            )
        if TEXT_VERSION.fullmatch(self.consent_text_version) is None:
            raise DomainInvariantError(
                "legal_consent_version_invalid",
                "Die Textversion darf nur Kleinbuchstaben, Zahlen, Punkt, "
                "Bindestrich und Unterstrich enthalten.",
            )
        normalized_privacy_email = self.privacy_contact_email.strip().casefold()
        if normalized_privacy_email.count("@") != 1 or any(
            character.isspace() for character in normalized_privacy_email
        ):
            raise DomainInvariantError(
                "legal_privacy_email_invalid",
                "Die Datenschutz-Kontaktadresse ist ungültig.",
            )
        object.__setattr__(self, "privacy_contact_email", normalized_privacy_email)
        for field_name, label in (
            ("tax_evidence_id", "Steuerfreigabe"),
            ("privacy_evidence_id", "Datenschutzfreigabe"),
        ):
            value = getattr(self, field_name)
            if EVIDENCE_ID.fullmatch(value) is None:
                raise DomainInvariantError(
                    "legal_evidence_id_invalid",
                    f"Die Evidence-ID für {label} ist ungültig.",
                )
        if self.e_invoice_evidence_id is not None and (
            EVIDENCE_ID.fullmatch(self.e_invoice_evidence_id) is None
        ):
            raise DomainInvariantError(
                "legal_evidence_id_invalid",
                "Die Evidence-ID zur E-Rechnungsentscheidung ist ungültig.",
            )

    def _normalize_imprint(self) -> None:
        for field_name in (
            "imprint_representatives",
            "imprint_phone",
            "imprint_register_court",
            "imprint_register_number",
            "imprint_content_responsible_name",
            "imprint_content_responsible_address",
        ):
            object.__setattr__(
                self, field_name, _single_line(getattr(self, field_name))
            )
        for field_name, label, minimum, maximum in (
            ("imprint_representatives", "Vertretungsberechtigte", 3, 1_000),
            ("imprint_register_court", "Registergericht", 3, 200),
            ("imprint_register_number", "Registernummer", 2, 60),
            (
                "imprint_content_responsible_name",
                "Inhaltlich Verantwortliche Person",
                3,
                200,
            ),
            (
                "imprint_content_responsible_address",
                "Anschrift der inhaltlich verantwortlichen Person",
                8,
                400,
            ),
        ):
            value = getattr(self, field_name)
            if value is not None and not minimum <= len(value) <= maximum:
                raise DomainInvariantError(
                    f"legal_{field_name}_invalid",
                    f"{label} ist zu kurz oder zu lang.",
                )
        if self.imprint_phone is not None and (
            PHONE.fullmatch(self.imprint_phone) is None
        ):
            raise DomainInvariantError(
                "legal_imprint_phone_invalid",
                "Die Telefonnummer darf nur Ziffern, Leerzeichen und + ( ) / . - "
                "enthalten.",
            )
        if (self.imprint_register_court is None) != (
            self.imprint_register_number is None
        ):
            raise DomainInvariantError(
                "legal_imprint_register_incomplete",
                "Registergericht und Registernummer gehören zusammen.",
            )
        if (self.imprint_content_responsible_name is None) != (
            self.imprint_content_responsible_address is None
        ):
            raise DomainInvariantError(
                "legal_imprint_content_responsible_incomplete",
                "Für die inhaltlich verantwortliche Person werden Name und "
                "Anschrift benötigt.",
            )
        vat_id = _single_line(self.imprint_vat_id)
        if vat_id is not None:
            vat_id = vat_id.replace(" ", "").upper()
            if VAT_ID.fullmatch(vat_id) is None:
                raise DomainInvariantError(
                    "legal_imprint_vat_id_invalid",
                    "Die Umsatzsteuer-Identifikationsnummer ist ungültig "
                    "(z. B. DE123456789).",
                )
        object.__setattr__(self, "imprint_vat_id", vat_id)

    def registered_association(self) -> bool:
        return (
            REGISTERED_ASSOCIATION.search(self.issuer.legal_name.casefold()) is not None
        )

    def activation_blockers(self, *, production: bool) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.e_invoice_decision is EInvoiceDecision.PENDING:
            blockers.append("e_invoice_decision_pending")
        if self.e_invoice_evidence_id is None:
            blockers.append("e_invoice_evidence_missing")
        if self.e_invoice_decision is EInvoiceDecision.REQUIRED:
            blockers.append("e_invoice_scope_required")
        if production:
            combined = " ".join(
                (
                    self.issuer.legal_name,
                    self.issuer.street_line_1,
                    self.issuer.city,
                    self.issuer.email,
                    self.privacy_contact_email,
                    self.bank_account_holder,
                )
            ).casefold()
            if any(
                marker in combined
                for marker in (
                    "golden",
                    ".invalid",
                    ".test",
                    "example.org",
                    "review-required",
                )
            ):
                blockers.append("synthetic_or_placeholder_value")
            # § 5 DDG: who represents the club and a second fast channel.
            if self.imprint_representatives is None:
                blockers.append("imprint_representatives_missing")
            if self.imprint_phone is None:
                blockers.append("imprint_phone_missing")
            if self.registered_association() and self.imprint_register_number is None:
                blockers.append("imprint_register_missing")
            if self.privacy_policy_text is None:
                blockers.append("privacy_policy_missing")
            if self.member_privacy_notice_text is None:
                blockers.append("member_privacy_notice_missing")
            if any(
                TEMPLATE_PLACEHOLDER in (text or "")
                for text in (
                    self.privacy_policy_text,
                    self.member_privacy_notice_text,
                    self.public_order_notice_text,
                    self.imprint_representatives,
                )
            ):
                blockers.append("template_placeholder_open")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class LegalConfigurationVersion:
    id: UUID
    version: int
    configuration: LegalConfigurationDraft
    created_by_user_id: UUID
    created_by_display_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LegalConfigurationApproval:
    version_id: UUID
    approved_by_user_id: UUID
    approved_by_display_name: str
    evidence_id: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if EVIDENCE_ID.fullmatch(self.evidence_id) is None:
            raise DomainInvariantError(
                "legal_approval_evidence_invalid",
                "Die Evidence-ID der Vier-Augen-Freigabe ist ungültig.",
            )


@dataclass(frozen=True, slots=True)
class LegalConfigurationState:
    revision: int
    draft: LegalConfigurationVersion | None
    active: LegalConfigurationVersion | None
    draft_approval: LegalConfigurationApproval | None

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise DomainInvariantError(
                "legal_configuration_revision_invalid",
                "Die Konfigurationsrevision muss positiv sein.",
            )
