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


def camel_identifier(value: str) -> str:
    parts = value.split("_")
    candidate = parts[0] + "".join(part.capitalize() for part in parts[1:])
    if not IDENTIFIER.fullmatch(candidate):
        raise GenerationError(f"Parametername ist kein TypeScript-Identifier: {value}")
    return candidate


def path_parameters(
    path: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
) -> list[tuple[str, str, str]]:
    combined: list[Any] = []
    for source in (path_item.get("parameters", []), operation.get("parameters", [])):
        if not isinstance(source, list):
            raise GenerationError("parameters muss eine Liste sein.")
        combined.extend(source)
    result: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for parameter in combined:
        if not isinstance(parameter, dict):
            raise GenerationError("Ungültiger OpenAPI-Parameter.")
        location = parameter.get("in")
        if location == "query":
            continue
        name = parameter.get("name")
        schema = parameter.get("schema")
        if (
            location != "path"
            or not isinstance(name, str)
            or not isinstance(schema, dict)
            or parameter.get("required") is not True
        ):
            raise GenerationError("Nur erforderliche Pfadparameter werden unterstützt.")
        if name in seen:
            raise GenerationError(f"Doppelter Pfadparameter: {name}")
        seen.add(name)
        result.append((name, camel_identifier(name), ts_type(schema)))
    placeholders = set(re.findall(r"\{([^{}]+)\}", path))
    if placeholders != seen:
        raise GenerationError(
            f"Pfadparameter stimmen nicht mit dem Pfad überein: {path}"
        )
    return result


def query_parameters(
    path_item: dict[str, Any],
    operation: dict[str, Any],
) -> list[tuple[str, str, str, bool]]:
    combined: list[Any] = []
    for source in (path_item.get("parameters", []), operation.get("parameters", [])):
        if not isinstance(source, list):
            raise GenerationError("parameters muss eine Liste sein.")
        combined.extend(source)
    result: list[tuple[str, str, str, bool]] = []
    seen: set[str] = set()
    for parameter in combined:
        if not isinstance(parameter, dict):
            raise GenerationError("Ungültiger OpenAPI-Parameter.")
        location = parameter.get("in")
        if location == "path":
            continue
        name = parameter.get("name")
        schema = parameter.get("schema")
        if (
            location != "query"
            or not isinstance(name, str)
            or not isinstance(schema, dict)
        ):
            raise GenerationError(
                "Nur Pfad- und skalare Query-Parameter werden unterstützt."
            )
        if name in seen:
            raise GenerationError(f"Doppelter Query-Parameter: {name}")
        seen.add(name)
        parameter_type = ts_type(schema)
        if parameter_type.startswith(("Array<", "{ ", "Record<")):
            raise GenerationError(f"Query-Parameter ist nicht skalar: {name}")
        result.append(
            (
                name,
                camel_identifier(name),
                parameter_type,
                parameter.get("required") is True,
            )
        )
    return result


def query_parameter_type(
    parameters: list[tuple[str, str, str, bool]],
) -> str:
    fields = []
    for original, _identifier, parameter_type, required in parameters:
        key = original if IDENTIFIER.fullmatch(original) else json.dumps(original)
        optional = "" if required else "?"
        fields.append(f"readonly {key}{optional}: {parameter_type};")
    return "{ " + " ".join(fields) + " }"


def request_body_type(operation: dict[str, Any]) -> str | None:
    request_body = operation.get("requestBody")
    if request_body is None:
        return None
    if not isinstance(request_body, dict) or request_body.get("required") is not True:
        raise GenerationError(
            "Nur erforderliche JSON-Request-Bodies werden unterstützt."
        )
    content = request_body.get("content")
    if not isinstance(content, dict):
        raise GenerationError("RequestBody ohne content.")
    media = content.get("application/json")
    if not isinstance(media, dict) or not isinstance(media.get("schema"), dict):
        raise GenerationError("RequestBody ohne JSON-Schema.")
    return ts_type(media["schema"])


def path_expression(
    path: str,
    parameters: list[tuple[str, str, str]],
) -> str:
    if not parameters:
        return json.dumps(path)
    value = path
    for original, identifier, _parameter_type in parameters:
        value = value.replace(
            "{" + original + "}",
            "${encodeURIComponent(String(" + identifier + "))}",
        )
    return f"`{value}`"


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
            parameters = path_parameters(path, path_item, operation)
            query = query_parameters(path_item, operation)
            if any(identifier == "queryParameters" for _, identifier, _ in parameters):
                raise GenerationError(
                    "Pfadparameter kollidiert mit generiertem Query-Objekt."
                )
            body_type = request_body_type(operation)
            result_type = response_type(operation)
            arguments = [
                f"    {identifier}: {parameter_type},"
                for _original, identifier, parameter_type in parameters
            ]
            if body_type is not None:
                arguments.append(f"    body: {body_type},")
            if query:
                required_query = any(required for *_rest, required in query)
                default = "" if required_query else " = {}"
                arguments.append(
                    f"    queryParameters: {query_parameter_type(query)}{default},"
                )
            arguments.append("    options: RequestOptions = {},")
            init_lines = [f"      {{ method: {json.dumps(method.upper())} }},"]
            if body_type is not None:
                init_lines = [
                    "      {",
                    f"        method: {json.dumps(method.upper())},",
                    '        headers: { "Content-Type": "application/json" },',
                    "        body: JSON.stringify(body),",
                    "      },",
                ]
            request_path = path_expression(path, parameters)
            query_lines: list[str] = []
            if query:
                query_lines = [
                    "    const searchParameters = new URLSearchParams();",
                    *(
                        line
                        for original, identifier, _parameter_type, _required in query
                        for line in (
                            f"    if (queryParameters.{identifier} !== undefined "
                            f"&& queryParameters.{identifier} !== null) {{",
                            "      searchParameters.set("
                            f"{json.dumps(original)}, "
                            f"String(queryParameters.{identifier}));",
                            "    }",
                        )
                    ),
                    "    const queryString = searchParameters.toString();",
                    f"    const requestPath = {request_path} "
                    '+ (queryString ? `?${queryString}` : "");',
                ]
                request_path = "requestPath"
            lines.extend(
                [
                    "",
                    f"  async {operation_id}(",
                    *arguments,
                    f"  ): Promise<{result_type}> {{",
                    *query_lines,
                    f"    return this.request<{result_type}>(",
                    f"      {request_path},",
                    *init_lines,
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
        "  constructor(baseUrl: string, fetcher?: FetchLike) {",
        '    this.#baseUrl = baseUrl.replace(/\\/$/, "");',
        "    this.#fetch = fetcher ?? globalThis.fetch.bind(globalThis);",
        "  }",
        "",
        "  async request<T>(",
        "    path: string,",
        "    init: RequestInit,",
        "    options: RequestOptions = {},",
        "  ): Promise<T> {",
        "    const response = await this.#fetch(`${this.#baseUrl}${path}`, {",
        "      ...init,",
        "      headers: {",
        '        Accept: "application/json",',
        "        ...(init.headers as Readonly<Record<string, string>> | undefined),",
        "        ...options.headers,",
        "      },",
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
