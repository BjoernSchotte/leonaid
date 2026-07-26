from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from leonaid.application.crm import (
    CompanyData,
    CompanyRecord,
    PersonData,
    PersonRecord,
    PostalAddress,
)
from leonaid.application.sponsor_matching import (
    SponsorDraft,
    SponsorMatchStatus,
    candidate_company_query,
    company_matches,
    match_status,
    normalize_match_name,
    person_matches,
)

GOLDEN_DATASET = (
    Path(__file__).parents[1] / "fixtures" / "golden" / "v1" / "dataset.json"
)


def test_match_key_normalizes_unicode_legal_form_whitespace_and_case() -> None:
    variants = (
        "Bäckerei Sonnenseite KG",
        "  BAECKEREI   SONNENSEITE K.G. ",
        "Bäckerei\u0308 Sonnenseite kg",
    )

    assert {normalize_match_name(value) for value in variants} == {
        "baeckerei sonnenseite kg"
    }
    assert candidate_company_query(variants[0]) == "sonnenseite"
    assert normalize_match_name("Ångström & Söhne") == "angstroem soehne"


def test_draft_uses_company_or_full_person_name_as_the_only_match_key() -> None:
    company = SponsorDraft(
        company_name=" Löwen-Apotheke GmbH ",
        given_name="Andere",
        family_name="Kontaktperson",
        email="kontakt@example.invalid",
        postal_code="48143",
    )
    person = SponsorDraft(
        given_name=" Max ",
        family_name=" MUSTERMANN ",
        email="anderes-postfach@example.invalid",
    )

    assert company.normalized_key == "loewen apotheke gmbh"
    assert person.normalized_key == "max mustermann"
    assert company.postal_code == "48143"
    with pytest.raises(ValueError, match="Vorname und Nachname"):
        SponsorDraft(given_name="Nurvorname")
    with pytest.raises(ValueError, match="Firmenkontakt"):
        SponsorDraft(
            company_name="Löwen-Apotheke GmbH",
            email="kontakt@example.invalid",
        )


def test_match_status_is_explicit_for_zero_one_and_multiple_candidates() -> None:
    assert match_status(0) is SponsorMatchStatus.NO_MATCH
    assert match_status(1) is SponsorMatchStatus.SINGLE_MATCH
    assert match_status(2) is SponsorMatchStatus.AMBIGUOUS_MATCH
    with pytest.raises(ValueError, match="nicht negativ"):
        match_status(-1)


def test_golden_company_and_person_conflicts_match_only_the_primary_key() -> None:
    dataset = json.loads(GOLDEN_DATASET.read_text(encoding="utf-8"))
    companies = tuple(
        CompanyRecord(
            twenty_id=UUID(item["id"]),
            data=CompanyData(
                name=item["name"],
                address=PostalAddress(
                    postal_code=item["postalCode"],
                    city=item["city"],
                ),
            ),
        )
        for item in dataset["companies"]
    )
    people = tuple(
        PersonRecord(
            twenty_id=UUID(item["id"]),
            data=PersonData(
                given_name=item["givenName"],
                family_name=item["familyName"],
                email=item["email"],
                company_twenty_id=(
                    UUID(item["companyId"]) if item["companyId"] is not None else None
                ),
            ),
        )
        for item in dataset["persons"]
    )
    company_scenario, person_scenario = dataset["matchScenarios"]

    company_result = company_matches(
        companies,
        company_scenario["normalizedKey"],
    )
    person_key = normalize_match_name(
        f"{person_scenario['input']['givenName']} "
        f"{person_scenario['input']['familyName']}"
    )
    person_result = person_matches(people, person_key)

    assert [str(item.twenty_id) for item in company_result] == (
        company_scenario["expectedCompanyIds"]
    )
    assert {str(item.twenty_id) for item in person_result} == set(
        person_scenario["expectedPersonIds"]
    )
    assert match_status(len(company_result)) is SponsorMatchStatus.SINGLE_MATCH
    assert match_status(len(person_result)) is SponsorMatchStatus.AMBIGUOUS_MATCH
