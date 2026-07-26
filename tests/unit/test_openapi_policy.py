from __future__ import annotations

from typing import Any

from tools.openapi.breaking import breaking_changes, digest, is_approved
from tools.openapi.generate import generate_typescript


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


def test_client_generator_supports_json_body_and_encoded_path_parameter() -> None:
    contract = {
        "paths": {
            "/api/v1/examples": {
                "post": {
                    "operationId": "createExample",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ExampleRequest"
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ExampleResponse"
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/api/v1/examples/{example_id}": {
                "delete": {
                    "operationId": "deleteExample",
                    "parameters": [
                        {
                            "in": "path",
                            "name": "example_id",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ExampleResponse"
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/api/v1/examples/search": {
                "get": {
                    "operationId": "searchExamples",
                    "parameters": [
                        {
                            "in": "query",
                            "name": "q",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                        {
                            "in": "query",
                            "name": "limit",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ExampleResponse"
                                    }
                                }
                            }
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "ApiErrorDetail": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "requestId": {"type": "string"},
                    },
                    "required": ["code", "message", "requestId"],
                },
                "ApiErrorResponse": {
                    "type": "object",
                    "properties": {
                        "error": {"$ref": "#/components/schemas/ApiErrorDetail"}
                    },
                    "required": ["error"],
                },
                "ExampleRequest": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                "ExampleResponse": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            }
        },
    }

    generated = generate_typescript(contract)

    assert "body: ExampleRequest" in generated
    assert '"Content-Type": "application/json"' in generated
    assert "body: JSON.stringify(body)" in generated
    assert "exampleId: string" in generated
    assert "encodeURIComponent(String(exampleId))" in generated
    assert "queryParameters:" in generated
    assert "readonly q?: string" in generated
    assert 'searchParameters.set("q", String(queryParameters.q))' in generated
