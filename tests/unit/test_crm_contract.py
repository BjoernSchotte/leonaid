from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyGatewaySettings, _contains_filter
from leonaid.application.crm import (
    CompanyData,
    CompanyUpdate,
    CrmGatewayError,
    CrmSyncStatus,
    PersonData,
    PersonUpdate,
    PostalAddress,
)


def test_semantic_crm_values_normalize_and_reject_uncontrolled_updates() -> None:
    company = CompanyData(
        "  Löwen Apotheke  ",
        PostalAddress(postal_code=" 48143 ", city=" Münster "),
    )
    person = PersonData("  Sophie ", " Sponsor ", " sophie@example.invalid ")

    assert company.name == "Löwen Apotheke"
    assert company.address.postal_code == "48143"
    assert company.address.city == "Münster"
    assert person.given_name == "Sophie"
    assert person.email == "sophie@example.invalid"

    with pytest.raises(ValueError, match="mindestens ein Feld"):
        CompanyUpdate()
    with pytest.raises(ValueError, match="mindestens ein Feld"):
        PersonUpdate()
    with pytest.raises(ValueError, match="ungültig"):
        PersonData("Sophie", "Sponsor", "kein-at")


def test_twenty_configuration_enforces_pinned_operational_limits() -> None:
    settings = TwentyGatewaySettings(
        base_url="http://twenty-server:3000",
        api_key=SecretStr("real-but-local-test-value"),
        page_size=60,
        requests_per_minute=100,
    )

    assert settings.page_size == 60
    assert "real-but-local-test-value" not in repr(settings)

    with pytest.raises(ValueError, match="page_size"):
        TwentyGatewaySettings(
            base_url="http://twenty-server:3000",
            api_key=SecretStr("key"),
            page_size=61,
        )
    with pytest.raises(ValueError, match="zwischen 1 und 100"):
        TwentyGatewaySettings(
            base_url="http://twenty-server:3000",
            api_key=SecretStr("key"),
            requests_per_minute=101,
        )


def test_filter_encoding_and_gateway_error_are_secret_safe() -> None:
    hostile = 'Acme",name[eq]:"Injected'
    expression = _contains_filter("name", hostile)
    assert expression == 'name[ilike]:"%Acme\\",name[eq]:\\"Injected%"'

    error = CrmGatewayError(
        "crm_unavailable",
        "Twenty ist derzeit nicht erreichbar.",
        operation="update_company",
        correlation_id="poc031:unit",
        retryable=True,
        outcome_unknown=True,
        leonaid_id=UUID("71000000-0000-4000-8000-000000000001"),
        twenty_id=UUID("72000000-0000-4000-8000-000000000001"),
    )
    assert error.sync_status is CrmSyncStatus.OUTCOME_UNKNOWN
    assert error.retryable is True
    assert error.correlation_id == "poc031:unit"
    assert "Bearer" not in str(error)
