#!/usr/bin/env python3
"""Write a production env file with fresh secrets from production.env.example.

Every `__RANDOM_*__` and `__DISTINCT_RANDOM_*__` placeholder gets its own
cryptographically random value; the Twenty integration key keeps the
PENDING_PILOT_INSTALL marker for ./leonaid pilot-install. Values the operator
must take from elsewhere (tenant, release images, domains, SMTP account,
backup endpoint) stay as placeholders and are listed by key name.

The output is created exclusively with mode 0600 and is never overwritten.
No secret value is printed.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tools.dx.generate_secrets import generate_identifier, generate_password, parse_env

PENDING_INTEGRATION_KEY = "PENDING_PILOT_INSTALL"
# The pilot doctor rejects secrets shorter than 24 characters.
GENERATORS: dict[str, Callable[[], str]] = {
    "__RANDOM_HEX_32_BYTES__": lambda: secrets.token_hex(32),
    "__DISTINCT_RANDOM_HEX_32_BYTES__": lambda: secrets.token_hex(32),
    "__DISTINCT_RANDOM_URLSAFE_32_BYTES__": lambda: secrets.token_urlsafe(32),
    "__RANDOM_PASSWORD__": lambda: generate_password(32),
    "__RANDOM_ACCESS_KEY__": lambda: generate_identifier(24),
    "__RANDOM_SECRET_KEY__": lambda: generate_password(40),
}
PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")


class SecretsError(RuntimeError):
    """The production env file could not be written safely."""


@dataclass(frozen=True)
class Rendered:
    content: str
    generated: dict[str, str]
    remaining: list[str]


def render(template: str, source: Path) -> Rendered:
    """Fill secret placeholders; report keys that still need operator input."""
    parse_env(template, source)  # rejects syntax errors and duplicate keys
    lines: list[str] = []
    generated: dict[str, str] = {}
    remaining: list[str] = []
    for raw in template.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            lines.append(raw)
            continue
        key, value = stripped.split("=", 1)
        if key == "TWENTY_INTEGRATION_API_KEY":
            value = PENDING_INTEGRATION_KEY
        generator = GENERATORS.get(value)
        if generator is not None:
            value = generator()
            generated[key] = value
        elif any(token in value for token in GENERATORS):
            raise SecretsError(f"{key}: a secret placeholder must be the whole value")
        if PLACEHOLDER.search(value):
            remaining.append(key)
        lines.append(f"{key}={value}")
    # Distinct values: one leaked secret must never open a second door.
    if len(set(generated.values())) != len(generated):
        raise SecretsError("generated secrets are not distinct")
    return Rendered("\n".join(lines) + "\n", generated, remaining)


def write_exclusive(path: Path, content: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SecretsError(f"{path} exists; refusing to overwrite it") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        rendered = render(
            arguments.template.read_text(encoding="utf-8"), arguments.template
        )
        write_exclusive(arguments.output, rendered.content)
    except (OSError, ValueError, SecretsError) as error:
        print(f"pilot-secrets: ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"pilot-secrets: OK: wrote {len(rendered.generated)} fresh secrets "
        "with mode 0600"
    )
    if rendered.remaining:
        print(
            "pilot-secrets: fill in these keys by hand: "
            + ", ".join(rendered.remaining)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
