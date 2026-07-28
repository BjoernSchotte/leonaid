#!/usr/bin/env python3
"""Prove public evidence redaction and fail-closed private-data handling."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def run_sanitizer(
    sanitizer: Path,
    artifacts: Path,
    env_file: Path,
    proof: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(sanitizer),
            str(artifacts),
            str(env_file),
            "--env-directory",
            str(proof),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def nested_zip(payload_name: str, payload: bytes) -> bytes:
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr(payload_name, payload)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("nested/inner.zip", inner.getvalue())
    return outer.getvalue()


def unsafe_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../private.txt", b"synthetic")
    return output.getvalue()


def zip_with_comment(comment: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.comment = comment
        archive.writestr("safe.txt", b"synthetic")
    return output.getvalue()


def zip_with_symlink() -> bytes:
    output = io.BytesIO()
    link = zipfile.ZipInfo("linked.txt")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(link, b"target.txt")
    return output.getvalue()


def assert_rejected(
    sanitizer: Path,
    env_file: Path,
    proof: Path,
    *,
    name: str,
    payload: bytes,
) -> None:
    case = proof.parent / f"case-{name.replace('.', '-')}"
    case.mkdir()
    (case / name).write_bytes(payload)
    result = run_sanitizer(sanitizer, case, env_file, proof)
    if result.returncode != 70 or "BLOCKED" not in result.stderr:
        raise AssertionError(
            f"Private Evidence wurde nicht fail-closed abgewiesen: {name}: "
            f"{result.stdout}{result.stderr}"
        )


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
        env_file.write_text(f"API_TOKEN={primary_secret}\n", encoding="utf-8")
        (proof / "sessions.env").write_text(
            f"ANNA_SESSION={session_secret}\n",
            encoding="utf-8",
        )
        (artifacts / "service.log").write_text(
            f"token={primary_secret} session={session_secret}\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(artifacts / "trace.zip", "w") as archive:
            archive.writestr(
                "events.json",
                f'{{"cookie":"{session_secret}","token":"{primary_secret}"}}',
            )
        (artifacts / "trace.zip").chmod(0o640)

        result = run_sanitizer(sanitizer, artifacts, env_file, proof)
        if (
            result.returncode != 0
            or "4 Secret-Vorkommen redigiert" not in result.stdout
        ):
            raise AssertionError(f"Unerwarteter Sanitizer-Nachweis: {result}")
        forbidden = (primary_secret.encode(), session_secret.encode())
        for path in artifacts.rglob("*"):
            if not path.is_file():
                continue
            if any(secret in path.read_bytes() for secret in forbidden):
                raise AssertionError(f"Secret blieb im Artefakt {path}")
        if (artifacts / "trace.zip").stat().st_mode & 0o777 != 0o640:
            raise AssertionError("Trace-ZIP verlor beim Redigieren ihre Dateirechte")

        private_canary = b"PII_NAME_CANARY_Erika-Mustermann"
        cases = {
            "private.txt": private_canary,
            "private-secret.md": b"SECRET_TOKEN_CANARY_not-from-env",
            "private.json": b'{"displayName":"PII_NAME_CANARY_Erika"}',
            "private-structured.json": b'{"billingAddress":"synthetic"}',
            "private.html": b"<p>PII_ADDRESS_CANARY_Hauptstrasse-1</p>",
            "private.csv": b"name,address\nSynthetic,Example\n",
            "private.png": b"\x89PNG\r\n\x1a\n" + private_canary,
            "private.pdf": b"%PDF-1.7\n" + private_canary,
            "private.zip": nested_zip("payload.json", private_canary),
            "private-trace.zip": nested_zip(
                "trace.trace",
                b'{"email":"real.person@example.org"}',
            ),
        }
        for name, payload in cases.items():
            assert_rejected(
                sanitizer,
                env_file,
                proof,
                name=name,
                payload=payload,
            )

        assert_rejected(
            sanitizer,
            env_file,
            proof,
            name="path-traversal.zip",
            payload=unsafe_zip(),
        )
        assert_rejected(
            sanitizer,
            env_file,
            proof,
            name="private-comment.zip",
            payload=zip_with_comment(private_canary),
        )
        assert_rejected(
            sanitizer,
            env_file,
            proof,
            name="symlink.zip",
            payload=zip_with_symlink(),
        )

    print(
        "ci-artifact-sanitize-test: OK: Secrets werden redigiert; PII, "
        "Screenshots, PDFs und verschachtelte Traces werden fail-closed abgewiesen"
    )


if __name__ == "__main__":
    main()
