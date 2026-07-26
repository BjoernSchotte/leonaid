from __future__ import annotations

from pathlib import Path

from tools.twenty.import_contacts import (
    candidate_company_query,
    load_mapping,
    load_rows,
    normalize_name,
)

ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = (
    ROOT
    / "tests/fixtures/golden/v1/outputs"
    / "019f9a37-b6da-7521-b590-ec1e8215a6bf"
    / "leonaid-crm-import.xlsx"
)
MAPPING = ROOT / "infra/twenty/import-mapping.json"
CSV_FIXTURE = ROOT / "tests/fixtures/golden/v1/import" / "leonaid-crm-import.csv"


def test_company_normalization_covers_unicode_case_and_whitespace() -> None:
    variants = (
        "Bäckerei Sonnenseite K.G.",
        "  BAECKEREI   Sonnenseite KG ",
        "Ba\u0308ckerei Sonnenseite K.G.",
    )
    assert {normalize_name(value) for value in variants} == {"baeckerei sonnenseite kg"}
    assert candidate_company_query(variants[0]) == "sonnenseite"


def test_golden_workbook_is_read_as_typed_real_xlsx() -> None:
    mapping = load_mapping(MAPPING)
    initial = load_rows(WORKBOOK, "Kontakte", mapping)
    update = load_rows(WORKBOOK, "Kontakte Update", mapping)

    assert len(initial) == 4
    assert len(update) == 4
    assert initial[0].company_name == "Nordstern Handel GmbH"
    assert initial[0].postal_code == "48155"
    assert update[0].postal_code == "48157"
    assert update[0].city == "Münster-Ost"
    assert initial[2].given_name == "Max"
    assert initial[2].validation_errors == ()
    assert initial[3].validation_errors == ("family_name fehlt für PERSON",)


def test_golden_semicolon_csv_uses_the_same_mapping() -> None:
    mapping = load_mapping(MAPPING)
    rows = load_rows(CSV_FIXTURE, "ignored-for-csv", mapping)

    assert len(rows) == 4
    assert rows[0].company_name == "Nordstern Handel GmbH"
    assert rows[0].postal_code == "48155"
    assert rows[2].given_name == "Max"
    assert rows[3].validation_errors == ("family_name fehlt für PERSON",)
