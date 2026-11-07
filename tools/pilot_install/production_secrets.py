#!/usr/bin/env python3
"""Write a production env file with fresh secrets from production.env.example.

Every `__RANDOM_*__` and `__DISTINCT_RANDOM_*__` placeholder gets its own
cryptographically random value; the Twenty integration key keeps the
PENDING_PILOT_INSTALL marker for ./leonaid pilot-install. Values the operator
must take from elsewhere (tenant, release images, SMTP account, backup
endpoint) stay as placeholders and are listed by key name.

With --public-domain the host settings are derived from two inputs
(specs/multi-domain §6.1): the public domain and the admin domain, which
defaults to app.<public domain>. --single-host keeps today's one-host setup.

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
from tools.pilot_deployment.validate import (
    DeploymentContractError,
    is_placeholder,
    valid_hostname,
)

PENDING_INTEGRATION_KEY = "PENDING_PILOT_INSTALL"


def doctor_safe(generate: Callable[[], str]) -> Callable[[], str]:
    """Draw again in the rare case a value looks like a template placeholder.

    URL-safe tokens can by chance contain a run such as "__AB__", which the
    pilot doctor would read as an unfilled placeholder.
    """

    def draw() -> str:
        while True:
            value = generate()
            if not is_placeholder(value):
                return value

    return draw


# The pilot doctor rejects secrets shorter than 24 characters.
GENERATORS: dict[str, Callable[[], str]] = {
    name: doctor_safe(generate)
    for name, generate in {
        "__RANDOM_HEX_32_BYTES__": lambda: secrets.token_hex(32),
        "__DISTINCT_RANDOM_HEX_32_BYTES__": lambda: secrets.token_hex(32),
        "__DISTINCT_RANDOM_URLSAFE_32_BYTES__": lambda: secrets.token_urlsafe(32),
        "__RANDOM_PASSWORD__": lambda: generate_password(32),
        "__RANDOM_ACCESS_KEY__": lambda: generate_identifier(24),
        "__RANDOM_SECRET_KEY__": lambda: generate_password(40),
        # EmDash's versioned key format: prefix plus 32 random bytes.
        "__RANDOM_EMDASH_KEY__": lambda: "emdash_enc_v1_" + secrets.token_urlsafe(32),
    }.items()
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


HOST_KEYS = (
    "LEONAID_PUBLIC_HOST_ENABLED",
    "LEONAID_PUBLIC_DOMAIN",
    "LEONAID_PUBLIC_BASE_URL",
    "LEONAID_ALLOWED_ORIGINS",
    "LEONAID_ADMIN_DOMAIN",
    "LEONAID_PROXY_CADDYFILE",
    "LEONAID_SITE_BASE_URL",
    "LEONAID_PUBLIC_ORIGINS",
    "LEONAID_PUBLIC_DOMAIN_ALIASES",
)


def host_settings(
    public_domain: str,
    admin_domain: str | None,
    aliases: list[str],
    *,
    single_host: bool = False,
) -> dict[str, str]:
    """All host keys from the public domain and the admin domain (§6.1)."""
    public = public_domain.strip().rstrip(".").casefold()
    names = [alias.strip().rstrip(".").casefold() for alias in aliases]
    try:
        valid_hostname(public, "public domain")
        for alias in names:
            valid_hostname(alias, "public domain alias")
    except DeploymentContractError as error:
        raise SecretsError(str(error)) from error
    if single_host:
        if admin_domain or names:
            raise SecretsError("--single-host takes no admin domain and no alias")
        return {
            "LEONAID_PUBLIC_DOMAIN": public,
            "LEONAID_PUBLIC_BASE_URL": f"https://{public}",
            "LEONAID_ALLOWED_ORIGINS": f"https://{public}",
        }
    admin = (admin_domain or f"app.{public}").strip().rstrip(".").casefold()
    try:
        valid_hostname(admin, "admin domain")
    except DeploymentContractError as error:
        raise SecretsError(str(error)) from error
    if admin == public or admin in names:
        raise SecretsError("the admin domain must differ from the public domain")
    if public in names or len(set(names)) != len(names):
        raise SecretsError("public domain aliases repeat a host")
    return {
        "LEONAID_PUBLIC_DOMAIN": public,
        "LEONAID_PUBLIC_BASE_URL": f"https://{admin}",
        "LEONAID_ALLOWED_ORIGINS": f"https://{admin}",
        "LEONAID_ADMIN_DOMAIN": admin,
        "LEONAID_PROXY_CADDYFILE": "Caddyfile.split",
        "LEONAID_SITE_BASE_URL": f"https://{public}",
        # Aliases redirect at the edge; only the public host calls the API.
        "LEONAID_PUBLIC_ORIGINS": f"https://{public}",
        # Caddy reads the aliases as site addresses: ", " between them.
        **({"LEONAID_PUBLIC_DOMAIN_ALIASES": ", ".join(names)} if names else {}),
    }


def admin_only_settings(admin_domain: str) -> dict[str, str]:
    """Admin host plus campaign hosts, no general public host (§6.6)."""
    admin = admin_domain.strip().rstrip(".").casefold()
    try:
        valid_hostname(admin, "admin domain")
    except DeploymentContractError as error:
        raise SecretsError(str(error)) from error
    return {
        "LEONAID_PUBLIC_HOST_ENABLED": "false",
        "LEONAID_PUBLIC_DOMAIN": "",
        "LEONAID_PUBLIC_BASE_URL": f"https://{admin}",
        "LEONAID_ALLOWED_ORIGINS": f"https://{admin}",
        "LEONAID_ADMIN_DOMAIN": admin,
        "LEONAID_PROXY_CADDYFILE": "Caddyfile.admin-only",
        # Survey links and legal pages stay on the admin host.
        "LEONAID_SITE_BASE_URL": f"https://{admin}",
    }


def apply_hosts(content: str, hosts: dict[str, str]) -> str:
    """Set host keys, activating the template's commented examples."""
    lines = []
    for raw in content.splitlines():
        candidate = raw.removeprefix("# ")
        key = candidate.split("=", 1)[0] if "=" in candidate else ""
        if key in HOST_KEYS and (raw == candidate or key in hosts):
            raw = f"{key}={hosts[key]}" if key in hosts else f"# {raw}"
        lines.append(raw)
    missing = set(hosts) - {line.split("=", 1)[0] for line in lines}
    if missing:
        raise SecretsError(f"template lacks host keys: {', '.join(sorted(missing))}")
    return "\n".join(lines) + "\n"


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
    parser.add_argument("--public-domain")
    parser.add_argument("--admin-domain")
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--single-host", action="store_true")
    # Only campaign hosts, no general public host (specs/multi-domain §6.6).
    parser.add_argument("--no-public-host", action="store_true")
    arguments = parser.parse_args()
    try:
        rendered = render(
            arguments.template.read_text(encoding="utf-8"), arguments.template
        )
        content = rendered.content
        if arguments.no_public_host:
            if (
                arguments.public_domain
                or arguments.alias
                or arguments.single_host
                or not arguments.admin_domain
            ):
                raise SecretsError(
                    "--no-public-host takes --admin-domain only, no public domain"
                )
            content = apply_hosts(content, admin_only_settings(arguments.admin_domain))
        elif arguments.public_domain:
            content = apply_hosts(
                content,
                host_settings(
                    arguments.public_domain,
                    arguments.admin_domain,
                    arguments.alias,
                    single_host=arguments.single_host,
                ),
            )
        elif arguments.admin_domain or arguments.alias or arguments.single_host:
            raise SecretsError("host options need --public-domain")
        write_exclusive(arguments.output, content)
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
