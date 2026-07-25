#!/usr/bin/env python3
"""Generate a local env file from committed non-secret placeholders."""

from __future__ import annotations

import re
import secrets
import string
import sys
from pathlib import Path


TOKENS = {
    "__GENERATE_HEX_32__": lambda: secrets.token_hex(32),
    "__GENERATE_URLSAFE_32__": lambda: secrets.token_urlsafe(32),
    "__GENERATE_PASSWORD_24__": lambda: generate_password(24),
    "__GENERATE_PASSWORD_32__": lambda: generate_password(32),
    "__GENERATE_IDENTIFIER_20__": lambda: generate_identifier(20),
}


def generate_password(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_identifier(length: int) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: generate_secrets.py TEMPLATE OUTPUT", file=sys.stderr)
        return 64
    template = Path(sys.argv[1])
    output = Path(sys.argv[2])
    if output.exists():
        print(f"secret-bootstrap: ERROR: refusing to overwrite {output}", file=sys.stderr)
        return 1
    content = template.read_text(encoding="utf-8")
    for token, generator in TOKENS.items():
        content = re.sub(re.escape(token), lambda _match: generator(), content)
    unresolved = sorted(set(re.findall(r"__GENERATE_[A-Z0-9_]+__", content)))
    if unresolved:
        print(f"secret-bootstrap: ERROR: unresolved tokens: {unresolved}", file=sys.stderr)
        return 1
    output.write_text(content, encoding="utf-8")
    print(f"secret-bootstrap: OK: generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
