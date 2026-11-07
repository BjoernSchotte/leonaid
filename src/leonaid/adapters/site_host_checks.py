"""Host verification for campaign hosts (specs/multi-domain §7.4).

The check proves that a hostname points to this installation's edge:

1. every address the name resolves to is one of the edge's own addresses
   (configured, or the addresses of the admin host) — so a lapsed domain
   that someone else re-registered fails, even if they relay requests;
2. ``http://<address>/.well-known/leonaid-host-check/<token>?nonce=<n>``
   answers with an HMAC of host, token and a fresh nonce under a server
   secret, so a captured answer cannot be replayed (never a private or
   loopback address, no redirects, at most 1 KiB);
3. a TLS handshake with the edge proxy for that name proves the certificate
   (Caddy obtains it on demand, §9.1).
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import secrets
import socket
import ssl
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

from leonaid.domain.site_hosts import HostCheckOutcome, check_answer

HOST_CHECK_PREFIX = "/.well-known/leonaid-host-check/"
MAX_RESPONSE_BYTES = 1024
HTTP_TIMEOUT_SECONDS = 5.0
TLS_TIMEOUT_SECONDS = 20.0
NAT64 = ipaddress.ip_network("64:ff9b::/96")


@dataclass(frozen=True, slots=True)
class HostCheckSettings:
    # Keys the check answer (derived from the installation secret).
    secret: str = ""
    http_port: int = 80
    # The edge's own addresses. Empty: the addresses of ``edge_name``.
    edge_addresses: tuple[str, ...] = ()
    # The name whose addresses are the edge's (the admin host).
    edge_name: str = ""
    # Development and tests only: the dev stack resolves to Docker addresses.
    allow_private_addresses: bool = False
    # The edge proxy that terminates TLS for every site host.
    tls_edge_host: str = "proxy"
    tls_edge_port: int = 443
    # PEM bundle of a test CA (Caddy's internal CA); None = system CAs.
    tls_ca_file: str | None = None


Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


async def system_resolver(hostname: str, port: int) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def forbidden_address(address: str) -> bool:
    """Every address that is not globally routable (the SSRF rule of §7.4).

    IPv6 forms that embed an IPv4 address (mapped, 6to4, Teredo, NAT64)
    count as that IPv4 address.
    """
    ip = ipaddress.ip_address(address)
    if not ip.is_global or ip.is_multicast:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = [ip.ipv4_mapped, ip.sixtofour]
        if ip.teredo is not None:
            embedded.append(ip.teredo[1])
        if ip in NAT64:
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        return (
            any(item is not None and forbidden_address(str(item)) for item in embedded)
            or ip.ipv4_mapped is not None
        )
    return False


class HostChecker:
    def __init__(
        self,
        settings: HostCheckSettings,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._resolve = resolver
        self._transport = transport

    async def check(
        self, hostname: str, token: str, *, tls: bool = True
    ) -> HostCheckOutcome:
        problem = await self._http(hostname, token)
        if problem is not None:
            return HostCheckOutcome(False, None, problem)
        if not tls:
            return HostCheckOutcome(True, None, "Host zeigt auf diesen Server.")
        problem = await self._tls(hostname)
        if problem is not None:
            return HostCheckOutcome(True, False, problem)
        return HostCheckOutcome(True, True, "Host und Zertifikat sind in Ordnung.")

    async def _edge(self) -> set[str] | None:
        if self._settings.edge_addresses:
            return {str(ipaddress.ip_address(a)) for a in self._settings.edge_addresses}
        if not self._settings.edge_name:
            return None
        try:
            found = await asyncio.wait_for(
                self._resolve(self._settings.edge_name, self._settings.http_port),
                HTTP_TIMEOUT_SECONDS,
            )
        except (OSError, asyncio.TimeoutError):
            return None
        return {str(ipaddress.ip_address(a)) for a in found}

    async def _http(self, hostname: str, token: str) -> str | None:
        """None when every address is ours and answers correctly."""
        try:
            addresses = await asyncio.wait_for(
                self._resolve(hostname, self._settings.http_port),
                HTTP_TIMEOUT_SECONDS,
            )
        except (OSError, asyncio.TimeoutError):
            return "Der Name ist im DNS nicht auflösbar."
        addresses = [str(ipaddress.ip_address(a)) for a in addresses]
        if not self._settings.allow_private_addresses and any(
            forbidden_address(address) for address in addresses
        ):
            return "Der Name zeigt (auch) auf eine nicht öffentliche Adresse."
        if not addresses:
            return "Der Name ist im DNS nicht auflösbar."
        edge = await self._edge()
        if edge is None:
            return "Die Adressen dieses Servers sind nicht bekannt."
        foreign = [address for address in addresses if address not in edge]
        if foreign:
            kind = "AAAA" if ":" in foreign[0] else "A"
            return (
                f"{kind}-Eintrag {foreign[0]} zeigt nicht auf diesen Server "
                f"({', '.join(sorted(edge))})."
            )
        reached = 0
        for address in addresses:
            problem = await self._fetch(address, hostname, token)
            if problem is None:
                reached += 1
            elif problem != _UNREACHABLE_V6:
                return problem
        if reached == 0:
            return "Der Server ist unter diesem Namen nicht erreichbar."
        return None

    async def _fetch(self, address: str, hostname: str, token: str) -> str | None:
        ip = ipaddress.ip_address(address)
        literal = f"[{address}]" if ip.version == 6 else address
        nonce = secrets.token_hex(16)
        url = (
            f"http://{literal}:{self._settings.http_port}"
            f"{HOST_CHECK_PREFIX}{token}?nonce={nonce}"
        )
        body = b""
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "GET", url, headers={"Host": hostname, "Accept": "text/plain"}
                ) as response:
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_RESPONSE_BYTES:
                            return f"{address}: Antwort zu groß."
                    if response.status_code != 200:
                        return (
                            f"{address}: Antwort {response.status_code} statt der "
                            "LeonAid-Prüfseite."
                        )
        except httpx.TimeoutException:
            return f"{address}: keine Antwort innerhalb von 5 Sekunden."
        except httpx.HTTPError as error:
            # The address is ours (checked above); this container may just
            # have no IPv6 route. Another address must answer.
            if ip.version == 6 and isinstance(error, httpx.ConnectError):
                return _UNREACHABLE_V6
            return f"{address}: Port {self._settings.http_port} nicht erreichbar."
        expected = check_answer(self._settings.secret, hostname, token, nonce)
        answer = body.decode("utf-8", "replace").strip()
        if not hmac.compare_digest(answer.encode(), expected.encode()):
            return f"{address}: Antwort stammt nicht von dieser Installation."
        return None

    async def _tls(self, hostname: str) -> str | None:
        context = ssl.create_default_context(cafile=self._settings.tls_ca_file)
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._settings.tls_edge_host,
                    self._settings.tls_edge_port,
                    ssl=context,
                    server_hostname=hostname,
                ),
                TLS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return (
                "Das Zertifikat wird noch ausgestellt. Bitte in einer Minute "
                "erneut prüfen."
            )
        except ssl.SSLCertVerificationError as error:
            return f"Zertifikat ungültig: {error.verify_message}."
        except (ssl.SSLError, OSError):
            return "Noch kein Zertifikat. Bitte in einer Minute erneut prüfen."
        writer.close()
        try:
            await writer.wait_closed()
        except (ssl.SSLError, OSError):
            pass
        return None


_UNREACHABLE_V6 = "unreachable-v6"
