#!/usr/bin/env python3
"""Verify real-system POC-012 snapshots without contacting replacement systems."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]


class SnapshotError(RuntimeError):
    """The persisted snapshot does not prove the expected real state."""


def load(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SnapshotError(f"{path} must contain a JSON object")
    return value


def records_by_id(items: Any, label: str) -> dict[str, JsonObject]:
    if not isinstance(items, list):
        raise SnapshotError(f"{label} must be a list")
    result: dict[str, JsonObject] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise SnapshotError(f"{label} contains a record without ID")
        result[item["id"]] = item
    return result


def normalized_business_snapshot(value: Any) -> Any:
    """Remove only identifiers that RustFS regenerates after a volume reset."""
    if isinstance(value, dict):
        return {
            key: normalized_business_snapshot(item)
            for key, item in value.items()
            if key not in {"snapshotSha256", "storageVersionId"}
        }
    if isinstance(value, list):
        return [normalized_business_snapshot(item) for item in value]
    return value


def verify_golden(snapshot: JsonObject, fixture: Path) -> None:
    dataset = load(fixture / "dataset.json")
    expected = load(fixture / "expected.json")
    dataset_digest = hashlib.sha256((fixture / "dataset.json").read_bytes()).hexdigest()
    if snapshot.get("expectedDatasetSha256") != dataset_digest:
        raise SnapshotError("dataset checksum differs from the fixture")

    core = snapshot.get("core")
    if not isinstance(core, dict):
        raise SnapshotError("core snapshot missing")
    if core.get("rowCount") != 1 or core.get("datasetSha256") != dataset_digest:
        raise SnapshotError("core snapshot does not contain exactly Golden Data v1")
    if core.get("expectedCounts") != expected.get("counts"):
        raise SnapshotError("core counts do not match expected.json")
    collections = core.get("collections")
    if not isinstance(collections, dict):
        raise SnapshotError("core collections missing")
    for name, count in expected["counts"].items():
        collection = collections.get(name)
        if not isinstance(collection, dict) or collection.get("count") != count:
            raise SnapshotError(f"core count differs: {name}")

    twenty = snapshot.get("twenty")
    if not isinstance(twenty, dict):
        raise SnapshotError("Twenty snapshot missing")
    actual_companies = records_by_id(twenty.get("companies"), "Twenty companies")
    expected_companies = records_by_id(dataset["companies"], "Golden companies")
    if set(actual_companies) != set(expected_companies):
        raise SnapshotError("Twenty company IDs do not match Golden Data")
    for record_id, company in expected_companies.items():
        actual = actual_companies[record_id]
        for key in ("name", "postalCode", "city"):
            if actual.get(key) != company.get(key):
                raise SnapshotError(f"Twenty company field differs: {record_id}.{key}")

    actual_people = records_by_id(twenty.get("people"), "Twenty people")
    expected_people = records_by_id(dataset["persons"], "Golden persons")
    if set(actual_people) != set(expected_people):
        raise SnapshotError("Twenty person IDs do not match Golden Data")
    for record_id, person in expected_people.items():
        actual = actual_people[record_id]
        expected_fields = {
            "givenName": person["givenName"],
            "familyName": person["familyName"],
            "email": person["email"],
            "companyId": person["companyId"],
        }
        if any(actual.get(key) != value for key, value in expected_fields.items()):
            raise SnapshotError(f"Twenty person fields differ: {record_id}")

    rustfs = snapshot.get("rustfs")
    if not isinstance(rustfs, dict) or not isinstance(rustfs.get("objects"), list):
        raise SnapshotError("RustFS objects missing")
    objects = rustfs["objects"]
    if len(objects) != len(dataset["invoices"]):
        raise SnapshotError("RustFS does not contain exactly one PDF per golden invoice")
    core_documents = core.get("documentManifest")
    if not isinstance(core_documents, list):
        raise SnapshotError("core document manifest missing")
    core_document_by_key = {
        str(item.get("objectKey")): item
        for item in core_documents
        if isinstance(item, dict)
    }
    for item in objects:
        if (
            not isinstance(item, dict)
            or item.get("isPdf") is not True
            or item.get("contentType") != "application/pdf"
            or item.get("sha256") != item.get("storedSha256")
            or not isinstance(item.get("storageVersionId"), str)
            or not item["storageVersionId"]
            or not isinstance(item.get("size"), int)
            or item["size"] < 1_000
        ):
            raise SnapshotError(
                "RustFS contains an invalid PDF or SHA-256 metadata value"
            )
        core_document = core_document_by_key.get(str(item.get("objectKey")))
        if (
            not isinstance(core_document, dict)
            or core_document.get("storageVersionId") != item["storageVersionId"]
        ):
            raise SnapshotError(
                "RustFS version ID and core document mapping are inconsistent"
            )

    if snapshot.get("mailpit") != {"total": 0, "messageIds": []}:
        raise SnapshotError("Mailpit is not at the empty golden state")


def verify_mutated(snapshot: JsonObject, fixture: Path) -> None:
    dataset = load(fixture / "dataset.json")
    core = snapshot.get("core")
    twenty = snapshot.get("twenty")
    rustfs = snapshot.get("rustfs")
    mailpit = snapshot.get("mailpit")
    if not isinstance(core, dict) or core.get("datasetSha256") != "0" * 64:
        raise SnapshotError("core mutation is not visible")
    if not isinstance(twenty, dict):
        raise SnapshotError("Twenty mutation is not visible")
    companies = records_by_id(twenty.get("companies"), "Twenty companies")
    first_company = str(dataset["companies"][0]["id"])
    if companies[first_company].get("name") != "ABSICHTLICH MUTIERT":
        raise SnapshotError("Twenty mutation is not visible")
    if not isinstance(rustfs, dict) or not isinstance(rustfs.get("objects"), list):
        raise SnapshotError("RustFS mutation is not visible")
    first_object = rustfs["objects"][0]
    if (
        not isinstance(first_object, dict)
        or first_object.get("size", 0) >= 1_000
        or first_object.get("storedSha256") != first_object.get("sha256")
    ):
        raise SnapshotError("RustFS mutation is not visible")
    if not isinstance(mailpit, dict) or mailpit.get("total") != 1:
        raise SnapshotError("Mailpit mutation is not visible")


def verify_equivalent(first: JsonObject, second: JsonObject) -> None:
    if normalized_business_snapshot(first) != normalized_business_snapshot(second):
        raise SnapshotError(
            "full reset did not restore the business snapshot exactly"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("golden", "mutated", "equivalent"))
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("fixture", type=Path)
    arguments = parser.parse_args()
    try:
        value = load(arguments.snapshot)
        if arguments.mode == "golden":
            verify_golden(value, arguments.fixture)
        elif arguments.mode == "mutated":
            verify_mutated(value, arguments.fixture)
        else:
            verify_equivalent(value, load(arguments.fixture))
    except (OSError, json.JSONDecodeError, SnapshotError) as error:
        print(f"snapshot-check: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"snapshot-check: OK: {arguments.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
