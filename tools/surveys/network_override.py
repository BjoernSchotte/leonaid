"""Allocate explicit non-overlapping survey test subnets; never prune networks."""

import ipaddress
import json
import secrets
import subprocess
import sys

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
candidates = list(ipaddress.ip_network("172.30.128.0/17").subnets(new_prefix=24))
secrets.SystemRandom().shuffle(candidates)
count = 1 if sys.argv[1] == "--single" else 7
selected = [
    candidate
    for candidate in candidates
    if not any(
        candidate.version == existing.version and candidate.overlaps(existing)
        for existing in used
    )
][:count]
if len(selected) != count:
    raise SystemExit("No free survey test subnets; existing networks are untouched")
if count == 1:
    print(selected[0])
    raise SystemExit(0)
names = [
    "edge",
    "core-data",
    "crm-data",
    "storage-data",
    "mail-data",
    "telemetry",
    "mailing-data",
]
with open(sys.argv[1], "w") as output:
    output.write("services:\n  proxy:\n    ports: !reset []\nnetworks:\n")
    for name, subnet in zip(names, selected, strict=True):
        output.write(
            f"  {name}:\n    ipam:\n      config:\n        - subnet: {subnet}\n"
        )
print("Selected seven currently unused explicit test subnets; host ports disabled")
