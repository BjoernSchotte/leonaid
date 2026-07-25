#!/usr/bin/env python3
"""Generate the canonical OpenAPI document and a dependency-free TS client."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from leonaid.entrypoints.fastapi.platform import app

HTTP_METHODS = ("delete", "get", "head", "options", "patch", "post", "put")
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


class GenerationError(RuntimeError):
    """The OpenAPI contract cannot be represented by the current generator."""


def canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def ref_name(reference: str) -> str:
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise GenerationError(f"Nicht unterstützte Referenz: {reference}")
    return reference.removeprefix(prefix)


def literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def ts_type(schema: dict[str, Any]) -> str:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return ref_name(reference)
    variants = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(variants, list):
        return " | ".join(
            ts_type(variant) for variant in variants if isinstance(variant, dict)
        )
    if "const" in schema:
        return literal(schema["const"])
    values = schema.get("enum")
    if isinstance(values, list) and values:
        return " | ".join(literal(value) for value in values)
    schema_type = schema.get("type")
    if schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise GenerationError("Array-Schema ohne items.")
        return f"Array<{ts_type(items)}>"
    if schema_type == "object" or "properties" in schema:
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"Record<string, {ts_type(additional)}>"
        properties = schema.get("properties", {})
        if not isinstance(properties, dict) or not properties:
            return "Record<string, unknown>"
        required = set(schema.get("required", []))
        fields = []
        for name in sorted(properties):
            property_schema = properties[name]
            if not isinstance(property_schema, dict):
                raise GenerationError(f"Ungültiges Property-Schema: {name}")
            key = name if IDENTIFIER.fullmatch(name) else json.dumps(name)
            optional = "" if name in required else "?"
            fields.append(f"readonly {key}{optional}: {ts_type(property_schema)};")
        return "{ " + " ".join(fields) + " }"
    return {
        "boolean": "boolean",
        "integer": "number",
        "null": "null",
        "number": "number",
        "string": "string",
    }.get(str(schema_type), "unknown")


def response_type(operation: dict[str, Any]) -> str:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        raise GenerationError("Operation ohne responses.")
    for status_code in sorted(responses):
        if not str(status_code).startswith("2"):
            continue
        response = responses[status_code]
        if not isinstance(response, dict):
            continue
        content = response.get("content")
        if not isinstance(content, dict):
            return "void"
        media = content.get("application/json")
        if not isinstance(media, dict) or not isinstance(media.get("schema"), dict):
            raise GenerationError("Erfolgsantwort ohne JSON-Schema.")
        return ts_type(media["schema"])
    raise GenerationError("Operation ohne 2xx-Antwort.")


def model_lines(document: dict[str, Any]) -> list[str]:
    components = document.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, dict) else {}
    if not isinstance(schemas, dict):
        raise GenerationError("components.schemas fehlt.")
    lines: list[str] = []
    for name in sorted(schemas):
        schema = schemas[name]
        if not isinstance(schema, dict):
            raise GenerationError(f"Ungültiges Schema: {name}")
        lines.append(f"export type {name} = {ts_type(schema)};")
    return lines


def operation_lines(document: dict[str, Any]) -> list[str]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise GenerationError("paths fehlt.")
    seen: set[str] = set()
    lines: list[str] = []
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not IDENTIFIER.fullmatch(
                operation_id
            ):
                raise GenerationError(f"Ungültige operationId für {method} {path}.")
            if operation_id in seen:
                raise GenerationError(f"Doppelte operationId: {operation_id}")
            seen.add(operation_id)
            if operation.get("parameters") or operation.get("requestBody"):
                raise GenerationError(
                    f"{operation_id}: Parameter/RequestBody noch nicht unterstützt."
                )
            result_type = response_type(operation)
            lines.extend(
                [
                    "",
                    f"  async {operation_id}(",
                    "    options: RequestOptions = {},",
                    f"  ): Promise<{result_type}> {{",
                    f"    return this.request<{result_type}>(",
                    f"      {json.dumps(path)},",
                    f"      {{ method: {json.dumps(method.upper())} }},",
                    "      options,",
                    "    );",
                    "  }",
                ]
            )
    if not seen:
        raise GenerationError("Keine API-Operationen gefunden.")
    return lines


def generate_typescript(document: dict[str, Any]) -> str:
    lines = [
        "/* eslint-disable */",
        "// Generated by tools/openapi/generate.py. Do not edit.",
        "",
        *model_lines(document),
        "",
        "export type FetchLike = (",
        "  input: RequestInfo | URL,",
        "  init?: RequestInit,",
        ") => Promise<Response>;",
        "",
        "export interface RequestOptions {",
        "  readonly signal?: AbortSignal;",
        "  readonly headers?: Readonly<Record<string, string>>;",
        "}",
        "",
        "export class ApiError extends Error {",
        "  readonly status: number;",
        "  readonly detail: ApiErrorDetail;",
        "",
        "  constructor(status: number, detail: ApiErrorDetail) {",
        "    super(detail.message);",
        '    this.name = "ApiError";',
        "    this.status = status;",
        "    this.detail = detail;",
        "  }",
        "}",
        "",
        "export class LeonAidApiClient {",
        "  readonly #baseUrl: string;",
        "  readonly #fetch: FetchLike;",
        "",
        "  constructor(baseUrl: string, fetcher: FetchLike = globalThis.fetch) {",
        '    this.#baseUrl = baseUrl.replace(/\\/$/, "");',
        "    this.#fetch = fetcher;",
        "  }",
        "",
        "  async request<T>(",
        "    path: string,",
        "    init: RequestInit,",
        "    options: RequestOptions = {},",
        "  ): Promise<T> {",
        "    const response = await this.#fetch(`${this.#baseUrl}${path}`, {",
        "      ...init,",
        '      headers: { Accept: "application/json", ...options.headers },',
        "      signal: options.signal,",
        "    });",
        "    const body = await response.json() as unknown;",
        "    if (!response.ok) {",
        "      if (isApiErrorResponse(body)) {",
        "        throw new ApiError(response.status, body.error);",
        "      }",
        "      throw new Error(`LeonAid API returned HTTP ${response.status}`);",
        "    }",
        "    return body as T;",
        "  }",
        *operation_lines(document),
        "}",
        "",
        "function isApiErrorResponse(value: unknown): value is ApiErrorResponse {",
        '  if (typeof value !== "object" || value === null || !("error" in value)) {',
        "    return false;",
        "  }",
        "  const error = value.error;",
        '  return typeof error === "object" && error !== null',
        '    && "code" in error && typeof error.code === "string"',
        '    && "message" in error && typeof error.message === "string"',
        '    && "requestId" in error && typeof error.requestId === "string";',
        "}",
        "",
    ]
    return "\n".join(lines)


def generated_files(root: Path) -> dict[Path, str]:
    document = app.openapi()
    output = root / "packages/api-client"
    return {
        output / "openapi.json": canonical_json(document),
        output / "src/generated.ts": generate_typescript(document),
    }


def write_or_check(root: Path, *, check: bool) -> None:
    differences: list[str] = []
    for path, content in generated_files(root).items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                differences.append(str(path.relative_to(root)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if differences:
        raise GenerationError(
            "Generierte API-Artefakte sind veraltet: " + ", ".join(differences)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    try:
        write_or_check(arguments.root.resolve(), check=arguments.check)
    except GenerationError as error:
        print(f"openapi-generate: ERROR: {error}", file=sys.stderr)
        return 1
    mode = "aktuell" if arguments.check else "geschrieben"
    print(f"openapi-generate: OK: OpenAPI und TypeScript-Client {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
