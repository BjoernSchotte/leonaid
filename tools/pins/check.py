#!/usr/bin/env python3
"""Reject dependency and container drift before a build can start."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any


PINNED_VERSION = re.compile(r"^[0-9]+(?:\.[0-9A-Za-z]+)+(?:[-+][0-9A-Za-z.-]+)?$")
PYTHON_DEPENDENCY = re.compile(
    r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==[0-9A-Za-z][0-9A-Za-z.!+_-]*(?:\s*;.+)?$"
)
IMAGE = re.compile(
    r"^(?P<name>[^@\s]+):(?P<tag>[^@:\s]+)"
    r"@(?P<digest>sha256:[0-9a-f]{64})$"
)
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED_SYSTEMS = {
    "alertmanager",
    "alpine",
    "bun",
    "caddy",
    "mailpit",
    "node",
    "listmonk",
    "otel",
    "playwright",
    "postgres",
    "prometheus",
    "python",
    "redis",
    "restic",
    "rustfs",
    "seaweedfs",
    "syft",
    "twenty",
    "trivy",
    "typst",
    "uv",
    "rustfs-upgrade-source",
    "twenty-upgrade-source",
}
TOOLCHAIN_KEYS = {"python", "nodejs", "bun", "uv", "typst", "playwright"}
DEPENDENCY_SECTIONS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)
ALLOWED_DYNAMIC_IMAGE_VARIABLES = {
    Path("infra/pilot/compose.yml"): {
        "LEONAID_CORE_IMAGE",
        "LEONAID_PUBLIC_IMAGE",
        "LEONAID_PWA_IMAGE",
        "LEONAID_WEB_IMAGE",
    },
    Path("infra/pilot/compose.test.yml"): {
        "LEONAID_TEST_CORE_IMAGE",
        "LEONAID_TEST_PUBLIC_IMAGE",
        "LEONAID_TEST_PWA_IMAGE",
        "LEONAID_TEST_WEB_IMAGE",
    },
}


class Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, message: str) -> None:
        self.items.append(message)

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.add(message)


def read_json(path: Path, problems: Problems) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        problems.add(f"{path}: invalid JSON: {error}")
        return {}
    if not isinstance(value, dict):
        problems.add(f"{path}: root must be an object")
        return {}
    return value


def read_toml(path: Path, problems: Problems) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        problems.add(f"{path}: invalid TOML: {error}")
        return {}
    return value


def check_toolchain(
    root: Path, systems: dict[str, dict[str, Any]], problems: Problems
) -> None:
    path = root / ".tool-versions"
    values: dict[str, str] = {}
    try:
        for line_number, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            fields = raw.split()
            if len(fields) != 2:
                problems.add(f"{path}:{line_number}: expected '<tool> <exact-version>'")
                continue
            key, version = fields
            if key in values:
                problems.add(f"{path}:{line_number}: duplicate tool {key}")
            values[key] = version
            if not PINNED_VERSION.fullmatch(version):
                problems.add(
                    f"{path}:{line_number}: {key} is not exactly pinned: {version}"
                )
    except OSError as error:
        problems.add(f"{path}: cannot read: {error}")
        return

    problems.require(
        set(values) == TOOLCHAIN_KEYS,
        f"{path}: expected tools {sorted(TOOLCHAIN_KEYS)}",
    )
    expected_prefixes = {
        "python": ("python", values.get("python", "")),
        "nodejs": ("node", values.get("nodejs", "")),
        "bun": ("bun", values.get("bun", "")),
        "uv": ("uv", values.get("uv", "")),
        "typst": ("typst", values.get("typst", "")),
        "playwright": ("playwright", values.get("playwright", "")),
    }
    for tool, (system_id, expected) in expected_prefixes.items():
        actual = str(systems.get(system_id, {}).get("version", ""))
        if expected and not actual.startswith(expected):
            problems.add(
                f"{path}: {tool} {expected} does not match external system {system_id} {actual}"
            )


def check_python(root: Path, problems: Problems) -> None:
    project_path = root / "pyproject.toml"
    lock_path = root / "uv.lock"
    project = read_toml(project_path, problems)
    lock = read_toml(lock_path, problems)

    dependencies: list[tuple[str, str]] = []
    project_dependencies = project.get("project", {}).get("dependencies", [])
    if isinstance(project_dependencies, list):
        dependencies.extend(
            ("project.dependencies", str(item)) for item in project_dependencies
        )
    else:
        problems.add(f"{project_path}: project.dependencies must be an array")

    groups = project.get("dependency-groups", {})
    if isinstance(groups, dict):
        for group, items in groups.items():
            if not isinstance(items, list):
                problems.add(
                    f"{project_path}: dependency group {group} must be an array"
                )
                continue
            dependencies.extend(
                (f"dependency-groups.{group}", str(item)) for item in items
            )

    problems.require(
        bool(dependencies), f"{project_path}: no direct dependencies found"
    )
    for section, dependency in dependencies:
        if not PYTHON_DEPENDENCY.fullmatch(dependency):
            problems.add(
                f"{project_path}: {section} dependency is not exactly pinned with ==: {dependency}"
            )

    packages = lock.get("package", [])
    problems.require(
        isinstance(packages, list) and bool(packages), f"{lock_path}: no packages"
    )
    if not isinstance(packages, list):
        return
    for package in packages:
        if not isinstance(package, dict):
            problems.add(f"{lock_path}: package entry must be a table")
            continue
        name = str(package.get("name", "<unnamed>"))
        version = str(package.get("version", ""))
        problems.require(
            bool(version), f"{lock_path}: package {name} has no exact version"
        )
        source = package.get("source", {})
        if not isinstance(source, dict) or "registry" not in source:
            continue
        artifacts: list[dict[str, Any]] = []
        sdist = package.get("sdist")
        if isinstance(sdist, dict):
            artifacts.append(sdist)
        wheels = package.get("wheels", [])
        if isinstance(wheels, list):
            artifacts.extend(item for item in wheels if isinstance(item, dict))
        if not artifacts:
            problems.add(
                f"{lock_path}: registry package {name} {version} has no hashed artifact"
            )
            continue
        for artifact in artifacts:
            digest = artifact.get("hash")
            if not isinstance(digest, str) or not HASH.fullmatch(digest):
                problems.add(
                    f"{lock_path}: registry package {name} {version} has an invalid artifact hash"
                )


def iter_package_json(root: Path) -> list[Path]:
    excluded = {".artifacts", ".cache", ".git", ".venv", "node_modules"}
    return sorted(
        path
        for path in root.rglob("package.json")
        if not any(part in excluded for part in path.relative_to(root).parts)
    )


def check_frontend(root: Path, problems: Problems) -> None:
    root_package = read_json(root / "package.json", problems)
    problems.require(
        root_package.get("packageManager") == "bun@1.2.19",
        f"{root / 'package.json'}: packageManager must be exactly bun@1.2.19",
    )
    engines = root_package.get("engines", {})
    problems.require(
        isinstance(engines, dict)
        and engines.get("bun") == "1.2.19"
        and engines.get("node") == "22.23.0",
        f"{root / 'package.json'}: Bun and Node engines must be exact",
    )

    for path in iter_package_json(root):
        package = read_json(path, problems)
        for section in DEPENDENCY_SECTIONS:
            dependencies = package.get(section, {})
            if not isinstance(dependencies, dict):
                problems.add(f"{path}: {section} must be an object")
                continue
            for name, version in dependencies.items():
                if isinstance(version, str) and version.startswith("workspace:"):
                    continue
                if not isinstance(version, str) or not PINNED_VERSION.fullmatch(
                    version
                ):
                    problems.add(
                        f"{path}: {section} dependency {name} is not exactly pinned: {version}"
                    )

    bun_lock = root / "bun.lock"
    try:
        lock_text = bun_lock.read_text(encoding="utf-8")
    except OSError as error:
        problems.add(f"{bun_lock}: cannot read: {error}")
        return
    problems.require(
        '"lockfileVersion": 1' in lock_text, f"{bun_lock}: unexpected lock format"
    )
    for name, version in root_package.get("devDependencies", {}).items():
        problems.require(
            f'"{name}@{version}"' in lock_text,
            f"{bun_lock}: direct dependency {name}@{version} is absent",
        )
    for line_number, line in enumerate(lock_text.splitlines(), 1):
        if (
            re.search(r'^\s+"[^"]+": \["[^"]+@[^\"]+"', line)
            and "@workspace:" not in line
            and "sha512-" not in line
        ):
            problems.add(
                f"{bun_lock}:{line_number}: package entry has no integrity hash"
            )


def check_external_systems(root: Path, problems: Problems) -> dict[str, dict[str, Any]]:
    path = root / "infra/locks/external-systems.lock"
    lock = read_json(path, problems)
    systems_raw = lock.get("systems", [])
    if not isinstance(systems_raw, list):
        problems.add(f"{path}: systems must be an array")
        return {}

    systems: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(systems_raw):
        if not isinstance(item, dict):
            problems.add(f"{path}: systems[{index}] must be an object")
            continue
        system_id = str(item.get("id", ""))
        if not system_id:
            problems.add(f"{path}: systems[{index}] has no id")
            continue
        if system_id in systems:
            problems.add(f"{path}: duplicate system id {system_id}")
        systems[system_id] = item

        image = str(item.get("image", ""))
        match = IMAGE.fullmatch(image)
        if not match:
            problems.add(f"{path}: {system_id} image is not tag+digest pinned: {image}")
        else:
            tag = match.group("tag")
            if tag.lower() == "latest":
                problems.add(f"{path}: {system_id} uses forbidden latest tag")
            if match.group("digest") != item.get("digest"):
                problems.add(f"{path}: {system_id} digest field differs from image")
        for field in ("version", "license", "upstream"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.add(f"{path}: {system_id} has no {field}")
        upstream = item.get("upstream")
        if isinstance(upstream, str) and not upstream.startswith("https://"):
            problems.add(f"{path}: {system_id} upstream must use https")
        roles = item.get("roles")
        if (
            not isinstance(roles, list)
            or not roles
            or not all(isinstance(role, str) for role in roles)
        ):
            problems.add(f"{path}: {system_id} roles must be a non-empty string array")

    problems.require(
        set(systems) == REQUIRED_SYSTEMS,
        f"{path}: expected systems {sorted(REQUIRED_SYSTEMS)}, got {sorted(systems)}",
    )
    for field in ("reviewedAt", "nextReviewOn"):
        try:
            date.fromisoformat(str(lock.get(field, "")))
        except ValueError:
            problems.add(f"{path}: {field} must be an ISO date")
    return systems


def check_env_parity(
    root: Path, systems: dict[str, dict[str, Any]], problems: Problems
) -> None:
    path = root / "infra/locks/images.env"
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        problems.add(f"{path}: cannot read: {error}")
        return
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            problems.add(f"{path}:{line_number}: invalid KEY=VALUE line")
            continue
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*_IMAGE", key):
            problems.add(f"{path}:{line_number}: invalid image variable {key}")
        if key in values:
            problems.add(f"{path}:{line_number}: duplicate variable {key}")
        values[key] = value

    expected = {
        f"{system_id.upper().replace('-', '_')}_IMAGE": item["image"]
        for system_id, item in systems.items()
    }
    if values != expected:
        missing = sorted(set(expected) - set(values))
        extra = sorted(set(values) - set(expected))
        changed = sorted(
            key for key in set(values) & set(expected) if values[key] != expected[key]
        )
        problems.add(
            f"{path}: external lock parity failed; missing={missing}, extra={extra}, changed={changed}"
        )


def check_browsers(
    root: Path, systems: dict[str, dict[str, Any]], problems: Problems
) -> None:
    path = root / "infra/locks/browser-artifacts.lock"
    lock = read_json(path, problems)
    playwright = str(lock.get("playwright", ""))
    system_version = str(systems.get("playwright", {}).get("version", ""))
    problems.require(
        system_version.startswith(playwright) and bool(playwright),
        f"{path}: Playwright version differs from image lock",
    )
    artifacts = lock.get("artifacts", {})
    expected = {"chromium", "firefox", "webkit"}
    problems.require(
        isinstance(artifacts, dict) and set(artifacts) == expected,
        f"{path}: expected browser artifacts {sorted(expected)}",
    )
    if isinstance(artifacts, dict):
        for name, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                problems.add(f"{path}: browser {name} must be an object")
                continue
            if not str(artifact.get("revision", "")).isdigit() or not artifact.get(
                "version"
            ):
                problems.add(f"{path}: browser {name} needs exact revision and version")


def check_renovate(root: Path, problems: Problems) -> None:
    path = root / "renovate.json"
    config = read_json(path, problems)
    expected = {
        "enabled": True,
        "automerge": False,
        "dependencyDashboard": True,
        "rangeStrategy": "pin",
        "pinDigests": True,
        "prCreation": "immediate",
    }
    for key, value in expected.items():
        if config.get(key) != value:
            problems.add(f"{path}: {key} must be {value!r}")
    rules = config.get("packageRules", [])
    if not isinstance(rules, list) or not rules:
        problems.add(f"{path}: an explicit non-automerge package rule is required")
    else:
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict) or rule.get("automerge") is not False:
                problems.add(f"{path}: packageRules[{index}] must disable automerge")


def check_image_references(root: Path, problems: Problems) -> None:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(
            part in {".artifacts", ".cache", ".git", ".venv", "node_modules"}
            for part in relative.parts
        ):
            continue
        name = path.name.lower()
        if name.startswith("dockerfile") or (
            path.suffix.lower() in {".yml", ".yaml"}
            and ("compose" in name or relative.parts[:2] == (".github", "workflows"))
        ):
            candidates.append(path)
    reference = re.compile(r"(?:^\s*image:\s*|^\s*FROM\s+)([^\s#]+)", re.IGNORECASE)
    dynamic_reference = re.compile(
        r"^\s*image:\s*\$\{(?P<variable>[A-Z][A-Z0-9_]*)"
        r"(?::[^}]*)?\}\s*(?:#.*)?$"
    )
    for path in candidates:
        relative = path.relative_to(root)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = reference.search(line)
            if not match:
                continue
            image = match.group(1)
            if "${" in image:
                dynamic_match = dynamic_reference.fullmatch(line)
                allowed_variables = ALLOWED_DYNAMIC_IMAGE_VARIABLES.get(relative, set())
                variable = (
                    dynamic_match.group("variable") if dynamic_match is not None else ""
                )
                if variable not in allowed_variables:
                    problems.add(
                        f"{path}:{line_number}: image reference must be literal "
                        "or an approved pilot release variable"
                    )
            elif not IMAGE.fullmatch(image):
                problems.add(
                    f"{path}:{line_number}: image reference is not tag+digest pinned: {image}"
                )


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = Problems()
    systems = check_external_systems(root, problems)
    check_toolchain(root, systems, problems)
    check_python(root, problems)
    check_frontend(root, problems)
    check_env_parity(root, systems, problems)
    check_browsers(root, systems, problems)
    check_renovate(root, problems)
    check_image_references(root, problems)
    if problems.items:
        for item in problems.items:
            print(f"pin-check: ERROR: {item}", file=sys.stderr)
        print(
            f"pin-check: FAILED with {len(problems.items)} problem(s)", file=sys.stderr
        )
        return 1
    print(
        f"pin-check: OK: {len(systems)} images, "
        f"{len(read_toml(root / 'uv.lock', Problems()).get('package', []))} Python packages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
