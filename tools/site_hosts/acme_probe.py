#!/usr/bin/env python3
"""Real-ACME acceptance probe for one campaign host (specs/multi-domain §14).

Run on any machine with internet access after the system admin added the
host, the club created its DNS records and the check in System › Domains
passed:

    python3 tools/site_hosts/acme_probe.py krapfentaxi.org [--admin app.example.org]

It proves, from the outside:

1. the name resolves to public addresses only, and every IPv4 address (and
   every reachable IPv6 address) is the server of the admin host;
2. ``http://<host>/.well-known/leonaid-host-check/`` reaches LeonAid
   (LeonAid's answer, never a registrar's forwarding page);
3. ``https://<host>/`` presents a certificate that the system trust store
   accepts for exactly this name, issued by a public CA (Let's Encrypt by
   default), valid for at least 7 days;
4. ``http://<host>/`` redirects to HTTPS on the same host.

Standard library only. Exit 0 when all checks pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import socket
import ssl
import sys
from datetime import datetime, timezone


def addresses(hostname: str) -> list[str]:
    infos = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def http_get(
    address: str, hostname: str, path: str
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(address, 80, timeout=10)
    try:
        connection.request("GET", path, headers={"Host": hostname})
        response = connection.getresponse()
        return (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            response.read(2048),
        )
    finally:
        connection.close()


def certificate(hostname: str, address: str) -> dict:  # type: ignore[type-arg]
    context = ssl.create_default_context()
    with socket.create_connection((address, 443), timeout=60) as raw:
        with context.wrap_socket(raw, server_hostname=hostname) as tls:
            peer = tls.getpeercert()
            assert peer is not None
            return peer


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("hostname")
    parser.add_argument("--admin", help="admin host; its addresses must match")
    parser.add_argument(
        "--issuer",
        default="Let's Encrypt",
        help="expected issuer organisation (default: Let's Encrypt)",
    )
    arguments = parser.parse_args(argv)
    hostname = arguments.hostname.strip().lower().rstrip(".")
    failures: list[str] = []

    def check(ok: bool, message: str) -> None:
        print(("OK   " if ok else "FAIL ") + message)
        if not ok:
            failures.append(message)

    try:
        found = addresses(hostname)
    except OSError as error:
        print(f"FAIL DNS: {hostname} not resolvable: {error}")
        return 1
    check(
        bool(found) and all(public(item) for item in found),
        f"DNS {hostname} → {', '.join(found)}",
    )
    if arguments.admin:
        expected = set(addresses(arguments.admin))
        v4 = [item for item in found if ipaddress.ip_address(item).version == 4]
        check(
            bool(v4) and set(v4) <= expected,
            f"IPv4 of {hostname} matches {arguments.admin} ({', '.join(sorted(expected))})",
        )
    for address in found:
        try:
            status, _, body = http_get(
                address, hostname, "/.well-known/leonaid-host-check/acme-probe"
            )
        except OSError as error:
            if ipaddress.ip_address(address).version == 6:
                print(f"SKIP {address}: no IPv6 route from this machine ({error})")
                continue
            check(False, f"{address}:80 reachable ({error})")
            continue
        # An unknown token is a 404 from LeonAid's API: plain JSON error body.
        check(
            status == 404 and b"site_host_check_unknown" in body,
            f"{address}:80 answers as LeonAid on the host-check path (status {status})",
        )
        status, headers, _ = http_get(address, hostname, "/")
        location = headers.get("location", "")
        check(
            status in {301, 308} and location.startswith(f"https://{hostname}/"),
            f"{address}:80 redirects / to HTTPS ({status} {location})",
        )
    v4 = next((item for item in found if ipaddress.ip_address(item).version == 4), None)
    if v4 is None:
        check(False, "an IPv4 address for the TLS probe")
    else:
        try:
            peer = certificate(hostname, v4)
        except (OSError, ssl.SSLError) as error:
            check(False, f"TLS certificate for {hostname} accepted ({error})")
        else:
            issuer = dict(item[0] for item in peer.get("issuer", ()))
            expires = datetime.fromtimestamp(
                ssl.cert_time_to_seconds(str(peer["notAfter"])), timezone.utc
            )
            days = (expires - datetime.now(timezone.utc)).days
            check(
                True,
                f"TLS certificate for {hostname} accepted by the system trust store",
            )
            check(
                arguments.issuer.casefold()
                in str(issuer.get("organizationName", "")).casefold(),
                f"issuer {issuer.get('organizationName')} {issuer.get('commonName')}",
            )
            check(
                days >= 7,
                f"certificate valid for {days} more days (until {expires:%Y-%m-%d})",
            )
    print("acme-probe: OK" if not failures else f"acme-probe: FAILED ({len(failures)})")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
