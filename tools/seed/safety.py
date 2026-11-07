#!/usr/bin/env python3
"""Refuse destructive resets unless the rendered stack is explicitly local."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ALLOWED_PROJECT = re.compile(
    # leonaid: main checkout; leonaid-wt-<cksum>: a linked worktree (see ./leonaid).
    r"leonaid(?:-poc[0-9]{3}-test(?:-[0-9]+-[0-9]+)?|-wt-[0-9]+)?\Z"
)
EXPECTED_ENDPOINTS = {
    ("api", "CORE_DATABASE_URL"): ("postgresql", "core-postgres"),
    ("api", "TWENTY_BASE_URL"): ("http", "twenty-server"),
    ("api", "RUSTFS_ENDPOINT_URL"): ("http", "rustfs"),
    ("api", "MAIL_HEALTH_URL"): ("http", "mailpit"),
    ("twenty-server", "PG_DATABASE_URL"): ("postgresql", "twenty-postgres"),
}
REQUIRED_SERVICES = {
    "api",
    "core-postgres",
    "mailpit",
    "rustfs",
    "twenty-postgres",
    "twenty-server",
}


class ResetSafetyError(RuntimeError):
    """The resolved target is not an explicitly marked local test stack."""


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ResetSafetyError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        if key in values:
            raise ResetSafetyError(f"{path}:{line_number}: duplicate key {key}")
        values[key] = value
    return values


def service_environment(config: dict[str, Any], service: str) -> dict[str, str]:
    services = config.get("services")
    if not isinstance(services, dict):
        raise ResetSafetyError("Compose configuration has no services")
    raw_service = services.get(service)
    if not isinstance(raw_service, dict):
        raise ResetSafetyError(f"Compose service missing: {service}")
    environment = raw_service.get("environment")
    if not isinstance(environment, dict):
        raise ResetSafetyError(f"Compose service {service} has no environment")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ResetSafetyError(
            f"Compose service {service} has invalid environment values"
        )
    return environment


def validate_endpoint(value: str, scheme: str, host: str, label: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != scheme or parsed.hostname != host:
        raise ResetSafetyError(
            f"{label} must point to {scheme}://{host}; target refused"
        )
    if parsed.username is None and scheme == "postgresql":
        raise ResetSafetyError(f"{label} has no local database user")


def validate(
    config: dict[str, Any],
    *,
    project_name: str,
    env_values: dict[str, str],
) -> None:
    if env_values.get("LEONAID_ENV") != "local":
        raise ResetSafetyError("LEONAID_ENV must be exactly 'local'")
    if env_values.get("LEONAID_RESET_ALLOWED") != "true":
        raise ResetSafetyError("LEONAID_RESET_ALLOWED must be exactly 'true'")
    if ALLOWED_PROJECT.fullmatch(project_name) is None:
        raise ResetSafetyError(f"Compose project name is not allowed: {project_name}")
    if config.get("name") != project_name:
        raise ResetSafetyError(
            f"rendered Compose project {config.get('name')!r} does not match {project_name!r}"
        )

    services = config.get("services")
    if not isinstance(services, dict):
        raise ResetSafetyError("Compose configuration has no services")
    missing_services = sorted(REQUIRED_SERVICES - set(services))
    if missing_services:
        raise ResetSafetyError(f"reset services missing: {missing_services}")

    for (service, key), (scheme, host) in EXPECTED_ENDPOINTS.items():
        environment = service_environment(config, service)
        value = environment.get(key)
        if value is None:
            raise ResetSafetyError(f"{service}.{key} missing")
        validate_endpoint(value, scheme, host, f"{service}.{key}")

    volumes = config.get("volumes")
    if not isinstance(volumes, dict) or not volumes:
        raise ResetSafetyError("Compose configuration has no named volumes")
    external_volumes = sorted(
        name
        for name, definition in volumes.items()
        if isinstance(definition, dict) and definition.get("external")
    )
    if external_volumes:
        raise ResetSafetyError(
            f"external volumes must not be reset: {external_volumes}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        config = json.load(sys.stdin)
        if not isinstance(config, dict):
            raise ResetSafetyError("Compose JSON must be an object")
        validate(
            config,
            project_name=arguments.project_name,
            env_values=parse_env(arguments.env_file),
        )
    except (OSError, json.JSONDecodeError, ResetSafetyError) as error:
        print(f"reset-safety: REFUSED: {error}", file=sys.stderr)
        return 1
    print("reset-safety: OK: only the marked local LeonAid test system")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
