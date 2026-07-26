#!/usr/bin/env python3
"""Reject server-side test doubles and response-substitution libraries."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

FORBIDDEN_PACKAGES = {
    "fetch-mock",
    "httpretty",
    "mock",
    "mock-service-worker",
    "mockttp",
    "msw",
    "nock",
    "pytest-mock",
    "responses",
    "respx",
    "sinon",
    "vcrpy",
}
FORBIDDEN_IMPORT_ROOTS = {
    "httpretty",
    "mock",
    "pytest_mock",
    "responses",
    "respx",
    "unittest.mock",
    "vcr",
}
DOUBLE_PREFIXES = ("Fake", "Mock", "Spy", "Stub")
IO_PORT_SUFFIXES = ("Gateway", "Repository", "Store", "Transport")
FORBIDDEN_NETWORK_MARKERS = {
    "context.route(": "Browser-Netzwerkinterception",
    "jest.mock(": "Modulersatz",
    "mock.module(": "Modulersatz",
    "page.route(": "Browser-Netzwerkinterception",
    "route.fulfill(": "ersetzte Serverantwort",
    "vi.mock(": "Modulersatz",
}
HTTP_FIXTURE_PARTS = {
    "cassettes",
    "http-fixture",
    "http-fixtures",
    "http_fixture",
    "http_fixtures",
}


def dependency_names(root: Path) -> set[str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    groups = pyproject.get("dependency-groups", {})
    values: list[Any] = []
    if isinstance(project, dict):
        values.extend(project.get("dependencies", []))
    if isinstance(groups, dict):
        for group in groups.values():
            if isinstance(group, list):
                values.extend(group)
    result = {
        str(value).split(";", 1)[0].split("[", 1)[0].split("=", 1)[0].casefold()
        for value in values
    }
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if isinstance(package, dict):
        for section in ("dependencies", "devDependencies"):
            dependencies = package.get(section, {})
            if isinstance(dependencies, dict):
                result.update(str(name).casefold() for name in dependencies)
    return result


def python_problems(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        return [f"{path}: ungültiges Python: {error}"]
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            if any(
                name == root or name.startswith(f"{root}.")
                for root in FORBIDDEN_IMPORT_ROOTS
            ):
                problems.append(
                    f"{path}:{getattr(node, 'lineno', 1)}: verbotener Import {name}"
                )
        if isinstance(node, ast.ClassDef) and node.name.startswith(DOUBLE_PREFIXES):
            if node.name.endswith(IO_PORT_SUFFIXES):
                problems.append(
                    f"{path}:{node.lineno}: Testimplementierung eines I/O-Ports "
                    f"{node.name}"
                )
    return problems


def text_problems(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for package in FORBIDDEN_PACKAGES:
        for marker in (
            f'from "{package}"',
            f"from '{package}'",
            f'require("{package}")',
            f"require('{package}')",
        ):
            if marker in text:
                problems.append(
                    f"{path}: verbotene Response-/Mock-Bibliothek {package}"
                )
                break
    for marker, label in FORBIDDEN_NETWORK_MARKERS.items():
        if marker in text:
            problems.append(f"{path}: {label} ist in Systemtests verboten ({marker})")
    for match in re.finditer(
        r"\bclass\s+((?:Fake|Mock|Spy|Stub)\w+(?:Gateway|Repository|Store|Transport))\b",
        text,
    ):
        problems.append(f"{path}: Testimplementierung eines I/O-Ports {match.group(1)}")
    return problems


def fixture_problem(path: Path) -> str | None:
    parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    if parts & HTTP_FIXTURE_PARTS or name.endswith((".har", ".har.zip")):
        return f"{path}: versionierte HTTP-Fixture-Datei ist verboten"
    return None


def check(root: Path) -> list[str]:
    problems = [
        f"Direktabhängigkeit {name} ist als Mock-/Fake-Bibliothek verboten."
        for name in sorted(dependency_names(root) & FORBIDDEN_PACKAGES)
    ]
    for path in sorted((root / "tests").rglob("*.py")):
        problems.extend(python_problems(path))
    for base in ("tests", "apps", "packages"):
        for path in sorted((root / base).rglob("*")):
            if not path.is_file():
                continue
            fixture = fixture_problem(path)
            if fixture is not None:
                problems.append(fixture)
            if (".test." in path.name or ".spec." in path.name) and path.suffix in {
                ".js",
                ".jsx",
                ".mjs",
                ".ts",
                ".tsx",
            }:
                problems.extend(text_problems(path))
    return problems


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = check(root)
    if problems:
        for problem in problems:
            print(f"no-test-doubles: ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print("no-test-doubles: OK: keine Serverantwort oder I/O-Port-Tests ersetzt")


if __name__ == "__main__":
    main()
