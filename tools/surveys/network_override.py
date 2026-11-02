"""Allocate explicit non-overlapping survey test subnets; never prune networks.

Usage:
  network_override.py OVERRIDE [VOLUME]   write a Compose override with subnets
  network_override.py --single            print one currently unused subnet
  network_override.py --create-internal NAME
                                          create the internal network NAME

A written override only selects subnets that are free at that moment; the
caller must reserve them with tools/testing/reserve_compose_networks.py before
anything else can create networks. --create-internal creates the network
itself and retries with the next candidate when a concurrent stack took the
subnet in between ("Pool overlaps"), so the Docker daemon arbitrates.
"""

import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "testing"))
from subnet_pools import candidate_subnets  # noqa: E402

ids = subprocess.check_output(["docker", "network", "ls", "-q"], text=True).split()
networks = (
    json.loads(
        subprocess.check_output(["docker", "network", "inspect", *ids], text=True)
    )
    if ids
    else []
)
used = [
    ipaddress.ip_network(item["Subnet"])
    for network in networks
    for item in (network["IPAM"].get("Config") or [])
    if item.get("Subnet")
]
names = [
    "edge",
    "core-data",
    "cms-data",
    "crm-data",
    "storage-data",
    "mail-data",
    "telemetry",
    "mailing-data",
]
if sys.argv[1] == "--create-internal":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: network_override.py --create-internal NAME")
    for subnet in candidate_subnets(used):
        created = subprocess.run(
            [
                "docker",
                "network",
                "create",
                "--internal",
                "--subnet",
                str(subnet),
                sys.argv[2],
            ],
            capture_output=True,
            text=True,
        )
        if created.returncode == 0:
            print(subnet)
            raise SystemExit(0)
        if "Pool overlaps" not in created.stderr:
            sys.stderr.write(created.stderr)
            raise SystemExit("Creating the test network failed")
    raise SystemExit("No free survey test subnet; existing networks are untouched")
# Overlays for stacks with extra networks (the pilot's mail-egress) name them
# here so they also get an explicit subnet from the test pools.
names += [
    name.strip()
    for name in os.environ.get("LEONAID_TEST_EXTRA_NETWORKS", "").split(",")
    if name.strip()
]
count = 1 if sys.argv[1] == "--single" else len(names)
selected = candidate_subnets(used)[:count]
if len(selected) != count:
    raise SystemExit("No free survey test subnets; existing networks are untouched")
if count == 1:
    print(selected[0])
    raise SystemExit(0)
with open(sys.argv[1], "w") as output:
    output.write("services:\n  proxy:\n    ports: !reset []\n")
    if len(sys.argv) == 3:
        # Caller creates/owns the independently retained recovery-proof volume.
        for service in ("api", "worker"):
            output.write(
                f"  {service}:\n    volumes:\n      - survey-erasure-archive:/recovery/survey-erasure\n"
            )
        output.write(
            f"volumes:\n  survey-erasure-archive:\n    external: true\n    name: {sys.argv[2]}\n"
        )
    output.write("networks:\n")
    for name, subnet in zip(names, selected, strict=True):
        output.write(
            f"  {name}:\n    ipam:\n      config:\n        - subnet: {subnet}\n"
        )
print(
    f"Selected {len(names)} currently unused explicit test subnets; host ports disabled"
)
