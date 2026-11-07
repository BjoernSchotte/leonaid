"""The public Impressum endpoint exposes only the carrier's contact data."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Response

from leonaid.domain.legal_configuration import LegalConfigurationVersion
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.entrypoints.fastapi.routes import (
    get_public_legal_notice,
    get_public_privacy_policy,
)

from .test_legal_configuration import MEMBER_NOTICE, PRIVACY_POLICY, valid_draft


class ActiveConfiguration:
    def __init__(self, version: LegalConfigurationVersion | None) -> None:
        self.version = version

    async def active_configuration(self) -> LegalConfigurationVersion | None:
        return self.version


def request_with(version: LegalConfigurationVersion | None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                legal_configuration_service=ActiveConfiguration(version)
            )
        )
    )


def active_version() -> LegalConfigurationVersion:
    return LegalConfigurationVersion(
        id=uuid4(),
        version=1,
        configuration=valid_draft(),
        created_by_user_id=uuid4(),
        created_by_display_name="Simone System",
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_active_configuration_names_the_provider_only() -> None:
    response = Response()
    notice = await get_public_legal_notice(
        request_with(active_version()),  # type: ignore[arg-type]
        response,
    )
    body = notice.model_dump(by_alias=True)
    assert body == {
        "provider": {
            "legalName": "Lions Hilfswerk Augsburg e.V.",
            "streetLine1": "Löwenweg 12",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "email": "rechnung@hilfswerk.test",
            "phone": "+49 821 123456",
            "representatives": "Vorstand: Erika Muster (Präsidentin)",
            "registerCourt": "Amtsgericht Augsburg",
            "registerNumber": "VR 1234",
            "vatId": None,
            "contentResponsibleName": None,
            "contentResponsibleAddress": None,
        }
    }
    # Tax, bank and evidence data never leave the configuration.
    text = notice.model_dump_json()
    for secret in ("DE123456789", "DE89", "COBADEFFXXX", "TAX-2026-001"):
        assert secret not in text
    assert response.headers["Cache-Control"].startswith("public, max-age=60")


@pytest.mark.asyncio
async def test_without_active_configuration_there_is_no_provider() -> None:
    notice = await get_public_legal_notice(
        request_with(None),  # type: ignore[arg-type]
        Response(),
    )
    assert notice.model_dump(by_alias=True) == {"provider": None}


def test_openapi_declares_the_public_legal_notice() -> None:
    document = create_app().openapi()
    operation = document["paths"]["/api/v1/public/legal-notice"]["get"]
    assert operation["operationId"] == "getPublicLegalNotice"
    assert "security" not in operation or operation["security"] == []
    provider = document["components"]["schemas"]["PublicLegalProviderResponse"]
    assert set(provider["properties"]) == {
        "legalName",
        "streetLine1",
        "postalCode",
        "city",
        "countryCode",
        "email",
        "phone",
        "representatives",
        "registerCourt",
        "registerNumber",
        "vatId",
        "contentResponsibleName",
        "contentResponsibleAddress",
    }
    # New fields stay optional: older clients and versions keep working.
    assert set(provider.get("required", [])) == {
        "legalName",
        "streetLine1",
        "postalCode",
        "city",
        "countryCode",
        "email",
    }
    privacy = document["paths"]["/api/v1/public/privacy-policy"]["get"]
    assert privacy["operationId"] == "getPublicPrivacyPolicy"
    assert "security" not in privacy or privacy["security"] == []


@pytest.mark.asyncio
async def test_privacy_policy_carries_the_active_texts_only() -> None:
    response = Response()
    policy = await get_public_privacy_policy(
        request_with(active_version()),  # type: ignore[arg-type]
        response,
    )
    body = policy.model_dump(by_alias=True)
    content = body["policy"]
    assert content["version"] == 1
    assert content["controller"]["legalName"] == "Lions Hilfswerk Augsburg e.V."
    assert content["privacyContactEmail"] == "datenschutz@hilfswerk.test"
    assert content["policyText"] == PRIVACY_POLICY
    assert content["memberNoticeText"] == MEMBER_NOTICE
    assert content["orderNoticeText"].startswith("Die Daten werden")
    assert content["orderLegalBasis"].startswith("Verarbeitung zur")
    text = policy.model_dump_json()
    for secret in ("DE123456789", "DE89", "COBADEFFXXX", "PRIVACY-2026-001"):
        assert secret not in text
    assert response.headers["Cache-Control"].startswith("public, max-age=60")


@pytest.mark.asyncio
async def test_without_active_configuration_there_is_no_privacy_policy() -> None:
    policy = await get_public_privacy_policy(
        request_with(None),  # type: ignore[arg-type]
        Response(),
    )
    assert policy.model_dump(by_alias=True) == {"policy": None}
