#!/usr/bin/env python3
"""Generate a local env file from committed non-secret placeholders."""

from __future__ import annotations

import re
import secrets
import stat
import string
import sys
from pathlib import Path
from typing import Callable


TOKENS: dict[str, Callable[[], str]] = {
    "__GENERATE_HEX_32__": lambda: secrets.token_hex(32),
    "__GENERATE_URLSAFE_32__": lambda: secrets.token_urlsafe(32),
    "__GENERATE_PASSWORD_24__": lambda: generate_password(24),
    "__GENERATE_PASSWORD_32__": lambda: generate_password(32),
    "__GENERATE_IDENTIFIER_20__": lambda: generate_identifier(20),
    "__GENERATE_EMAIL__": lambda: generate_email(),
}


def generate_password(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_identifier(length: int) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_email() -> str:
    return f"admin-{secrets.token_hex(8)}@leonaid.invalid"


def parse_env(content: str, source: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(content.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{source}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError(f"{source}:{line_number}: duplicate key {key}")
        values[key] = value
    return values


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: generate_secrets.py TEMPLATE OUTPUT", file=sys.stderr)
        return 64
    template = Path(sys.argv[1])
    output = Path(sys.argv[2])
    content = template.read_text(encoding="utf-8")
    try:
        template_values = parse_env(content, template)
        existing_values = (
            parse_env(output.read_text(encoding="utf-8"), output)
            if output.exists()
            else {}
        )
    except (OSError, ValueError) as error:
        print(f"secret-bootstrap: ERROR: {error}", file=sys.stderr)
        return 1
    extra_keys = sorted(set(existing_values) - set(template_values))
    if extra_keys:
        print(
            f"secret-bootstrap: ERROR: local file has unknown keys: {extra_keys}",
            file=sys.stderr,
        )
        return 1

    rendered_lines: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            rendered_lines.append(raw)
            continue
        key, template_value = line.split("=", 1)
        if key in existing_values:
            rendered_lines.append(f"{key}={existing_values[key]}")
            continue
        value = template_value
        for token, generator in TOKENS.items():
            value = re.sub(re.escape(token), lambda _match: generator(), value)
        rendered_lines.append(f"{key}={value}")
    rendered = "\n".join(rendered_lines) + "\n"
    unresolved = sorted(set(re.findall(r"__GENERATE_[A-Z0-9_]+__", rendered)))
    if unresolved:
        print(
            f"secret-bootstrap: ERROR: unresolved tokens: {unresolved}", file=sys.stderr
        )
        return 1
    previous = output.read_text(encoding="utf-8") if output.exists() else None
    if previous == rendered:
        print(f"secret-bootstrap: OK: existing {output} is current")
        return 0
    mode = stat.S_IMODE(output.stat().st_mode) if output.exists() else 0o600
    temporary = output.with_name(f".{output.name}.{secrets.token_hex(8)}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.chmod(mode)
    temporary.replace(output)
    action = "updated missing values in" if previous is not None else "generated"
    print(f"secret-bootstrap: OK: {action} {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
