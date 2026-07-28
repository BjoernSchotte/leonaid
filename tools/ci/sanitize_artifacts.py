#!/usr/bin/env python3
"""Sanitize public CI evidence and reject private or opaque payloads."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

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
ARCHIVE_SUFFIXES = {".zip"}
PRIVATE_BINARY_SUFFIXES = {
    ".avif",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".webp",
    ".xls",
    ".xlsx",
}
PRIVATE_RECORDING_SUFFIXES = {".csv", ".har", ".trace"}
SECRET_MARKERS = ("KEY", "MAGIC", "PASSWORD", "SECRET", "SESSION", "TOKEN")
MAX_ARCHIVE_DEPTH = 4
MAX_ARCHIVE_ENTRIES = 2_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_TEXT_BYTES = 32 * 1024 * 1024

EMAIL_PATTERN = re.compile(
    rb"(?<![A-Za-z0-9._%+-])"
    rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    rb"(?![A-Za-z0-9.-])"
)
PHONE_PATTERN = re.compile(
    rb"(?<!\w)(?:\+49|0049|0)[1-9][0-9]{1,4}"
    rb"(?:[\s()/.-]*[0-9]){6,12}(?!\w)"
)
PRIVATE_CANARY_PATTERN = re.compile(
    rb"(?:PII|PRIVATE|INVOICE|DOCUMENT|SECRET|TOKEN)"
    rb"_[A-Z0-9_]*CANARY_[A-Za-z0-9_-]+"
)
PRIVATE_JSON_KEYS = {
    "address",
    "bankaccount",
    "bic",
    "billingaddress",
    "documentbytes",
    "displayname",
    "email",
    "firstname",
    "iban",
    "invoicenumber",
    "lastname",
    "phonenumber",
    "postalcode",
    "recipientname",
    "street",
    "taxnumber",
    "vatid",
}


class SanitizationFailure(RuntimeError):
    """Raised when an artifact cannot be proven safe for public upload."""


@dataclass(frozen=True)
class SanitizeResult:
    payload: bytes
    checked: int
    replacements: int


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


def redact_known_secrets(data: bytes, secrets: dict[str, str]) -> tuple[bytes, int]:
    replacements = 0
    sanitized = data
    for key, secret in secrets.items():
        encoded = secret.encode()
        count = sanitized.count(encoded)
        if count:
            replacements += count
            replacement = f"[REDACTED:{key}]".encode()
            sanitized = sanitized.replace(encoded, replacement)
    return sanitized, replacements


def reject_private_signatures(data: bytes, label: str) -> None:
    for match in EMAIL_PATTERN.finditer(data):
        email = match.group(0).decode("ascii", errors="ignore").casefold()
        if not email.endswith(".invalid"):
            raise SanitizationFailure(
                f"personenbezogene E-Mail-Signatur in öffentlichem Artefakt: {label}"
            )
    if PHONE_PATTERN.search(data):
        raise SanitizationFailure(f"Telefon-Signatur in öffentlichem Artefakt: {label}")
    if PRIVATE_CANARY_PATTERN.search(data):
        raise SanitizationFailure(
            f"private Canary-Signatur in öffentlichem Artefakt: {label}"
        )


def reject_private_json_fields(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in PRIVATE_JSON_KEYS:
                raise SanitizationFailure(
                    f"privates JSON-Feld {key!r} in öffentlichem Artefakt: {label}"
                )
            reject_private_json_fields(item, label)
    elif isinstance(value, list):
        for item in value:
            reject_private_json_fields(item, label)


def sanitize_text(
    data: bytes,
    *,
    label: str,
    suffix: str,
    secrets: dict[str, str],
) -> SanitizeResult:
    if len(data) > MAX_TEXT_BYTES:
        raise SanitizationFailure(f"Textartefakt überschreitet Größenlimit: {label}")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SanitizationFailure(
            f"Textartefakt ist nicht valides UTF-8: {label}"
        ) from error
    sanitized, replacements = redact_known_secrets(data, secrets)
    reject_private_signatures(sanitized, label)
    if suffix == ".json":
        try:
            value = json.loads(sanitized)
        except json.JSONDecodeError as error:
            raise SanitizationFailure(
                f"JSON-Artefakt ist nicht strukturell prüfbar: {label}"
            ) from error
        reject_private_json_fields(value, label)
    return SanitizeResult(sanitized, checked=1, replacements=replacements)


def safe_archive_name(name: str, label: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\x00" in name or "\\" in name:
        raise SanitizationFailure(f"unsicherer ZIP-Pfad in {label}: {name!r}")
    reject_private_signatures(name.encode("utf-8"), f"{label} (ZIP-Pfad)")
    return path


def sanitize_payload(
    data: bytes,
    *,
    name: str,
    label: str,
    secrets: dict[str, str],
    depth: int,
) -> SanitizeResult:
    suffix = PurePosixPath(name).suffix.casefold()
    stream = io.BytesIO(data)
    is_archive = suffix in ARCHIVE_SUFFIXES or zipfile.is_zipfile(stream)
    if is_archive:
        return sanitize_zip_bytes(
            data,
            label=label,
            secrets=secrets,
            depth=depth + 1,
        )
    if suffix in TEXT_SUFFIXES:
        return sanitize_text(data, label=label, suffix=suffix, secrets=secrets)
    if suffix in PRIVATE_BINARY_SUFFIXES | PRIVATE_RECORDING_SUFFIXES:
        raise SanitizationFailure(
            f"private/opaque Evidence darf nicht öffentlich hochgeladen werden: {label}"
        )
    raise SanitizationFailure(f"nicht freigegebener Artefakttyp: {label}")


def sanitize_zip_bytes(
    data: bytes,
    *,
    label: str,
    secrets: dict[str, str],
    depth: int,
) -> SanitizeResult:
    if depth > MAX_ARCHIVE_DEPTH:
        raise SanitizationFailure(f"ZIP-Verschachtelung zu tief: {label}")
    checked = 1
    replacements = 0
    total_uncompressed = 0
    output = io.BytesIO()
    try:
        with (
            zipfile.ZipFile(io.BytesIO(data), "r") as source,
            zipfile.ZipFile(output, "w") as target,
        ):
            if source.comment:
                comment = sanitize_text(
                    source.comment,
                    label=f"{label} (ZIP-Kommentar)",
                    suffix=".txt",
                    secrets=secrets,
                )
                checked += comment.checked
                replacements += comment.replacements
                target.comment = comment.payload
            entries = source.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise SanitizationFailure(f"zu viele ZIP-Einträge: {label}")
            seen_names: set[str] = set()
            for entry in entries:
                safe_archive_name(entry.filename, label)
                if entry.filename in seen_names:
                    raise SanitizationFailure(
                        f"doppelter ZIP-Pfad ist nicht eindeutig: {label}"
                    )
                seen_names.add(entry.filename)
                if entry.flag_bits & 0x1:
                    raise SanitizationFailure(
                        f"verschlüsselter ZIP-Eintrag ist nicht prüfbar: {label}"
                    )
                unix_type = (entry.external_attr >> 16) & 0o170000
                if unix_type == 0o120000:
                    raise SanitizationFailure(
                        f"ZIP-Symlink ist nicht als öffentliche Evidence erlaubt: {label}"
                    )
                total_uncompressed += entry.file_size
                if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise SanitizationFailure(
                        f"ZIP überschreitet Entpacklimit: {label}"
                    )
                if entry.is_dir():
                    entry.comment = b""
                    entry.extra = b""
                    target.writestr(entry, b"")
                    continue
                payload = source.read(entry)
                result = sanitize_payload(
                    payload,
                    name=entry.filename,
                    label=f"{label}!/{entry.filename}",
                    secrets=secrets,
                    depth=depth,
                )
                checked += result.checked
                replacements += result.replacements
                entry.comment = b""
                entry.extra = b""
                target.writestr(entry, result.payload)
    except zipfile.BadZipFile as error:
        raise SanitizationFailure(f"defektes ZIP-Artefakt: {label}") from error
    return SanitizeResult(
        output.getvalue(),
        checked=checked,
        replacements=replacements,
    )


def write_atomically(path: Path, payload: bytes) -> None:
    original_mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary_path = Path(temporary.name)
    try:
        os.chmod(temporary_path, original_mode)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def sanitize(
    directory: Path,
    env_files: list[Path],
    env_directories: list[Path],
) -> tuple[int, int]:
    if not directory.is_dir():
        raise SanitizationFailure(f"Artefaktverzeichnis fehlt: {directory}")
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
        relative = path.relative_to(directory).as_posix()
        reject_private_signatures(relative.encode("utf-8"), relative)
        result = sanitize_payload(
            path.read_bytes(),
            name=path.name,
            label=relative,
            secrets=secrets,
            depth=0,
        )
        checked += result.checked
        replacements += result.replacements
        if result.payload != path.read_bytes():
            write_atomically(path, result.payload)
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
    try:
        checked, replacements = sanitize(
            arguments.directory.resolve(),
            [path.resolve() for path in arguments.env_files],
            [path.resolve() for path in arguments.env_directory],
        )
    except SanitizationFailure as error:
        parser.exit(70, f"ci-artifact-sanitize: BLOCKED: {error}\n")
    print(
        f"ci-artifact-sanitize: OK: {checked} Artefakte geprüft, "
        f"{replacements} Secret-Vorkommen redigiert"
    )


if __name__ == "__main__":
    main()
