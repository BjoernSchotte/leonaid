from __future__ import annotations

import json
from pathlib import Path

from pytest import raises

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identifiers import EntityId
from leonaid.domain.platform import PlatformIdentity

ROOT = Path(__file__).resolve().parents[2]


def test_entity_ids_accept_real_golden_domain_objects() -> None:
    dataset = json.loads(
        (ROOT / "tests/fixtures/golden/v1/dataset.json").read_text(encoding="utf-8")
    )

    values = (
        dataset["users"][0]["id"],
        dataset["actions"][0]["id"],
        dataset["companies"][0]["id"],
        dataset["invoices"][0]["id"],
    )

    assert [str(EntityId.parse(value)) for value in values] == list(values)


def test_entity_id_rejects_non_uuid4() -> None:
    with raises(DomainInvariantError) as captured:
        EntityId.parse("00000000-0000-0000-0000-000000000000")

    assert captured.value.code == "entity_id_version_invalid"


def test_platform_identity_enforces_stable_contract_versions() -> None:
    identity = PlatformIdentity(
        service="leonaid-api",
        release="0.0.0",
        api_version="v1",
    )

    assert identity.service == "leonaid-api"

    with raises(DomainInvariantError) as captured:
        PlatformIdentity(
            service="LeonAid API",
            release="next",
            api_version="latest",
        )

    assert captured.value.code == "service_name_invalid"
