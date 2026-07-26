#!/usr/bin/env python3
"""Prove text, binary and Playwright ZIP evidence cannot retain test secrets."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    sanitizer = root / "tools/ci/sanitize_artifacts.py"
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        artifacts = workspace / "artifacts"
        proof = workspace / "proof"
        artifacts.mkdir()
        proof.mkdir()

        primary_secret = "primary-secret-value"
        session_secret = "session-secret-value"
        env_file = workspace / ".env.local"
        env_file.write_text(
            f"API_TOKEN={primary_secret}\n",
            encoding="utf-8",
        )
        (proof / "sessions.env").write_text(
            f"ANNA_SESSION={session_secret}\n",
            encoding="utf-8",
        )
        (artifacts / "service.log").write_text(
            f"token={primary_secret} session={session_secret}\n",
            encoding="utf-8",
        )
        (artifacts / "screenshot.png").write_bytes(
            b"PNG-prefix-" + primary_secret.encode() + b"-suffix"
        )
        with zipfile.ZipFile(artifacts / "trace.zip", "w") as archive:
            archive.writestr(
                "trace.trace",
                f"cookie={session_secret}; token={primary_secret}",
            )
        (artifacts / "trace.zip").chmod(0o644)

        result = subprocess.run(
            [
                sys.executable,
                str(sanitizer),
                str(artifacts),
                str(env_file),
                "--env-directory",
                str(proof),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if "5 Secret-Vorkommen redigiert" not in result.stdout:
            raise AssertionError(f"Unerwarteter Sanitizer-Nachweis: {result.stdout}")

        forbidden = (primary_secret.encode(), session_secret.encode())
        for path in artifacts.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".zip":
                with zipfile.ZipFile(path, "r") as archive:
                    payloads = [
                        archive.read(entry.filename) for entry in archive.infolist()
                    ]
            else:
                payloads = [path.read_bytes()]
            if any(secret in payload for payload in payloads for secret in forbidden):
                raise AssertionError(f"Secret blieb im Artefakt {path}")
        if (artifacts / "trace.zip").stat().st_mode & 0o777 != 0o644:
            raise AssertionError("Trace-ZIP verlor beim Redigieren ihre Leserechte")

    print(
        "ci-artifact-sanitize-test: OK: Text, Binärdatei und Trace-ZIP "
        "enthalten keine Test-Secrets"
    )


if __name__ == "__main__":
    main()
