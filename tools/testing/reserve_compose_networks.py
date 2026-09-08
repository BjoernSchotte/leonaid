"""Reserve owned Compose networks before deferred service creation can race."""

import ipaddress
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys


def reserve(project: str, override: Path, configuration: dict) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]+", project):
        raise ValueError("invalid owned project")
    networks = configuration["networks"]
    document = override.read_text()
    prepared = []
    for key, settings in networks.items():
        if (
            not re.fullmatch(r"[a-z][a-z-]+", key)
            or settings.get("name") != f"{project}_{key}"
            or settings.get("external", False)
            or settings.get("driver", "bridge") != "bridge"
            or settings.get("enable_ipv6", False)
        ):
            raise ValueError("unsupported owned network configuration")
        pattern = rf"(  {re.escape(key)}:\n    ipam:\n      config:\n        - subnet: )([^\n]+)"
        match = re.search(pattern, document)
        if match is None:
            raise ValueError("missing explicit network subnet")
        planned = ipaddress.ip_network(match[2])
        prepared.append((key, settings, pattern, planned))
    if not prepared:
        raise ValueError("no owned networks")
    pool = list(ipaddress.ip_network("172.30.128.0/17").subnets(new_prefix=24))
    version = subprocess.check_output(
        ["docker", "compose", "version", "--short"], text=True
    ).strip()
    retries = 0
    for key, settings, pattern, planned in prepared:
        alternatives = [candidate for candidate in pool if candidate != planned]
        secrets.SystemRandom().shuffle(alternatives)
        for subnet in [planned, *alternatives]:
            command = [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--label",
                f"com.docker.compose.project={project}",
                "--label",
                f"com.docker.compose.network={key}",
                "--label",
                f"com.docker.compose.version={version}",
                "--subnet",
                str(subnet),
            ]
            if settings.get("internal", False):
                command.append("--internal")
            command.append(settings["name"])
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                document, count = re.subn(
                    pattern, lambda match: match[1] + str(subnet), document
                )
                assert count == 1
                break
            if "Pool overlaps" not in result.stderr:
                raise RuntimeError(
                    "owned network reservation failed; caller must clean its project"
                )
            retries += 1
        else:
            raise RuntimeError("no free subnet for owned network")
    temporary = override.with_suffix(".reserved.tmp")
    temporary.write_text(document)
    temporary.replace(override)
    print(
        f"Reserved {len(prepared)} owned networks before service startup; {retries} subnet collisions resolved"
    )


if __name__ == "__main__":
    try:
        reserve(sys.argv[1], Path(sys.argv[2]), json.load(sys.stdin))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            f"network-reservation: failed ({type(error).__name__}); owned cleanup required",
            file=sys.stderr,
        )
        raise SystemExit(1)
