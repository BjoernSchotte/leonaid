#!/usr/bin/env python3
"""Prove public evidence redaction and fail-closed private-data handling."""

from __future__ import annotations

import io
import re
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
            f"Private evidence was not rejected fail-closed: {name}: "
            f"{result.stdout}{result.stderr}"
        )


def assert_capture_copies_only_text(root: Path) -> None:
    """capture-failure.sh copies exactly the proof types the sanitizer reads.

    A copied binary makes the sanitizer discard the whole capture; a missing
    text type silently drops evidence.
    """
    sys.path.insert(0, str(root))
    from tools.ci.sanitize_artifacts import TEXT_SUFFIXES

    script = (root / "tools/ci/capture-failure.sh").read_text(encoding="utf-8")
    match = re.search(r"^\s*(\*\.[a-z]+(?: \| \*\.[a-z]+)*)\)$", script, re.M)
    if match is None:
        raise AssertionError("capture-failure.sh has no proof copy pattern")
    copied = {pattern[1:] for pattern in match.group(1).split(" | ")}
    if copied != TEXT_SUFFIXES:
        raise AssertionError(
            f"capture-failure.sh copies {sorted(copied)}, "
            f"the sanitizer reads {sorted(TEXT_SUFFIXES)}"
        )


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    sanitizer = root / "tools/ci/sanitize_artifacts.py"
    assert_capture_copies_only_text(root)
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
            or "4 secret occurrences redacted" not in result.stdout
        ):
            raise AssertionError(f"Unexpected sanitizer result: {result}")
        forbidden = (primary_secret.encode(), session_secret.encode())
        for path in artifacts.rglob("*"):
            if not path.is_file():
                continue
            if any(secret in path.read_bytes() for secret in forbidden):
                raise AssertionError(f"Secret remained in artifact {path}")
        if (artifacts / "trace.zip").stat().st_mode & 0o777 != 0o640:
            raise AssertionError("Trace ZIP lost its file permissions during redaction")

        timestamp_artifacts = workspace / "timestamp-artifacts"
        timestamp_artifacts.mkdir()
        (timestamp_artifacts / "restic.log").write_text(
            "restoring snapshot at 2026-07-30 04:06:49.055375279 +0000 UTC\n"
            "installed fastapi==0.116.1\n"
            "2026-07-30T04:06:49.055375279Z next log line\n",
            encoding="utf-8",
        )
        timestamp_result = run_sanitizer(
            sanitizer,
            timestamp_artifacts,
            env_file,
            proof,
        )
        if timestamp_result.returncode != 0:
            raise AssertionError(
                "Timestamp nanoseconds were rejected as a phone number: "
                f"{timestamp_result.stdout}{timestamp_result.stderr}"
            )

        uuid_artifacts = workspace / "uuid-artifacts"
        uuid_artifacts.mkdir()
        (uuid_artifacts / "command.log").write_text(
            '{"requestId":"566bbb6b-0855-4240-8756-6569c7885bd0"}\n'
            "id 10855424-0875-4656-9788-012345678901 done\n",
            encoding="utf-8",
        )
        uuid_result = run_sanitizer(sanitizer, uuid_artifacts, env_file, proof)
        if uuid_result.returncode != 0:
            raise AssertionError(
                "UUID digit groups were rejected as a phone number: "
                f"{uuid_result.stdout}{uuid_result.stderr}"
            )

        # Identifier fragments that contain phone-like digit groups. Each line
        # is checked on its own so a failure names the exact false positive.
        identifier_lines = (
            "request 566bbb6b-0855-4240-8756 (truncated UUID)",
            "request ...0855-4240-8756-6569c7885bd0 (UUID with cut head)",
            "ref deadbeef-0123-4567-89ab tail",
            "traceparent 00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01",
            "commit 0123456789abcdef0123",
            "digest sha256:0123456789012345678901234567890123456789"
            "012345678901234567890123",
            "span 0102030405060708",
            "id=012345678901234567890",
            "artifact 20261103-012345678",
            '{"durationSeconds":0.12345678}',
            '{"score": 0.123456789012}',
            "took 0.0123456789 s",
            "ts=1730612345.0123456789",
        )
        for index, line in enumerate(identifier_lines):
            case = workspace / f"identifier-{index}"
            case.mkdir()
            (case / "command.log").write_text(f"{line}\n", encoding="utf-8")
            identifier_result = run_sanitizer(sanitizer, case, env_file, proof)
            if identifier_result.returncode != 0:
                raise AssertionError(
                    f"Identifier was rejected as a phone number: {line!r}: "
                    f"{identifier_result.stdout}{identifier_result.stderr}"
                )

        layer_artifacts = workspace / "layer-artifacts"
        layer_artifacts.mkdir()
        layer_log = layer_artifacts / "command.log"
        layer_log.write_text(
            "#121 loading layer 090230666164 25.52kB / 25.52kB 0.1s done\n",
            encoding="utf-8",
        )
        layer_result = run_sanitizer(sanitizer, layer_artifacts, env_file, proof)
        if layer_result.returncode != 0 or layer_log.read_text() != (
            "#121 loading layer [DOCKER_LAYER_ID] 25.52kB / 25.52kB 0.1s done\n"
        ):
            raise AssertionError("Numeric Docker layer ID was not redacted")

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
            "private-layer-suffix.log": (
                b"#121 loading layer 090230666164 25.52kB / 25.52kB 0.1s done "
                b"Kontakt: 089 12345678"
            ),
            "private-layer-like.txt": b"Kontakt: 090230666164",
            "private-phone-local.txt": b"Kontakt: 089 12345678",
            "private-phone-plus49.txt": b"Kontakt: +49 89 12345678",
            "private-phone-0049.txt": b"Kontakt: 0049 (89) 12345678",
            "private-phone-after-uuid.txt": (
                b"566bbb6b-0855-4240-8756-6569c7885bd0 Kontakt: 089 12345678"
            ),
            "private-uuid-like-phone.txt": b"Kontakt: 0855-4240-8756",
            "private-phone-trunk-in-parens.txt": b"Tel. +49 (0)89 1234567",
            "private-phone-trunk-spaced.txt": b"Tel. +49 (0) 171 1234567",
            "private-phone-national-parens.txt": b"(0)89 1234567",
            "private-phone-mobile.txt": b"Mobil 0171 1234567",
            "private-phone-compact.txt": b"Mobil 01711234567",
            "private-phone-e164.txt": b"+491711234567",
            "private-phone-hyphens.txt": b"+49-171-1234567",
            "private-phone-slash.txt": b"Tel.:089/123 456-78",
            "private-phone-after-abbrev.txt": b"Tel.0171 1234567",
            "private-phone-area-parens.txt": b"(089) 123 45 67",
            "private-phone-short-subscriber.txt": b"030 123456",
            "private-phone-extension.txt": b"089 1234567-12",
            "private-phone-sentence.txt": b"Ruf an: 0171 1234567.",
            "private-phone-after-word.txt": b"Fax-0171 1234567",
            "private-phone-ambiguous-id.txt": b"run-0123-4567-8901",
            "private-phone-json.json": b'{"contact":"+49 171 1234567"}',
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
        "ci-artifact-sanitize-test: OK: secrets are redacted; PII, "
        "screenshots, PDFs and nested traces are rejected fail-closed"
    )


if __name__ == "__main__":
    main()
