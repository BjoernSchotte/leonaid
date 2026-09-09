"""Versioned, synthetic-only CI fixture; never reads an existing environment file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

VERSION = 1


def file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inputs(root):
    # Include application code: initialization may execute more than migrations.
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    return sorted(
        name
        for name in set(names)
        if name
        and (
            name.startswith(
                (
                    "src/",
                    "migrations/",
                    "infra/",
                    "tools/testing/",
                    "tools/twenty/",
                    "tools/typst/",
                    "tools/surveys/network",
                    "tests/fixtures/golden/",
                )
            )
            or name in {".env.example", "pyproject.toml", "uv.lock", "alembic.ini"}
        )
    )


def key(root):
    digest = hashlib.sha256(f"synthetic-fixture-{VERSION}-linux-amd64".encode())
    for name in inputs(root):
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Fixture input must be a regular file: {name}")
        digest.update(name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def environment(root):
    # Public, deliberately synthetic credentials. Never copy .env.local into a cache.
    text = (root / ".env.example").read_text()
    result = []
    for line in text.splitlines():
        name = line.split("=", 1)[0]
        value = hashlib.sha256(f"leonaid-ci-synthetic-v1-{name}".encode()).hexdigest()
        replacements = {
            "__GENERATE_HEX_32__": value,
            "__GENERATE_URLSAFE_32__": value,
            "__GENERATE_PASSWORD_24__": value[:24],
            "__GENERATE_PASSWORD_32__": value[:32],
            "__GENERATE_IDENTIFIER_20__": value[:20].upper(),
            "__GENERATE_EMAIL__": "ci-fixture@leonaid.invalid",
        }
        for token, replacement in replacements.items():
            line = line.replace(token, replacement)
        if "__GENERATE_" in line:
            raise ValueError("Unrecognized synthetic environment token")
        result.append(line)
    return "\n".join(result) + "\n"


def validate(root, directory):
    metadata = json.loads((directory / "manifest.json").read_text())
    if metadata.get("version") != VERSION or metadata.get("key") != key(root):
        raise ValueError("CI fixture inputs changed; rebuild required")
    if metadata.get("syntheticOnly") is not True:
        raise ValueError("Missing synthetic fixture provenance")
    for name, digest in metadata["files"].items():
        if not re.fullmatch(
            r"volume-[0-9]+\.tar|integration\.env|pdfs/[a-zA-Z0-9_.-]+", name
        ):
            raise ValueError("Unexpected fixture payload")
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Fixture payload must be a regular file")
        if file_digest(path) != digest:
            raise ValueError("Fixture payload checksum mismatch")
        if name.endswith(".tar"):
            with tarfile.open(path) as archive:
                for member in archive:
                    parts = PurePosixPath(member.name).parts
                    if member.name.startswith("/") or ".." in parts:
                        raise ValueError("Unsafe fixture archive path")
                    if not (member.isfile() or member.isdir()):
                        raise ValueError(
                            "Fixture archives cannot contain links or devices"
                        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]*", metadata.get("integrationKey", "")):
        raise ValueError("Invalid synthetic integration key")
    if any(not re.fullmatch(r"[a-z0-9-]+", name) for name in metadata["volumes"]):
        raise ValueError("Invalid fixture volume name")
    return metadata


def build(root, directory):
    from shared_stack import SharedStack

    if directory.exists():
        raise ValueError("Refusing to replace an existing fixture directory")
    with tempfile.TemporaryDirectory(prefix="leonaid-ci-fixture-source-") as temporary:
        source = Path(temporary)
        # Only repository sources are copied; never local files, snapshots or credentials.
        names = (
            subprocess.check_output(
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                cwd=root,
            )
            .decode()
            .split("\0")
        )
        for name in sorted(set(names)):
            if not name or name.startswith((".env", ".local/", ".artifacts/", ".git/")):
                continue
            path = root / name
            if path.is_symlink() or not path.is_file():
                continue
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        (source / ".env.local").write_text(environment(root))
        (source / ".env.local").chmod(0o600)
        stack = SharedStack(source, "documents")
        stack.env.pop("LEONAID_CI_FIXTURE", None)
        try:
            stack.initialize()
            directory.mkdir(mode=0o700, parents=True)
            files = {}
            for path in sorted(stack.directory.rglob("*")):
                name = path.relative_to(stack.directory).as_posix()
                if path.is_file() and re.fullmatch(
                    r"volume-[0-9]+\.tar|integration\.env|pdfs/[a-zA-Z0-9_.-]+", name
                ):
                    target = directory / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    files[name] = hashlib.file_digest(
                        target.open("rb"), "sha256"
                    ).hexdigest()
            metadata = {
                "version": VERSION,
                "key": key(root),
                "syntheticOnly": True,
                "volumes": [v.removeprefix(stack.project + "_") for v in stack.volumes],
                "integrationKey": stack.env["TWENTY_INTEGRATION_API_KEY"],
                "files": files,
            }
            (directory / "manifest.json").write_text(json.dumps(metadata))
            validate(root, directory)
        finally:
            stack.close()


def activate(root, directory):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError(
            "CI fixture activation is restricted to an ephemeral GitHub job"
        )
    validate(root, directory)
    (root / ".env.local").write_text(environment(root))
    (root / ".env.local").chmod(0o600)
    with open(os.environ["GITHUB_ENV"], "a") as output:
        print(f"LEONAID_CI_FIXTURE={directory.resolve()}", file=output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["key", "build", "validate", "activate"])
    parser.add_argument("directory", nargs="?", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.command == "key":
        print(key(root))
    else:
        globals()[args.command](root, args.directory)
