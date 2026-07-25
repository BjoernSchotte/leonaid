#!/usr/bin/env python3
"""Reject unapproved breaking changes between two OpenAPI documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HTTP_METHODS = ("delete", "get", "head", "options", "patch", "post", "put")


def digest(document: dict[str, Any]) -> str:
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def schemas(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = document.get("components")
    raw = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): schema for name, schema in raw.items() if isinstance(schema, dict)
    }


def type_contract(schema: object) -> object:
    if not isinstance(schema, dict):
        return schema
    return {
        key: (
            [type_contract(item) for item in value]
            if isinstance(value, list)
            else type_contract(value)
            if isinstance(value, dict)
            else value
        )
        for key, value in schema.items()
        if key
        in {
            "$ref",
            "anyOf",
            "const",
            "enum",
            "format",
            "items",
            "oneOf",
            "type",
        }
    }


def breaking_changes(
    old: dict[str, Any],
    new: dict[str, Any],
) -> list[str]:
    changes: set[str] = set()
    old_paths = old.get("paths", {})
    new_paths = new.get("paths", {})
    if not isinstance(old_paths, dict) or not isinstance(new_paths, dict):
        return ["contract:paths-invalid"]
    for path, old_path_item in old_paths.items():
        if path not in new_paths:
            changes.add(f"path-removed:{path}")
            continue
        new_path_item = new_paths[path]
        if not isinstance(old_path_item, dict) or not isinstance(new_path_item, dict):
            changes.add(f"path-invalid:{path}")
            continue
        for method in HTTP_METHODS:
            old_operation = old_path_item.get(method)
            if not isinstance(old_operation, dict):
                continue
            new_operation = new_path_item.get(method)
            if not isinstance(new_operation, dict):
                changes.add(f"operation-removed:{method.upper()} {path}")
                continue
            if old_operation.get("operationId") != new_operation.get("operationId"):
                changes.add(f"operation-id-changed:{method.upper()} {path}")
            old_responses = old_operation.get("responses", {})
            new_responses = new_operation.get("responses", {})
            if isinstance(old_responses, dict) and isinstance(new_responses, dict):
                for status_code in old_responses:
                    if (
                        str(status_code).startswith("2")
                        and status_code not in new_responses
                    ):
                        changes.add(
                            f"success-response-removed:{method.upper()} {path} {status_code}"
                        )

    old_schemas = schemas(old)
    new_schemas = schemas(new)
    for name, old_schema in old_schemas.items():
        if name not in new_schemas:
            changes.add(f"schema-removed:{name}")
            continue
        new_schema = new_schemas[name]
        old_properties = old_schema.get("properties", {})
        new_properties = new_schema.get("properties", {})
        if not isinstance(old_properties, dict) or not isinstance(new_properties, dict):
            if type_contract(old_schema) != type_contract(new_schema):
                changes.add(f"schema-type-changed:{name}")
            continue
        for property_name, old_property in old_properties.items():
            if property_name not in new_properties:
                changes.add(f"property-removed:{name}.{property_name}")
            elif type_contract(old_property) != type_contract(
                new_properties[property_name]
            ):
                changes.add(f"property-type-changed:{name}.{property_name}")
        old_required = set(old_schema.get("required", []))
        new_required = set(new_schema.get("required", []))
        for property_name in new_required - old_required:
            changes.add(f"property-newly-required:{name}.{property_name}")
    return sorted(changes)


def is_approved(
    changes: list[str],
    old: dict[str, Any],
    new: dict[str, Any],
    approval_document: dict[str, Any],
) -> bool:
    approvals = approval_document.get("approvals")
    if not isinstance(approvals, list):
        return False
    expected_old = digest(old)
    expected_new = digest(new)
    for approval in approvals:
        if not isinstance(approval, dict):
            continue
        if (
            approval.get("oldSha256") == expected_old
            and approval.get("newSha256") == expected_new
            and approval.get("changes") == changes
            and isinstance(approval.get("rationale"), str)
            and str(approval["rationale"]).strip()
        ):
            return True
    return False


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} enthält kein JSON-Objekt.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("approvals", type=Path)
    arguments = parser.parse_args()
    old = load(arguments.old)
    new = load(arguments.new)
    changes = breaking_changes(old, new)
    if not changes:
        print("openapi-breaking: OK: keine brechende Änderung")
        return 0
    approvals = load(arguments.approvals)
    if is_approved(changes, old, new, approvals):
        print("openapi-breaking: OK: bewusst freigegeben: " + ", ".join(changes))
        return 0
    for change in changes:
        print(f"openapi-breaking: ERROR: {change}", file=sys.stderr)
    print(
        "openapi-breaking: FAILED: exakte Hashes, Änderungsliste und Begründung "
        "in der Approval-Datei erforderlich",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
