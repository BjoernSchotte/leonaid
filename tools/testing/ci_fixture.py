"""Versioned, synthetic-only CI fixture; never reads an existing environment file."""

from __future__ import annotations

import argparse
import base64
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
    # Construction runs migrations, CRM provisioning and PDF rendering, never API
    # request handlers. Ordinary feature changes must not rebuild initialized data.
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
        # Documentation next to the inputs (infra/**/README.md) builds nothing;
        # a README change rebuilt the fixture (about 4 min, run 42530398039).
        and not name.endswith(".md")
        and (
            name.startswith(
                (
                    "src/leonaid/adapters/typst/",
                    "src/leonaid/modules/surveys/adapters/typst/",
                    "src/leonaid/modules/surveys/domain/",
                    "src/leonaid/domain/",
                    "migrations/",
                    "infra/",
                    "tools/testing/",
                    "tools/twenty/",
                    "tools/typst/",
                    "tools/surveys/network",
                    "tests/fixtures/golden/",
                )
            )
            or name
            in {
                ".env.example",
                "pyproject.toml",
                "uv.lock",
                "alembic.ini",
                "src/leonaid/application/invoice_documents.py",
            }
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


PORT_KEYS = ("LEONAID_HTTP_PORT", "LEONAID_HTTPS_PORT")
PROJECT_KEY = "LEONAID_COMPOSE_PROJECT"
# Per checkout, not part of the synthetic secrets: the host ports publish only
# the developer's own stack (test stacks run with fixed ports and no published
# host ports) and every stack call passes its own --project-name.
LOCAL_KEYS = (*PORT_KEYS, PROJECT_KEY)
COMPOSE_PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]*")


def environment(
    root, http_port="8080", https_port="8443", compose_project="leonaid-ci"
):
    # Public, deliberately synthetic credentials. Never copy .env.local into a cache.
    ports = dict(zip(PORT_KEYS, (http_port, https_port)))
    if not all(str(port).isdigit() for port in ports.values()):
        raise ValueError("Synthetic environment ports must be numeric")
    if not COMPOSE_PROJECT.fullmatch(compose_project):
        raise ValueError("Synthetic environment needs a valid Compose project")
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
            # The digest as a P-256 scalar (a public test key, like the rest).
            "__GENERATE_P256_PRIVATE_KEY__": base64.urlsafe_b64encode(
                bytes.fromhex(value)
            )
            .decode()
            .rstrip("="),
            # Left unreplaced (and rejected below) for any other key.
            "__HOST_PORT__": str(ports.get(name, "__HOST_PORT__")),
            "__COMPOSE_PROJECT__": compose_project,
        }
        for token, replacement in replacements.items():
            line = line.replace(token, replacement)
        if "__GENERATE_" in line or "__HOST_PORT__" in line:
            raise ValueError("Unrecognized synthetic environment token")
        result.append(line)
    return "\n".join(result) + "\n"


def local_settings(text):
    """(HTTP port, HTTPS port, Compose project) of an env file text, or None.

    A file written before the project setting existed reports the CI default.
    """
    values = dict(
        line.split("=", 1) for line in text.splitlines() if line.startswith(LOCAL_KEYS)
    )
    found = tuple(values.get(key, "") for key in PORT_KEYS)
    project = values.get(PROJECT_KEY, "leonaid-ci")
    if not all(value.isdigit() for value in found) or not COMPOSE_PROJECT.fullmatch(
        project
    ):
        return None
    return (*found, project)


def ports(text):
    """Return the (HTTP, HTTPS) host ports of an env file text, or None."""
    settings = local_settings(text)
    return None if settings is None else settings[:2]


def is_synthetic(root, text):
    """True if `text` is exactly the synthetic environment, apart from the
    per-checkout host ports and Compose project."""
    settings = local_settings(text)
    return settings is not None and text == environment(root, *settings)


def is_synthetic_subset(root, text):
    """True if every setting in `text` has its synthetic value.

    Keys that `.env.example` gained after the file was written may be missing;
    bootstrap then rewrites the full synthetic environment. Any other value
    (a generated secret, a changed setting, an unknown key) is not synthetic.
    """
    settings = local_settings(text)
    if settings is None:
        return False
    expected = {
        line.split("=", 1)[0]: line
        for line in environment(root, *settings).splitlines()
        if "=" in line and not line.startswith("#")
    }
    lines = [
        line for line in text.splitlines() if "=" in line and not line.startswith("#")
    ]
    return all(expected.get(line.split("=", 1)[0]) == line for line in lines)


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


def build(root, directory, output=None):
    if __package__:
        from .shared_stack import SharedStack
    else:
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
        stack = SharedStack(source, "documents", output=output)
        stack.env.pop("LEONAID_CI_FIXTURE", None)
        stack.env["LEONAID_FIXTURE_BUILD"] = "1"
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


def write_environment(
    root, target, http_port, https_port, compose_project="leonaid-ci"
):
    """Write the synthetic environment for a local checkout (bootstrap).

    Refuses to replace an environment with other (generated) secrets: those
    belong to an existing development stack whose data would stop working.
    """
    if target.exists() and not is_synthetic_subset(root, target.read_text()):
        raise ValueError(
            f"{target.name} holds generated secrets; delete it (and reset this "
            "checkout's development stack) to switch to the synthetic environment"
        )
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(environment(root, http_port, https_port, compose_project))
    temporary.chmod(0o600)
    temporary.replace(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["key", "build", "validate", "activate", "environment", "is-synthetic"],
    )
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--http-port", default="8080")
    parser.add_argument("--https-port", default="8443")
    parser.add_argument("--compose-project", default="leonaid-ci")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.command == "key":
        print(key(root))
    elif args.command == "is-synthetic":
        raise SystemExit(
            0 if is_synthetic_subset(root, args.directory.read_text()) else 1
        )
    elif args.command == "environment":
        try:
            write_environment(
                root,
                args.directory,
                args.http_port,
                args.https_port,
                args.compose_project,
            )
        except ValueError as error:
            raise SystemExit(f"synthetic-environment: ERROR: {error}") from None
    else:
        globals()[args.command](root, args.directory)
