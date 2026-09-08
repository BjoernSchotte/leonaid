"""Prove deferred-network collision recovery against the real Docker daemon."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    project = f"surveys-network-reservation-{os.getpid()}"
    blocker = project + "-blocker"
    expected_names = {blocker, f"{project}_edge", f"{project}_core-data"}
    assert not expected_names.intersection(
        docker("network", "ls", "--format", "{{.Name}}").splitlines()
    )
    owned: list[str] = []
    try:
        subnet = subprocess.check_output(
            [
                sys.executable,
                str(root / "tools/surveys/network_override.py"),
                "--single",
            ],
            text=True,
        ).strip()
        blocker_id = docker(
            "network", "create", "--internal", "--subnet", subnet, blocker
        )
        owned.append(blocker)
        with tempfile.TemporaryDirectory() as directory:
            override = Path(directory) / "compose.yml"
            override.write_text(
                "networks:\n"
                + "".join(
                    f"  {key}:\n    ipam:\n      config:\n        - subnet: {subnet}\n"
                    for key in ("edge", "core-data")
                )
            )
            networks = {
                key: {"name": f"{project}_{key}", "internal": internal}
                for key, internal in (("edge", False), ("core-data", True))
            }
            invalid = {key: dict(value) for key, value in networks.items()}
            invalid["core-data"]["name"] = blocker
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(root / "tools/testing/reserve_compose_networks.py"),
                    project,
                    str(override),
                ],
                input=json.dumps({"networks": invalid}),
                capture_output=True,
                text=True,
            )
            assert rejected.returncode == 1
            assert expected_names.intersection(
                docker("network", "ls", "--format", "{{.Name}}").splitlines()
            ) == {blocker}
            owned.extend(settings["name"] for settings in networks.values())
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "tools/testing/reserve_compose_networks.py"),
                    project,
                    str(override),
                ],
                input=json.dumps({"networks": networks}),
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr
            assert "2 owned networks" in result.stdout
            actual = json.loads(docker("network", "inspect", *owned))
            assert actual[0]["Id"] == blocker_id
            assert actual[0]["IPAM"]["Config"][0]["Subnet"] == subnet
            for record, internal in zip(actual[1:], (False, True), strict=True):
                assert record["Internal"] is internal
                assert record["Labels"]["com.docker.compose.project"] == project
                selected = record["IPAM"]["Config"][0]["Subnet"]
                assert selected != subnet and selected in override.read_text()
            assert (
                len({record["IPAM"]["Config"][0]["Subnet"] for record in actual}) == 3
            )
            print(
                "PASS: two stale selections resolved; blocker unchanged; owned subnets, labels and internal flags verified"
            )
    finally:
        for name in reversed(owned):
            probe = subprocess.run(
                ["docker", "network", "inspect", name], capture_output=True
            )
            if probe.returncode == 0:
                docker("network", "rm", name)
        remaining = docker(
            "network",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        )
        assert not remaining
    print("PASS: reservation proof removed only its owned networks")


if __name__ == "__main__":
    main()
