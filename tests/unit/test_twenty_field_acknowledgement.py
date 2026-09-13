"""A failed Twenty response must neither duplicate a field nor hide schema drift."""

from unittest.mock import Mock

import pytest

from tools.seed.golden import SeedError
from tools.twenty.provision import Provisioner, SchemaDrift, TwentySchemaError


@pytest.mark.parametrize("outcome", ["committed", "missing", "drift", "forbidden"])
def test_field_response_failure_requires_declared_readback(monkeypatch, outcome):
    desired = {
        "name": "reference",
        "label": "Reference",
        "description": "External reference",
        "icon": "IconLink",
        "type": "TEXT",
        "isNullable": True,
        "isUnique": False,
    }
    provisioner = object.__new__(Provisioner)
    provisioner.manifest = {
        "objects": [{"nameSingular": "company", "fields": [desired]}]
    }
    monkeypatch.setattr(
        provisioner, "object_map", lambda: {"company": {"id": "company-id"}}
    )
    fields = []
    monkeypatch.setattr(
        provisioner, "object_details", lambda _: {"fieldsList": list(fields)}
    )
    error = SeedError(
        "Twenty GraphQL: Permission denied"
        if outcome == "forbidden"
        else "Twenty GraphQL: Could not find flat entity with universal identifier field-id"
    )

    def create_then_lose_response(*args):
        if outcome in {"committed", "drift"}:
            fields.append({**desired, "id": "field-id", "isActive": True})
            if outcome == "drift":
                fields[0]["type"] = "NUMBER"
        raise error

    mutation = Mock(side_effect=create_then_lose_response)
    monkeypatch.setattr(provisioner, "create_field", mutation)
    # Expire the existing bounded read wait immediately if nothing was committed.
    monkeypatch.setattr(
        "tools.twenty.provision.time.monotonic", Mock(side_effect=[0, 91])
    )
    if outcome == "committed":
        provisioner.ensure_fields()
    elif outcome == "drift":
        with pytest.raises(SchemaDrift, match="fields.reference.type"):
            provisioner.ensure_fields()
    elif outcome == "missing":
        with pytest.raises(TwentySchemaError, match="veröffentlichte Field nicht"):
            provisioner.ensure_fields()
    else:
        with pytest.raises(SeedError) as failure:
            provisioner.ensure_fields()
        assert failure.value is error
    assert mutation.call_count == 1
