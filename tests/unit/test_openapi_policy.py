from __future__ import annotations

from typing import Any

from tools.openapi.breaking import breaking_changes, digest, is_approved


def document(
    *, include_name: bool = True, require_name: bool = False
) -> dict[str, Any]:
    properties: dict[str, object] = {"id": {"type": "string"}}
    if include_name:
        properties["name"] = {"type": "string"}
    required = ["id", "name"] if require_name else ["id"]
    return {
        "paths": {
            "/api/v1/example": {
                "get": {
                    "operationId": "getExample",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
        "components": {
            "schemas": {
                "Example": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        },
    }


def test_breaking_policy_detects_removed_and_newly_required_properties() -> None:
    old = document()
    without_name = document(include_name=False)
    required_name = document(require_name=True)

    assert breaking_changes(old, without_name) == ["property-removed:Example.name"]
    assert breaking_changes(old, required_name) == [
        "property-newly-required:Example.name"
    ]


def test_breaking_policy_requires_exact_hash_changes_and_rationale() -> None:
    old = document()
    new = document(include_name=False)
    changes = breaking_changes(old, new)
    approval = {
        "approvals": [
            {
                "oldSha256": "wrong",
                "newSha256": "wrong",
                "changes": changes,
                "rationale": "Bewusst für den Test.",
            }
        ]
    }

    assert is_approved(changes, old, new, approval) is False
    approval["approvals"][0]["oldSha256"] = digest(old)
    approval["approvals"][0]["newSha256"] = digest(new)
    assert is_approved(changes, old, new, approval) is True
