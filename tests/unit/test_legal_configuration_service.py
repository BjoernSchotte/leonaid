"""An admin app from before the Impressum fields must not clear them."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from leonaid.application.legal_configuration import LegalConfigurationService
from leonaid.domain.identity import (
    AccountStatus,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.legal_configuration import (
    LegalConfigurationDraft,
    LegalConfigurationState,
    LegalConfigurationVersion,
)

from leonaid.entrypoints.fastapi.schemas import SaveLegalConfigurationDraftRequest

from .test_legal_configuration import valid_draft

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


class Repository:
    def __init__(self, active: LegalConfigurationDraft | None) -> None:
        self.active = (
            LegalConfigurationVersion(
                id=uuid4(),
                version=1,
                configuration=active,
                created_by_user_id=uuid4(),
                created_by_display_name="Simone System",
                created_at=NOW,
            )
            if active is not None
            else None
        )
        self.saved: LegalConfigurationDraft | None = None

    async def state(self) -> LegalConfigurationState:
        return LegalConfigurationState(
            revision=2, draft=None, active=self.active, draft_approval=None
        )

    async def save_draft(
        self, *, configuration: LegalConfigurationDraft, **_: object
    ) -> LegalConfigurationState:
        self.saved = configuration
        return await self.state()


def admin() -> IdentityPrincipal:
    user_id: UUID = uuid4()
    return IdentityPrincipal(
        account=UserAccount(
            user_id, f"{user_id}@example.test", "Klara", AccountStatus.ACTIVE
        ),
        global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}),
        action_memberships=(),
    )


def without_imprint() -> LegalConfigurationDraft:
    return replace(
        valid_draft(),
        legal_form=None,
        imprint_representatives=None,
        imprint_phone=None,
        imprint_register_court=None,
        imprint_register_number=None,
        imprint_vat_id=None,
        privacy_policy_text=None,
        member_privacy_notice_text=None,
    )


@pytest.mark.asyncio
async def test_omitted_later_fields_keep_the_previous_values() -> None:
    previous = replace(valid_draft(), imprint_vat_id="DE123456789")
    repository = Repository(previous)
    service = LegalConfigurationService(repository, production=False)  # type: ignore[arg-type]

    await service.save_draft(
        admin(),
        configuration=without_imprint(),
        expected_revision=2,
        request_id="req-legal-carry",
        omitted_fields=frozenset(
            {
                "legal_form",
                "imprint_representatives",
                "imprint_phone",
                "imprint_register_court",
                "imprint_register_number",
                "imprint_vat_id",
                "privacy_policy_text",
                "member_privacy_notice_text",
                # Not a later field: never carried over.
                "bic",
            }
        ),
    )

    saved = repository.saved
    assert saved is not None
    assert saved.legal_form == previous.legal_form is not None
    assert saved.imprint_representatives == previous.imprint_representatives
    assert saved.imprint_phone == previous.imprint_phone
    assert saved.imprint_register_number == "VR 1234"
    assert saved.imprint_vat_id == "DE123456789"
    assert saved.privacy_policy_text == previous.privacy_policy_text
    assert saved.member_privacy_notice_text == previous.member_privacy_notice_text


@pytest.mark.asyncio
async def test_sent_empty_values_clear_the_fields() -> None:
    repository = Repository(valid_draft())
    service = LegalConfigurationService(repository, production=False)  # type: ignore[arg-type]

    await service.save_draft(
        admin(),
        configuration=without_imprint(),
        expected_revision=2,
        request_id="req-legal-clear",
    )

    saved = repository.saved
    assert saved is not None
    assert saved.imprint_representatives is None
    assert saved.privacy_policy_text is None


def test_the_route_reports_omitted_fields_not_null_ones() -> None:
    body = {
        "expectedRevision": 2,
        "issuer": {
            "legalName": "Lions Hilfswerk Augsburg e.V.",
            "streetLine1": "Löwenweg 12",
            "postalCode": "86150",
            "city": "Augsburg",
            "taxIdentifier": "103/123/45678",
            "email": "rechnung@hilfswerk.test",
        },
        "bankAccountHolder": "Lions Hilfswerk Augsburg e.V.",
        "iban": "DE89370400440532013000",
        "taxTreatment": "tax_exempt",
        "taxRateBasisPoints": 0,
        "taxNote": "Steuerbefreit laut Prüfung.",
        "numberPrefix": "KT",
        "numberWidth": 5,
        "paymentTermsDays": 14,
        "publicOrderLegalBasis": "Vertragserfüllung der Bestellung.",
        "publicOrderNoticeText": "Wir verarbeiten die Daten nur zur Bestellung.",
        "consentTextVersion": "public-order-v1",
        "privacyContactEmail": "datenschutz@hilfswerk.test",
        "retention": {
            "invoiceDays": 3650,
            "commitmentDays": 3650,
            "contactDays": 730,
            "consentEvidenceDays": 3650,
            "auditDays": 3650,
        },
        "eInvoiceDecision": "pending",
        "taxEvidenceId": "STEUER-1",
        "privacyEvidenceId": "DATENSCHUTZ-1",
        # Sent explicitly as null: clear it.
        "imprintVatId": None,
    }
    request = SaveLegalConfigurationDraftRequest.model_validate(body)
    omitted = set(type(request).model_fields) - request.model_fields_set
    assert "imprint_phone" in omitted
    assert "privacy_policy_text" in omitted
    assert "imprint_vat_id" not in omitted
