#!/usr/bin/env python3
"""Validate local secrets without ever printing their values."""

from __future__ import annotations

import sys
from pathlib import Path


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError(f"{path}:{line_number}: duplicate key {key}")
        values[key] = value
    return values


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_secrets.py TEMPLATE ENV", file=sys.stderr)
        return 64
    template_path = Path(sys.argv[1])
    env_path = Path(sys.argv[2])
    try:
        template = parse_env(template_path)
        actual = parse_env(env_path)
    except (OSError, ValueError) as error:
        print(f"secret-check: ERROR: {error}", file=sys.stderr)
        return 1

    if set(actual) != set(template):
        print("secret-check: ERROR: template and local keys differ", file=sys.stderr)
        return 1
    if actual.get("LEONAID_ENV") != "local":
        print("secret-check: ERROR: LEONAID_ENV must be local", file=sys.stderr)
        return 1

    secret_values = [value for key, value in actual.items() if key != "LEONAID_ENV"]
    if any(
        not value
        or "__GENERATE_" in value
        or "change-me" in value.lower()
        or len(value) < 20
        for value in secret_values
    ):
        print("secret-check: ERROR: empty, short or template secret", file=sys.stderr)
        return 1
    if len(secret_values) != len(set(secret_values)):
        print("secret-check: ERROR: logically separate secrets must be unique", file=sys.stderr)
        return 1

    print(f"secret-check: OK: {len(secret_values)} unique generated secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
