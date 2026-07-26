#!/usr/bin/env python3
"""Redact generated CI evidence before it can be uploaded."""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path

TEXT_SUFFIXES = {
    ".html",
    ".json",
    ".log",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
SECRET_MARKERS = ("KEY", "MAGIC", "PASSWORD", "SECRET", "SESSION", "TOKEN")


def secrets_from(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if any(marker in key.upper() for marker in SECRET_MARKERS) and len(value) >= 8:
            result[key] = value
    return result


def replace_binary(data: bytes, secrets: dict[str, str]) -> tuple[bytes, int]:
    replacements = 0
    sanitized = data
    for secret in secrets.values():
        encoded = secret.encode()
        count = sanitized.count(encoded)
        if count:
            replacements += count
            sanitized = sanitized.replace(encoded, b"*" * len(encoded))
    return sanitized, replacements


def sanitize_zip(path: Path, secrets: dict[str, str]) -> int:
    replacements = 0
    original_mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with (
            zipfile.ZipFile(path, "r") as source,
            zipfile.ZipFile(temporary_path, "w") as target,
        ):
            for entry in source.infolist():
                data, count = replace_binary(source.read(entry.filename), secrets)
                replacements += count
                target.writestr(entry, data)
        temporary_path.chmod(original_mode)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return replacements


def sanitize(
    directory: Path,
    env_files: list[Path],
    env_directories: list[Path],
) -> tuple[int, int]:
    secrets: dict[str, str] = {}
    for env_file in env_files:
        secrets.update(secrets_from(env_file))
    for env_directory in env_directories:
        if env_directory.is_dir():
            for env_file in env_directory.rglob("*.env"):
                secrets.update(secrets_from(env_file))
    checked = 0
    replacements = 0
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        checked += 1
        if path.suffix.casefold() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            sanitized = text
            for key, secret in secrets.items():
                count = sanitized.count(secret)
                if count:
                    replacements += count
                    sanitized = sanitized.replace(secret, f"[REDACTED:{key}]")
            if sanitized != text:
                path.write_text(sanitized, encoding="utf-8")
        elif path.suffix.casefold() == ".zip" and zipfile.is_zipfile(path):
            replacements += sanitize_zip(path, secrets)
        else:
            data = path.read_bytes()
            sanitized_data, count = replace_binary(data, secrets)
            replacements += count
            if sanitized_data != data:
                path.write_bytes(sanitized_data)
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.casefold() == ".zip" and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as archive:
                remaining = any(
                    secret.encode() in archive.read(entry.filename)
                    for entry in archive.infolist()
                    for secret in secrets.values()
                )
        else:
            data = path.read_bytes()
            remaining = any(secret.encode() in data for secret in secrets.values())
        if remaining:
            raise RuntimeError(f"Secret konnte nicht redigiert werden: {path}")
    return checked, replacements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("env_files", type=Path, nargs="+")
    parser.add_argument(
        "--env-directory",
        action="append",
        default=[],
        type=Path,
    )
    arguments = parser.parse_args()
    checked, replacements = sanitize(
        arguments.directory.resolve(),
        [path.resolve() for path in arguments.env_files],
        [path.resolve() for path in arguments.env_directory],
    )
    print(
        f"ci-artifact-sanitize: OK: {checked} Artefakte geprüft, "
        f"{replacements} Secret-Vorkommen redigiert"
    )


if __name__ == "__main__":
    main()
