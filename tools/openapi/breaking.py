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


LOWER_BOUNDS = {"minLength", "minimum", "exclusiveMinimum", "minItems"}
UPPER_BOUNDS = {"maxLength", "maximum", "exclusiveMaximum", "maxItems"}


def constraints(schema: object, at: str = "") -> dict[str, object]:
    """Bounds and patterns by position, through anyOf/oneOf/allOf/items."""
    if isinstance(schema, list):
        return {
            key: value
            for index, item in enumerate(schema)
            for key, value in constraints(item, f"{at}/{index}").items()
        }
    if not isinstance(schema, dict):
        return {}
    found: dict[str, object] = {
        f"{at}/{key}": value
        for key, value in schema.items()
        if key in LOWER_BOUNDS | UPPER_BOUNDS | {"pattern"}
    }
    for key in ("anyOf", "oneOf", "allOf", "items"):
        found.update(constraints(schema.get(key), f"{at}/{key}"))
    return found


def tightened(old: object, new: object) -> bool:
    before, after = constraints(old), constraints(new)
    for position, value in after.items():
        keyword = position.rsplit("/", 1)[1]
        if position not in before:
            return True
        previous = before[position]
        if keyword == "pattern":
            if value != previous:
                return True
        elif not isinstance(value, (int, float)) or not isinstance(
            previous, (int, float)
        ):
            return True
        elif keyword in LOWER_BOUNDS and value > previous:
            return True
        elif keyword in UPPER_BOUNDS and value < previous:
            return True
    return False


def parameters(operation: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    raw = operation.get("parameters", [])
    return {
        (str(item.get("in")), str(item.get("name"))): item
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict)
    }


def parameter_changes(
    label: str, old_operation: dict[str, Any], new_operation: dict[str, Any]
) -> set[str]:
    """Query, path and header parameters a caller already sends.

    Breaking: a new required parameter, a parameter that became required,
    a changed type or enum, and a tightened bound or pattern.
    """
    changes: set[str] = set()
    old = parameters(old_operation)
    for key, parameter in parameters(new_operation).items():
        where = f"{label} {key[0]}:{key[1]}"
        before = old.get(key)
        if before is None:
            if parameter.get("required") is True:
                changes.add(f"parameter-newly-required:{where}")
            continue
        if parameter.get("required") is True and before.get("required") is not True:
            changes.add(f"parameter-newly-required:{where}")
        if type_contract(before.get("schema")) != type_contract(
            parameter.get("schema")
        ):
            changes.add(f"parameter-type-changed:{where}")
        elif tightened(before.get("schema"), parameter.get("schema")):
            changes.add(f"parameter-constraint-tightened:{where}")
    return changes


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
            changes.update(
                parameter_changes(
                    f"{method.upper()} {path}", old_operation, new_operation
                )
            )
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
            elif tightened(old_property, new_properties[property_name]):
                changes.add(f"property-constraint-tightened:{name}.{property_name}")
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
        raise ValueError(f"{path} does not contain a JSON object.")
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
        print("openapi-breaking: OK: no breaking change")
        return 0
    approvals = load(arguments.approvals)
    if is_approved(changes, old, new, approvals):
        print("openapi-breaking: OK: explicitly approved: " + ", ".join(changes))
        return 0
    for change in changes:
        print(f"openapi-breaking: ERROR: {change}", file=sys.stderr)
    print(
        "openapi-breaking: FAILED: approval file requires exact hashes, change list "
        "and rationale",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
