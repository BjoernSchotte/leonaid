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
from tools.pilot_install.production_secrets import PENDING_INTEGRATION_KEY

# Provider-issued credentials cannot be generated; the operator enters them.
OPERATOR_SECRETS = {"MAIL_SMTP_PASSWORD"}


def run(root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(root / "tools/pilot_install/production_secrets.py"),
            "--template",
            str(root / "infra/pilot/production.env.example"),
            "--output",
            str(output),
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
            if len(value) < 24 or "__" in value:
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
    print(
        f"pilot-secrets-test: OK: {len(generated)} distinct fresh secrets, 0600, "
        "pending key, no overwrite and no secret output"
    )


if __name__ == "__main__":
    main()
