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
        raise SnapshotError(f"{path} muss ein JSON-Objekt enthalten")
    return value


def records_by_id(items: Any, label: str) -> dict[str, JsonObject]:
    if not isinstance(items, list):
        raise SnapshotError(f"{label} muss eine Liste sein")
    result: dict[str, JsonObject] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise SnapshotError(f"{label} enthält einen Datensatz ohne ID")
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
        raise SnapshotError("Dataset-Prüfsumme weicht von der Fixture ab")

    core = snapshot.get("core")
    if not isinstance(core, dict):
        raise SnapshotError("Core-Snapshot fehlt")
    if core.get("rowCount") != 1 or core.get("datasetSha256") != dataset_digest:
        raise SnapshotError("Core-Snapshot enthält nicht exakt Golden Data v1")
    if core.get("expectedCounts") != expected.get("counts"):
        raise SnapshotError("Core-Counts entsprechen nicht expected.json")
    collections = core.get("collections")
    if not isinstance(collections, dict):
        raise SnapshotError("Core-Collections fehlen")
    for name, count in expected["counts"].items():
        collection = collections.get(name)
        if not isinstance(collection, dict) or collection.get("count") != count:
            raise SnapshotError(f"Core-Count weicht ab: {name}")

    twenty = snapshot.get("twenty")
    if not isinstance(twenty, dict):
        raise SnapshotError("Twenty-Snapshot fehlt")
    actual_companies = records_by_id(twenty.get("companies"), "Twenty companies")
    expected_companies = records_by_id(dataset["companies"], "Golden companies")
    if set(actual_companies) != set(expected_companies):
        raise SnapshotError("Twenty-Company-IDs entsprechen nicht Golden Data")
    for record_id, company in expected_companies.items():
        actual = actual_companies[record_id]
        for key in ("name", "postalCode", "city"):
            if actual.get(key) != company.get(key):
                raise SnapshotError(f"Twenty-Company-Feld weicht ab: {record_id}.{key}")

    actual_people = records_by_id(twenty.get("people"), "Twenty people")
    expected_people = records_by_id(dataset["persons"], "Golden persons")
    if set(actual_people) != set(expected_people):
        raise SnapshotError("Twenty-Person-IDs entsprechen nicht Golden Data")
    for record_id, person in expected_people.items():
        actual = actual_people[record_id]
        expected_fields = {
            "givenName": person["givenName"],
            "familyName": person["familyName"],
            "email": person["email"],
            "companyId": person["companyId"],
        }
        if any(actual.get(key) != value for key, value in expected_fields.items()):
            raise SnapshotError(f"Twenty-Person-Felder weichen ab: {record_id}")

    rustfs = snapshot.get("rustfs")
    if not isinstance(rustfs, dict) or not isinstance(rustfs.get("objects"), list):
        raise SnapshotError("RustFS-Objekte fehlen")
    objects = rustfs["objects"]
    if len(objects) != len(dataset["invoices"]):
        raise SnapshotError("RustFS enthält nicht exakt ein PDF je Golden-Rechnung")
    core_documents = core.get("documentManifest")
    if not isinstance(core_documents, list):
        raise SnapshotError("Core-Dokumentmanifest fehlt")
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
                "RustFS enthält ein ungültiges PDF oder SHA-256-Metadatum"
            )
        core_document = core_document_by_key.get(str(item.get("objectKey")))
        if (
            not isinstance(core_document, dict)
            or core_document.get("storageVersionId") != item["storageVersionId"]
        ):
            raise SnapshotError(
                "RustFS-Version-ID und Core-Dokumentzuordnung sind inkonsistent"
            )

    if snapshot.get("mailpit") != {"total": 0, "messageIds": []}:
        raise SnapshotError("Mailpit ist nicht auf dem leeren Golden-Stand")


def verify_mutated(snapshot: JsonObject, fixture: Path) -> None:
    dataset = load(fixture / "dataset.json")
    core = snapshot.get("core")
    twenty = snapshot.get("twenty")
    rustfs = snapshot.get("rustfs")
    mailpit = snapshot.get("mailpit")
    if not isinstance(core, dict) or core.get("datasetSha256") != "0" * 64:
        raise SnapshotError("Core-Mutation ist nicht sichtbar")
    if not isinstance(twenty, dict):
        raise SnapshotError("Twenty-Mutation ist nicht sichtbar")
    companies = records_by_id(twenty.get("companies"), "Twenty companies")
    first_company = str(dataset["companies"][0]["id"])
    if companies[first_company].get("name") != "ABSICHTLICH MUTIERT":
        raise SnapshotError("Twenty-Mutation ist nicht sichtbar")
    if not isinstance(rustfs, dict) or not isinstance(rustfs.get("objects"), list):
        raise SnapshotError("RustFS-Mutation ist nicht sichtbar")
    first_object = rustfs["objects"][0]
    if (
        not isinstance(first_object, dict)
        or first_object.get("size", 0) >= 1_000
        or first_object.get("storedSha256") != first_object.get("sha256")
    ):
        raise SnapshotError("RustFS-Mutation ist nicht sichtbar")
    if not isinstance(mailpit, dict) or mailpit.get("total") != 1:
        raise SnapshotError("Mailpit-Mutation ist nicht sichtbar")


def verify_equivalent(first: JsonObject, second: JsonObject) -> None:
    if normalized_business_snapshot(first) != normalized_business_snapshot(second):
        raise SnapshotError(
            "fachlicher Snapshot wurde durch den vollständigen Reset nicht exakt "
            "wiederhergestellt"
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
