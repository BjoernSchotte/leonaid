#!/usr/bin/env python3
"""Exercise the core one-off user guard with real temporary repositories."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

GOOD_SHELL = """#!/bin/sh
compose run --rm --no-deps --user "$(id -u):$(id -g)" \\
  --volume "$root:/repo:ro" \\
  --entrypoint python \\
  api /repo/tools/seed/golden.py seed
# Named volumes only: the core uid owns them.
compose run --rm --no-deps \\
  --volume "${project}_survey-erasure-archive:/archive" \\
  api python -c 'print(1)'
# No host mount at all.
compose run --rm --no-deps --entrypoint alembic api upgrade head
# Another image is not the core image.
docker run --rm --volume "$root:/workspace:ro" "$PYTHON_IMAGE" python -V
# core-oneoff-user: reads only image content through a deliberate root shell
compose run --rm --no-deps --volume "$root:/repo:ro" api true
# Browser and tool containers that write host files run as the host user.
docker run --rm --user "$(id -u):$(id -g)" --env HOME=/tmp \
  --volume "$root:/workspace:ro" --volume "$proof:/proof" \
  "$PLAYWRIGHT_IMAGE" node_modules/.bin/playwright test
# A root container may read a volume when the host shell writes the archive.
docker run --rm --volume "${project}_rustfs-data:/source:ro" \
  "$ALPINE_IMAGE" tar -C /source -cf - . >"$proof/rustfs.tar"
docker run --rm --mount type=bind,src="$root",dst=/workspace,readonly "$ALPINE_IMAGE" true
docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock "$TRIVY_IMAGE" image x
# host-write-user: chown to a service uid requires root
docker run --rm --volume "$workspace:/secrets" "$ALPINE_IMAGE" chown 65534 /secrets/x
"""

GOOD_STACK_USER = """#!/bin/sh
LEONAID_CORE_RUNTIME_USER="$(id -u):$(id -g)"
export LEONAID_CORE_RUNTIME_USER
compose run --rm --no-deps --volume "$proof:/proof" api python /repo/x.py
docker run --rm --user "$LEONAID_CORE_RUNTIME_USER" \\
  --volume "$proof:/proof" "$api_image" python -V
"""

GOOD_PYTHON = """
browser = [
    "docker", "run", "--rm", "--user", "1000:1000",
    "--volume", f"{proof}:/proof", "playwright",
]
readonly = ["docker", "run", "--rm", "-v", f"{root}:/workspace:ro", "python"]
# host-write-user: root reads service-owned volumes, then chowns the archives
archive = ["docker", "run", "--rm", "--volume", f"{fixture}:/fixture", "alpine"]
command = [
    "docker", "compose", "run", "--rm", "--no-deps",
    "--user", "1000:1000",
    "--volume", f"{root}:/repo:ro",
    "api", "python", "/repo/x.py",
]
"""

BAD_CASES = {
    "compose run without --user": (
        "tools/seed/test.sh",
        """#!/bin/sh
phase seed-starting-data compose run --rm --no-deps \\
  --env-from-file "$env_file" \\
  --volume "$root:/repo:ro" \\
  --entrypoint python \\
  api /repo/tools/seed/golden.py seed
""",
    ),
    "worker with a private proof directory": (
        "tools/example/test.sh",
        """#!/bin/sh
"$runner" run --rm --no-deps --volume "$proof:/proof:ro" worker python -V
""",
    ),
    "docker run of the core image": (
        "tools/example/render.sh",
        """#!/bin/sh
docker run --rm --volume "$proof:/proof" --entrypoint python "$api_image" -V
""",
    ),
    "docker run in a stack-user suite": (
        "tools/surveys/example.sh",
        """#!/bin/sh
LEONAID_CORE_RUNTIME_USER="$(id -u):$(id -g)"
export LEONAID_CORE_RUNTIME_USER
docker run --rm --volume "$proof:/proof" "$api_image" python -V
""",
    ),
    "workflow step": (
        ".github/workflows/example.yml",
        """jobs:
  probe:
    steps:
      - run: |
          docker compose run --rm --no-deps \\
            --volume "$GITHUB_WORKSPACE:/repo:ro" api python /repo/x.py
""",
    ),
    "python argument list": (
        "tools/example/stack.py",
        """
command = [
    "docker", "compose", "run", "--rm", "--no-deps",
    "--volume", f"{root}:/repo:ro",
    "api", "python", "/repo/x.py",
]
""",
    ),
    "playwright writing into a proof directory": (
        "tools/surveys/package.sh",
        """#!/bin/sh
docker run --rm --network "container:$project" --env HOME=/tmp --env CI=1 \\
  --volume "$root:/workspace:ro" --volume "$proof:/proof" \\
  "$PLAYWRIGHT_IMAGE" node_modules/.bin/playwright test --output=/proof/x
""",
    ),
    "alpine archive written inside the container": (
        "tools/surveys/infrastructure.sh",
        """#!/bin/sh
docker run --rm --volume "${project}_rustfs-data:/source:ro" --volume "$proof:/proof" \\
  "$ALPINE_IMAGE" tar -C /source -cf /proof/recovery-rustfs.tar .
""",
    ),
    "writable bind mount": (
        "tools/example/bind.sh",
        """#!/bin/sh
docker run --rm --mount type=bind,src="$proof",dst=/proof "$PYTHON_IMAGE" python -V
""",
    ),
    "python docker run with a writable host mount": (
        "tools/example/preflight.py",
        """
command = [
    "docker", "run", "--rm", "--network", "none",
    "-v", f"{root}:/workspace:ro",
    "-v", f"{proof}:/proof",
    "python", "-V",
]
""",
    ),
    "the ./leonaid CLI": (
        "leonaid",
        """#!/bin/sh
compose --profile dev-mail run --rm --no-deps \\
  --volume "$root/.local:/repo/.local" \\
  api /repo/tools/seed/golden.py snapshot
""",
    ),
}


def run(checker: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(checker), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    checker = Path(sys.argv[1]).resolve() / "tools/ci/core_oneoff_user.py"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write(root, "tools/good/test.sh", GOOD_SHELL)
        write(root, "tools/surveys/good.sh", GOOD_STACK_USER)
        write(root, "tools/good/stack.py", GOOD_PYTHON)
        result = run(checker, root)
        if result.returncode != 0:
            raise AssertionError(f"correct one-offs were rejected: {result.stderr}")
        for label, (relative, content) in BAD_CASES.items():
            write(root, relative, content)
            result = run(checker, root)
            if result.returncode == 0 or f"{relative}:" not in result.stderr:
                raise AssertionError(f"{label} was not rejected: {result.stderr}")
            (root / relative).unlink()
        result = run(checker, root)
        if result.returncode != 0:
            raise AssertionError(f"cleaned fixture was rejected: {result.stderr}")
    print(
        "core-oneoff-user-test: OK: correct, named-volume, read-only, stack-user "
        f"and marked one-offs pass; {len(BAD_CASES)} missing --user cases rejected"
    )


if __name__ == "__main__":
    main()
