#!/usr/bin/env python3
"""Real-file test for ./leonaid pilot-secrets against production.env.example."""

from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.dx.generate_secrets import parse_env
from tools.pilot_deployment.doctor import SECRET_KEYS
from tools.pilot_deployment.validate import is_placeholder
from tools.pilot_install.production_secrets import GENERATORS, PENDING_INTEGRATION_KEY

# Provider-issued credentials cannot be generated; the operator enters them.
OPERATOR_SECRETS = {"MAIL_SMTP_PASSWORD"}


def run(root: Path, output: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(root / "tools/pilot_install/production_secrets.py"),
            "--template",
            str(root / "infra/pilot/production.env.example"),
            "--output",
            str(output),
            *options,
        ],
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(root)},
    )


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    template = parse_env(
        (root / "infra/pilot/production.env.example").read_text(encoding="utf-8"),
        root / "infra/pilot/production.env.example",
    )
    with tempfile.TemporaryDirectory() as directory:
        first = Path(directory) / "production.env"
        result = run(root, first)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        if stat.S_IMODE(first.stat().st_mode) != 0o600:
            raise AssertionError("pilot-secrets output is not 0600")
        values = parse_env(first.read_text(encoding="utf-8"), first)
        if set(values) != set(template):
            raise AssertionError("pilot-secrets changed the set of keys")
        if values["TWENTY_INTEGRATION_API_KEY"] != PENDING_INTEGRATION_KEY:
            raise AssertionError("the integration key must stay pending")
        generated = {
            key
            for key, value in template.items()
            if value.startswith(("__RANDOM_", "__DISTINCT_RANDOM_"))
        }
        expected = (set(SECRET_KEYS) - OPERATOR_SECRETS) - {
            "TWENTY_INTEGRATION_API_KEY"
        }
        if not expected <= generated:
            raise AssertionError(f"secrets without generator: {expected - generated}")
        for key in generated:
            value = values[key]
            if len(value) < 24 or is_placeholder(value):
                raise AssertionError(f"{key} is not a strong fresh value")
            if value in result.stdout + result.stderr:
                raise AssertionError("pilot-secrets printed a secret")
        if len({values[key] for key in generated}) != len(generated):
            raise AssertionError("generated secrets are not distinct")
        if "MAIL_SMTP_PASSWORD" not in result.stdout:
            raise AssertionError("pilot-secrets must list the keys left to fill")

        before = first.read_bytes()
        again = run(root, first)
        if again.returncode == 0 or "refusing to overwrite" not in again.stderr:
            raise AssertionError("pilot-secrets overwrote an existing file")
        if first.read_bytes() != before:
            raise AssertionError("a refused run changed the existing file")

        second = Path(directory) / "second.env"
        if run(root, second).returncode != 0:
            raise AssertionError("second pilot-secrets run failed")
        other = parse_env(second.read_text(encoding="utf-8"), second)
        if any(values[key] == other[key] for key in generated):
            raise AssertionError("two runs produced a repeated secret")
    # Generated and issued secrets may contain "__" by chance (URL-safe
    # tokens about once in eight, the Twenty JWT likewise); only the template
    # shape is a placeholder.
    for value in ("abc__def0123456789abcdef0123", "eyJ__x.eyJ__y.sig__nature0123"):
        if is_placeholder(value):
            raise AssertionError("a random secret with '__' counts as a placeholder")
    for value in (
        "__RANDOM_PASSWORD__",
        "prefix-__SMTP_PASSWORD__",
        "ChangeMe-0123456789abcdef",
    ):
        if not is_placeholder(value):
            raise AssertionError(f"placeholder {value!r} was not recognised")
    for name, generate in GENERATORS.items():
        for _ in range(2000):
            if is_placeholder(generate()):
                raise AssertionError(f"{name} produced a template placeholder")
    print(
        f"pilot-secrets-test: OK: {len(generated)} distinct fresh secrets, 0600, "
        "pending key, no overwrite and no secret output"
    )
    hosts(root)


def hosts(root: Path) -> None:
    """Host settings derived from the public and admin domain (multi-domain §6.1)."""
    with tempfile.TemporaryDirectory() as directory:
        split = Path(directory) / "split.env"
        result = run(
            root,
            split,
            "--public-domain",
            "Leonaid.org",
            "--alias",
            "www.leonaid.org",
            "--alias",
            "web.leonaid.org",
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        values = parse_env(split.read_text(encoding="utf-8"), split)
        expected = {
            "LEONAID_PUBLIC_DOMAIN": "leonaid.org",
            "LEONAID_ADMIN_DOMAIN": "app.leonaid.org",
            "LEONAID_PROXY_CADDYFILE": "Caddyfile.split",
            "LEONAID_PUBLIC_BASE_URL": "https://app.leonaid.org",
            "LEONAID_ALLOWED_ORIGINS": "https://app.leonaid.org",
            "LEONAID_SITE_BASE_URL": "https://leonaid.org",
            "LEONAID_PUBLIC_ORIGINS": (
                "https://leonaid.org,https://www.leonaid.org,https://web.leonaid.org"
            ),
            "LEONAID_PUBLIC_DOMAIN_ALIASES": "www.leonaid.org, web.leonaid.org",
        }
        for key, value in expected.items():
            if values.get(key) != value:
                raise AssertionError(f"{key}={values.get(key)!r}, want {value!r}")
        if not values["CMS_ENCRYPTION_KEY"].startswith("emdash_enc_v1_"):
            raise AssertionError("CMS key lacks the EmDash key prefix")

        own = Path(directory) / "own-admin.env"
        result = run(
            root,
            own,
            "--public-domain",
            "leonaid.org",
            "--admin-domain",
            "mitglieder.leonaid.org",
        )
        values = parse_env(own.read_text(encoding="utf-8"), own)
        if result.returncode != 0 or values["LEONAID_ADMIN_DOMAIN"] != (
            "mitglieder.leonaid.org"
        ):
            raise AssertionError("an explicit admin domain was not kept")
        if "LEONAID_PUBLIC_DOMAIN_ALIASES" in values:
            raise AssertionError("an unused alias line was activated")

        single = Path(directory) / "single.env"
        result = run(
            root, single, "--public-domain", "portal.leonaid.org", "--single-host"
        )
        values = parse_env(single.read_text(encoding="utf-8"), single)
        if (
            result.returncode != 0
            or values["LEONAID_PUBLIC_BASE_URL"] != "https://portal.leonaid.org"
            or "LEONAID_ADMIN_DOMAIN" in values
            or "LEONAID_SITE_BASE_URL" in values
        ):
            raise AssertionError("--single-host must keep one host")

        for label, options in (
            (
                "admin equals public",
                ("--public-domain", "leonaid.org", "--admin-domain", "leonaid.org"),
            ),
            (
                "admin equals alias",
                (
                    "--public-domain",
                    "leonaid.org",
                    "--admin-domain",
                    "www.leonaid.org",
                    "--alias",
                    "www.leonaid.org",
                ),
            ),
            ("reserved domain", ("--public-domain", "leonaid.test")),
            ("alias without public domain", ("--alias", "www.leonaid.org")),
            (
                "single host with alias",
                (
                    "--public-domain",
                    "leonaid.org",
                    "--single-host",
                    "--alias",
                    "www.leonaid.org",
                ),
            ),
        ):
            target = Path(directory) / "refused.env"
            if run(root, target, *options).returncode == 0 or target.exists():
                raise AssertionError(f"pilot-secrets accepted {label}")
    print(
        "pilot-secrets-test: OK: admin/public host settings derived; unsafe hosts refused"
    )


if __name__ == "__main__":
    main()
