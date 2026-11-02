#!/usr/bin/env python3
"""Require an explicit user for core one-off containers that mount host paths.

The core image runs as the fixed uid 10001. A checkout or proof directory on
the host is in general not readable for that uid (CI checkouts, mktemp 0700
directories, 0600 files), so every `compose run` of api/worker/pilot-exporter
and every `docker run` of a core image that bind-mounts a host path must pass
`--user` (normally the invoking user). Suites that export
LEONAID_CORE_RUNTIME_USER="$(id -u):$(id -g)" run the whole Compose stack as
the invoking user, so their compose one-offs inherit it; their plain
`docker run` calls still need `--user`. Deliberate exceptions carry the marker
comment `# core-oneoff-user: <reason>` on the line before the command.

Usage: core_oneoff_user.py ROOT
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

MARKER = "core-oneoff-user:"
SKIPPED_PARTS = {".git", ".venv", ".artifacts", ".cache", "node_modules"}
# A compose service of the core image used as the run target.
CORE_SERVICE = re.compile(
    r'(?:^|\s)"?(?:api|worker|pilot-exporter|\$probe_service)"?(?:\s|$)'
)
# A core image passed to `docker run` by variable or Compose image tag.
CORE_IMAGE = re.compile(
    r'\$\{?(?:api_image|core_image|LEONAID_(?:TEST_)?CORE_IMAGE)\}?|-api(?::latest)?"'
)
VOLUME = re.compile(r'(?:--volume[ =]|(?:^|\s)-v\s+)"?([^"\s]+)"?')
BIND_MOUNT = re.compile(r"--mount[ =]\"?type=bind")
USER = re.compile(r"(?:--user[ =]|(?:^|\s)-u\s)")
# Named volumes: Compose-prefixed names and variables that hold volume names.
NAMED_VOLUME = re.compile(
    r"^\$\{?(?:project|[a-z_]*project|[a-z_]*volume)\}?(?:_[a-z0-9-]+)?:"
    r"|^[a-z][a-z0-9_-]*:"
)


def shell_commands(text: str) -> list[tuple[int, str, str]]:
    """Return (line, joined command, preceding line) for each logical line."""
    lines = text.split("\n")
    commands: list[tuple[int, str, str]] = []
    index = 0
    while index < len(lines):
        start = index
        command = lines[index]
        while command.rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            command = command.rstrip()[:-1] + " " + lines[index].strip()
        index += 1
        previous = lines[start - 1] if start > 0 else ""
        commands.append((start + 1, command, previous))
    return commands


def host_mount(command: str) -> bool:
    if BIND_MOUNT.search(command):
        return True
    return any(not NAMED_VOLUME.match(source) for source in VOLUME.findall(command))


# Suites that run their whole isolated stack as the invoking user: compose
# one-offs inherit that user from compose.yml (x-core-user).
STACK_USER = re.compile(
    r'^LEONAID_CORE_RUNTIME_USER="\$\(id -u\):\$\(id -g\)"$\n^export LEONAID_CORE_RUNTIME_USER$',
    re.MULTILINE,
)


def shell_violations(path: Path, text: str) -> list[str]:
    violations = []
    stack_user = STACK_USER.search(text) is not None
    for line, command, previous in shell_commands(text):
        if not re.search(r"\brun\b", command):
            continue
        is_compose_run = re.search(r"\brun\b[^|;&]*?\s--rm\b", command) and (
            CORE_SERVICE.search(command.split(" run ", 1)[-1])
        )
        is_docker_run = "docker run" in command and CORE_IMAGE.search(command)
        if not (is_compose_run or is_docker_run):
            continue
        if stack_user and is_compose_run and not is_docker_run:
            continue
        if not host_mount(command) or USER.search(command):
            continue
        if MARKER in previous:
            continue
        violations.append(f"{path}:{line}")
    return violations


def python_violations(path: Path, text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [f"{path}: unparseable Python, cannot be checked"]
    violations = []
    lines = text.split("\n")
    for node in ast.walk(tree):
        if not isinstance(node, ast.List):
            continue
        strings = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if "run" not in strings or not ({"api", "worker"} & set(strings)):
            continue
        has_host_mount = False
        for flag, source in zip(node.elts, node.elts[1:]):
            if not (
                isinstance(flag, ast.Constant) and flag.value in {"--volume", "-v"}
            ):
                continue
            if isinstance(source, ast.Constant) and isinstance(source.value, str):
                has_host_mount |= NAMED_VOLUME.match(source.value) is None
            else:
                # f-strings and expressions build host paths at runtime.
                has_host_mount = True
        if not has_host_mount or {"--user", "-u"} & set(strings):
            continue
        if node.lineno > 1 and MARKER in lines[node.lineno - 2]:
            continue
        violations.append(f"{path}:{node.lineno}")
    return violations


def candidate_files(root: Path) -> list[Path]:
    files = [root / "leonaid"] if (root / "leonaid").is_file() else []
    for directory in ("tools", "infra", ".github"):
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if SKIPPED_PARTS & set(path.relative_to(root).parts):
                continue
            if path.is_file() and path.suffix in {".sh", ".py", ".yml", ".yaml"}:
                files.append(path)
    return files


def check(root: Path) -> list[str]:
    violations: list[str] = []
    for path in candidate_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(root)
        if path.suffix == ".py":
            violations += python_violations(relative, text)
        else:
            violations += shell_violations(relative, text)
    return violations


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: core_oneoff_user.py ROOT", file=sys.stderr)
        return 64
    violations = check(Path(sys.argv[1]))
    if violations:
        for violation in violations:
            print(
                f"core-oneoff-user: ERROR: {violation}: core one-off mounts a "
                'host path without --user; add --user "$(id -u):$(id -g)" or '
                f"mark a deliberate exception with '# {MARKER} <reason>'",
                file=sys.stderr,
            )
        return 1
    print("core-oneoff-user: OK: every core one-off with a host mount sets --user")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
