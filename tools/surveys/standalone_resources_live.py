#!/usr/bin/env python3
"""Prove real existing volumes survive rejection by each standalone harness."""

import json
import os
import subprocess
import sys
from pathlib import Path


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def cleanup_failure(root):
    name = f"surveys-cleanup-probe-{os.getpid()}"
    helper = str(root / "tools/surveys/standalone_resources.sh")
    environment = {**os.environ, "project": name}
    subprocess.run(
        ["sh", "-c", '. "$1"; standalone_absent', "probe", helper],
        env=environment,
        check=True,
    )
    image = subprocess.check_output(
        [
            "sh",
            "-c",
            '. "$1"; printf %s "$BUN_IMAGE"',
            "probe",
            str(root / "infra/locks/images.env"),
        ],
        text=True,
    )
    volume_created = network_created = container_created = False
    try:
        docker("volume", "create", name)
        volume_created = True
        subnet = subprocess.check_output(
            [
                sys.executable,
                str(root / "tools/surveys/network_override.py"),
                "--single",
            ],
            text=True,
        ).strip()
        docker("network", "create", "--internal", "--subnet", subnet, name)
        network_created = True
        # A stopped real container makes its volume busy without starting a stack.
        docker(
            "container",
            "create",
            "--name",
            name,
            "--network",
            "none",
            "--volume",
            f"{name}:/probe",
            image,
            "true",
        )
        container_created = True
        command = '. "$1"; container=false; volume=true; network=$2; image=false; standalone_cleanup'
        failed = subprocess.run(
            ["sh", "-c", command, "probe", helper, "true"],
            env=environment,
            capture_output=True,
            text=True,
        )
        assert failed.returncode != 0
        assert "volume is in use" in failed.stderr.lower(), failed.stderr
        assert name not in docker("network", "ls", "--format", "{{.Name}}").splitlines()
        network_created = False
        docker("volume", "inspect", name)
        docker("container", "rm", name)
        container_created = False
        subprocess.run(
            ["sh", "-c", command, "probe", helper, "false"],
            env=environment,
            check=True,
        )
        volume_created = False
        print(
            "PASS: busy volume fails cleanup; network still removed; retry removes volume and verifies empty namespace",
            flush=True,
        )
    finally:
        if container_created:
            docker("container", "rm", "-f", name)
        if volume_created:
            docker("volume", "rm", name)
        if network_created:
            docker("network", "rm", name)


def unavailable_daemon(root):
    # Real Docker client failure, not a substitute daemon or command stub.
    environment = {
        **os.environ,
        "DOCKER_HOST": f"unix:///tmp/survey-missing-{os.getpid()}.sock",
    }
    environment.pop("DOCKER_CONTEXT", None)
    for script in ("migrations", "package", "aggregate-engine"):
        failed = subprocess.run(
            ["sh", str(root / "tools/surveys" / (script + ".sh")), str(root)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert failed.returncode != 0
        assert "Cannot read container inventory" in failed.stderr, failed.stderr
    print(
        "PASS: all three harnesses reject unreadable Docker inventory before mutation",
        flush=True,
    )


def main():
    root = Path(__file__).resolve().parents[2]
    checksum = subprocess.check_output(["cksum"], input=str(root), text=True).split()[0]
    for script, prefix in (
        ("migrations", "migrations"),
        ("package", "package"),
        ("aggregate-engine", "engine"),
    ):
        child = subprocess.Popen(
            [
                "sh",
                "-c",
                'read -r ready; exec sh "$1" "$2"',
                "probe",
                str(root / "tools/surveys" / (script + ".sh")),
                str(root),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        name = f"surveys-{prefix}-{checksum}-{child.pid}"
        created = False
        try:
            # Check the complete exact namespace before creating our test volume.
            subprocess.run(
                [
                    "sh",
                    "-c",
                    '. "$1"; standalone_absent',
                    "probe",
                    str(root / "tools/surveys/standalone_resources.sh"),
                ],
                env={**os.environ, "project": name},
                check=True,
            )
            docker("volume", "create", "--label", "leonaid.probe=collision", name)
            created = True
            before = json.loads(docker("volume", "inspect", name))
            stdout, stderr = child.communicate("start\n", timeout=30)
            assert child.returncode != 0, stdout
            assert f"Resource collision or cleanup residue: volume {name}" in stderr, (
                stderr
            )
            assert json.loads(docker("volume", "inspect", name)) == before
            assert not docker("container", "ls", "-aq", "--filter", f"name=^/{name}$")
            assert (
                name
                not in docker("network", "ls", "--format", "{{.Name}}").splitlines()
            )
            assert (
                f"{name}:latest"
                not in docker(
                    "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"
                ).splitlines()
            )
            print(
                f"PASS: {script} rejects existing volume before mutation; original metadata intact",
                flush=True,
            )
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
            if created:
                docker("volume", "rm", name)

    cleanup_failure(root)
    unavailable_daemon(root)


if __name__ == "__main__":
    main()
