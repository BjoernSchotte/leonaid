from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.privacy import (
    ContactChannel,
    ConsentEvidenceKind,
    ConsentRecord,
    LegalBasisStatus,
    PrivacyPurpose,
    normalize_recipient,
    subject_digest,
)

NOW = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
HMAC_SECRET = "privacy-test-secret-with-at-least-32-characters"


def test_email_normalization_and_subject_hash_are_stable_without_raw_email() -> None:
    normalized = normalize_recipient(
        "  Mara.Muster@Musterwerk.LeonAid.Invalid ",
        ContactChannel.EMAIL,
    )

    assert normalized == "mara.muster@musterwerk.leonaid.invalid"
    assert (
        subject_digest(normalized, HMAC_SECRET)
        == "a824b9dcc302da0e88259dd1fe2e990c6cf046304baa1932220a6126f5e29db3"
    )
    assert normalized not in subject_digest(normalized, HMAC_SECRET)


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        normalize_recipient("keine-adresse", ContactChannel.EMAIL)

    assert captured.value.code == "privacy_email_invalid"


def test_consent_rejects_revocation_before_evidence() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        ConsentRecord(
            id=UUID("d0000000-0000-4000-8000-000000000001"),
            action_id=UUID("20000000-0000-4000-8000-000000000001"),
            commitment_id=UUID("80000000-0000-4000-8000-000000000005"),
            twenty_company_id=None,
            twenty_person_id=UUID("50000000-0000-4000-8000-000000000001"),
            normalized_recipient="mara.muster@musterwerk.leonaid.invalid",
            purpose=PrivacyPurpose.PUBLIC_ORDER_FULFILMENT,
            channel=ContactChannel.EMAIL,
            text_version="public-order-poc-2026-07",
            source="public_order_form",
            evidence_kind=ConsentEvidenceKind.NOTICE_ACKNOWLEDGEMENT,
            legal_basis_status=LegalBasisStatus.REVIEW_PENDING,
            granted_at=NOW,
            revoked_at=NOW - timedelta(seconds=1),
        )

    assert captured.value.code == "consent_revocation_before_grant"
