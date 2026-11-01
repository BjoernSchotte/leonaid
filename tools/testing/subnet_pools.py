"""Candidate /24 subnets for isolated test stacks.

Docker hands out whole /16 networks from 172.17.0.0/12 by default. On a host
with many Compose projects one of them can cover the preferred test pool
completely, so a second pool outside Docker's defaults serves as fallback.
LEONAID_TEST_SUBNET_POOLS (comma-separated CIDRs) overrides both.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
import socket
import struct
from pathlib import Path

DEFAULT_POOLS = ("172.30.128.0/17", "10.213.0.0/16")
POOL_VARIABLE = "LEONAID_TEST_SUBNET_POOLS"


def configured_pools() -> list[ipaddress.IPv4Network]:
    raw = os.environ.get(POOL_VARIABLE, "").strip()
    values = [item.strip() for item in raw.split(",") if item.strip()] or list(
        DEFAULT_POOLS
    )
    pools = []
    for value in values:
        network = ipaddress.ip_network(value)
        if not isinstance(network, ipaddress.IPv4Network) or network.prefixlen > 24:
            raise ValueError(f"{POOL_VARIABLE} needs IPv4 pools of /24 or larger")
        pools.append(network)
    return pools


def host_routes(
    route_table: Path = Path("/proc/net/route"),
) -> list[ipaddress.IPv4Network]:
    """Return the Linux host's IPv4 routes (LAN, VPN), except the default route."""

    try:
        lines = route_table.read_text().splitlines()[1:]
    except OSError:
        return []
    routes = []
    for line in lines:
        fields = line.split()
        if len(fields) < 8:
            continue
        destination = socket.inet_ntoa(struct.pack("<L", int(fields[1], 16)))
        mask = socket.inet_ntoa(struct.pack("<L", int(fields[7], 16)))
        network = ipaddress.ip_network(f"{destination}/{mask}", strict=False)
        if network.prefixlen > 0:
            routes.append(network)
    return routes


def candidate_subnets(
    used: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None,
) -> list[ipaddress.IPv4Network]:
    """Free /24 subnets, preferred pool first, shuffled within each pool."""

    blocked = [*(used or []), *host_routes()]
    result: list[ipaddress.IPv4Network] = []
    for pool in configured_pools():
        subnets = [
            subnet
            for subnet in pool.subnets(new_prefix=24)
            if not any(
                subnet.version == existing.version and subnet.overlaps(existing)
                for existing in blocked
            )
        ]
        secrets.SystemRandom().shuffle(subnets)
        result.extend(subnets)
    return result
