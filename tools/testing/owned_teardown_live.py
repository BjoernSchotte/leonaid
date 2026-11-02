"""Prove failure diagnostics and teardown leave no Docker objects behind.

Runs against the real Docker daemon (through a host slot, it starts mailpit
and builds the api image):

1. A project with the Golden Journey file set (rollback-network overlay plus
   isolation file, networks reserved first) gets failure diagnostics from
   tools/ci/capture-failure.sh. Its `compose run api` must reuse the project's
   own file set: with compose.yml alone it created `core-data`/`crm-data`
   from Docker's default pools, which the suite's `down` did not know.
2. After the suite-style `--profile '*' down`, verify_owned_project_removed
   must find nothing and remove the built images.
3. A planted leak (stopped one-off container, network, volume) is listed,
   removed by label and reported as a failure.
4. A tag named after the project but built under another project's label
   (EmDash recovery targets reuse the source's image names) is removed; a tag
   of a project whose name extends "<project>-" is kept.

Usage: python3 tools/testing/owned_teardown_live.py
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/testing/owned_teardown.sh"


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def inventory(project: str) -> dict[str, list[str]]:
    label = f"label=com.docker.compose.project={project}"
    return {
        "containers": docker(
            "ps", "-a", "--filter", label, "--format", "{{.Names}}"
        ).split(),
        "networks": docker(
            "network", "ls", "--filter", label, "--format", "{{.Name}}"
        ).split(),
        "volumes": docker(
            "volume", "ls", "--filter", label, "--format", "{{.Name}}"
        ).split(),
        "images": docker(
            "image",
            "ls",
            "--filter",
            label,
            "--format",
            "{{.Repository}}:{{.Tag}}",
        ).split(),
    }


def verify(project: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            "-c",
            '. "$1"; verify_owned_project_removed "$2"',
            "owned-teardown-live",
            str(HELPER),
            project,
        ],
        capture_output=True,
        text=True,
    )


def diagnostics_do_not_leak(project: str, directory: Path) -> None:
    isolation = directory / "compose-isolation.yml"
    compose = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(ROOT / ".env.local"),
        "--file",
        str(ROOT / "infra/compose/compose.yml"),
        "--file",
        str(ROOT / "infra/upgrade/compose.rollback-network.yml"),
        "--file",
        str(isolation),
    ]
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/surveys/network_override.py"),
            str(isolation),
        ],
        check=True,
    )
    model = subprocess.check_output(
        [*compose, "--profile", "*", "config", "--format", "json"], text=True
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/testing/reserve_compose_networks.py"),
            project,
            str(isolation),
        ],
        input=model,
        text=True,
        check=True,
    )
    declared = set(inventory(project)["networks"])
    subprocess.run(
        [*compose, "--profile", "dev-mail", "up", "--detach", "--wait", "mailpit"],
        check=True,
    )
    artifacts = directory / "artifacts"
    proof = directory / "proof"
    proof.mkdir()
    subprocess.run(
        [
            "sh",
            str(ROOT / "tools/ci/capture-failure.sh"),
            str(ROOT),
            str(proof),
            project,
        ],
        env={**os.environ, "LEONAID_CI_ARTIFACT_DIR": str(artifacts)},
        check=True,
    )
    log = (artifacts / f"runtime-{project}" / "runtime-diagnostics.log").read_text()
    created = set(inventory(project)["networks"]) - declared
    assert not created, f"diagnostics created undeclared networks: {created}"
    assert (artifacts / f"runtime-{project}" / "services.txt").exists()
    print(
        f"owned-teardown-live: diagnostics ran with the suite file set ({len(log)} log bytes)"
    )
    subprocess.run(
        [*compose, "--profile", "*", "down", "--volumes", "--remove-orphans"],
        check=True,
        capture_output=True,
    )
    result = verify(project)
    assert result.returncode == 0, result.stderr
    remaining = inventory(project)
    assert not any(remaining.values()), remaining
    print(
        "owned-teardown-live: suite teardown left no containers, networks, volumes or images"
    )


def planted_leak_is_reported_and_removed(project: str, image: str) -> None:
    label = f"com.docker.compose.project={project}"
    docker("network", "create", "--internal", "--label", label, f"{project}_core-data")
    docker("volume", "create", "--label", label, f"{project}_data")
    docker(
        "create",
        "--label",
        label,
        "--label",
        "com.docker.compose.oneoff=True",
        "--network",
        f"{project}_core-data",
        "--name",
        f"{project}-api-run-1",
        image,
        "true",
    )
    result = verify(project)
    assert result.returncode == 1, result
    for name in (f"{project}-api-run-1", f"{project}_core-data", f"{project}_data"):
        assert name in result.stderr, (name, result.stderr)
    remaining = inventory(project)
    assert not any(remaining.values()), remaining
    assert verify(project).returncode == 0
    print("owned-teardown-live: planted leak was listed, removed and failed the check")


def labelled_image(base: str, tag: str, builder: str) -> None:
    subprocess.run(
        [
            "docker",
            "build",
            "--quiet",
            "--network",
            "none",
            "--label",
            f"com.docker.compose.project={builder}",
            "--tag",
            tag,
            "-",
        ],
        input=f"FROM {base}\n",
        text=True,
        check=True,
        capture_output=True,
    )


def cross_labelled_images_are_removed(project: str, image: str) -> None:
    # An EmDash recovery target builds under the source's image names.
    borrowed = f"{project}-api:latest"
    labelled_image(image, borrowed, f"leonaid-restore-{project}")
    # A project named "<project>-child" owns its own tags.
    foreign = f"{project}-child-api:latest"
    labelled_image(image, foreign, f"{project}-child")
    try:
        result = verify(project)
        assert result.returncode == 0, result.stderr
        tags = docker(
            "image",
            "ls",
            "--filter",
            f"reference={project}-*",
            "--format",
            "{{.Repository}}:{{.Tag}}",
        ).split()
        assert borrowed not in tags, tags
        assert foreign in tags, tags
    finally:
        subprocess.run(
            ["docker", "image", "rm", borrowed, foreign], capture_output=True
        )
    print(
        "owned-teardown-live: tag built under another project's label removed; "
        "a longer project's tag kept"
    )


def main() -> None:
    suffix = os.getpid()
    projects = [f"leonaid-teardown-live-{suffix}", f"leonaid-teardown-leak-{suffix}"]
    for project in projects:
        assert not any(inventory(project).values()), f"{project} already exists"
    from_images = (ROOT / "infra/locks/images.env").read_text().splitlines()
    image = next(
        line.split("=", 1)[1].strip("'\"")
        for line in from_images
        if line.startswith("MAILPIT_IMAGE=")
    )
    try:
        with tempfile.TemporaryDirectory() as directory:
            diagnostics_do_not_leak(projects[0], Path(directory))
        planted_leak_is_reported_and_removed(projects[1], image)
        cross_labelled_images_are_removed(projects[1], image)
    finally:
        # Never leave this proof's own objects behind, even when it fails.
        for project in projects:
            sys.stderr.write(verify(project).stderr)


if __name__ == "__main__":
    main()
