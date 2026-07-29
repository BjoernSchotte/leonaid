"""Privacy evidence, contact suppression and data-subject workflow values."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import require_aware

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


class PrivacyPurpose(StrEnum):
    PUBLIC_ORDER_FULFILMENT = "public_order_fulfilment"
    ACQUISITION = "acquisition"
    MARKETING = "marketing"


class ContactChannel(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    POSTAL = "postal"


class ConsentEvidenceKind(StrEnum):
    NOTICE_ACKNOWLEDGEMENT = "notice_acknowledgement"
    EXPLICIT_CONSENT = "explicit_consent"


class LegalBasisStatus(StrEnum):
    REVIEW_PENDING = "legal_review_pending"
    CONFIRMED = "confirmed"


class ErasureStatus(StrEnum):
    COMPLETED_WITH_RETENTION = "completed_with_retention"


def normalize_recipient(value: str, channel: ContactChannel) -> str:
    normalized = " ".join(value.split()).casefold()
    if channel is ContactChannel.EMAIL:
        if len(normalized) > 320 or not EMAIL.fullmatch(normalized):
            raise DomainInvariantError(
                "privacy_email_invalid",
                "Bitte gib eine gültige E-Mail-Adresse ein.",
            )
        return normalized
    if not normalized or len(normalized) > 500:
        raise DomainInvariantError(
            "privacy_recipient_invalid",
            "Der Kontaktwert ist ungültig.",
        )
    return normalized


def subject_digest(normalized_recipient: str, secret: str) -> str:
    if len(secret) < 32:
        raise ValueError("Privacy-HMAC-Secret muss mindestens 32 Zeichen lang sein.")
    return hmac.new(
        secret.encode(),
        f"leonaid-privacy-subject:v1:{normalized_recipient}".encode(),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    id: UUID
    action_id: UUID | None
    commitment_id: UUID | None
    twenty_company_id: UUID | None
    twenty_person_id: UUID | None
    normalized_recipient: str
    purpose: PrivacyPurpose
    channel: ContactChannel
    text_version: str
    source: str
    evidence_kind: ConsentEvidenceKind
    legal_basis_status: LegalBasisStatus
    granted_at: datetime
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        require_aware(self.granted_at, "Consent-Zeitpunkt")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, "Widerrufszeitpunkt")
            if self.revoked_at < self.granted_at:
                raise DomainInvariantError(
                    "consent_revocation_before_grant",
                    "Der Widerruf darf nicht vor dem Nachweis liegen.",
                )


@dataclass(frozen=True, slots=True)
class SuppressionEntry:
    id: UUID
    normalized_recipient: str
    channel: ContactChannel
    purpose: PrivacyPurpose
    reason: str
    suppressed_at: datetime
    consent_record_id: UUID | None

    def __post_init__(self) -> None:
        require_aware(self.suppressed_at, "Sperrzeitpunkt")


@dataclass(frozen=True, slots=True)
class PrivacyReference:
    id: UUID
    reference_type: str
    action_id: UUID | None
    status: str | None
    label: str


@dataclass(frozen=True, slots=True)
class PrivacyRetentionPolicy:
    legal_configuration_version_id: UUID
    legal_configuration_version: int
    invoice_days: int
    commitment_days: int
    contact_days: int
    consent_evidence_days: int
    audit_days: int

    def __post_init__(self) -> None:
        if self.legal_configuration_version < 1:
            raise DomainInvariantError(
                "privacy_retention_version_invalid",
                "Die Version der Aufbewahrungsregeln ist ungültig.",
            )
        if any(
            days < 1 or days > 36_500
            for days in (
                self.invoice_days,
                self.commitment_days,
                self.contact_days,
                self.consent_evidence_days,
                self.audit_days,
            )
        ):
            raise DomainInvariantError(
                "privacy_retention_days_invalid",
                "Die freigegebenen Aufbewahrungsfristen sind ungültig.",
            )


@dataclass(frozen=True, slots=True)
class PrivacySubjectReport:
    normalized_recipient: str
    retention: PrivacyRetentionPolicy
    twenty_company_ids: tuple[UUID, ...]
    twenty_person_ids: tuple[UUID, ...]
    consents: tuple[ConsentRecord, ...]
    suppressions: tuple[SuppressionEntry, ...]
    commitments: tuple[PrivacyReference, ...]
    invoices: tuple[PrivacyReference, ...]
    documents: tuple[PrivacyReference, ...]
    assignments: tuple[PrivacyReference, ...]
    activities: tuple[PrivacyReference, ...]

    @property
    def found(self) -> bool:
        return any(
            (
                self.twenty_company_ids,
                self.twenty_person_ids,
                self.consents,
                self.suppressions,
                self.commitments,
                self.invoices,
                self.documents,
                self.assignments,
                self.activities,
            )
        )


@dataclass(frozen=True, slots=True)
class PrivacyErasureResult:
    case_id: UUID
    subject_hash: str
    status: ErasureStatus
    retention: PrivacyRetentionPolicy
    anonymized_commitments: int
    cleared_activity_notes: int
    cleared_reminders: int
    revoked_consents: int
    retained_invoice_ids: tuple[UUID, ...]
    retained_document_ids: tuple[UUID, ...]
    retention_reasons: tuple[str, ...]
    open_decisions: tuple[str, ...]
    completed_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.completed_at, "Löschabschluss")
