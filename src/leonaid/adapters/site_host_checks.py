"""Host verification for campaign hosts (specs/multi-domain §7.4).

The check proves that a hostname reaches this installation: Core fetches
``http://<host>/.well-known/leonaid-host-check/<token>`` from every public
address the name resolves to (never a private or loopback address) and
expects this installation's answer. A TLS handshake with the edge proxy then
proves the certificate (Caddy obtains it on demand, §9.1).
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
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


@dataclass(frozen=True, slots=True)
class HostCheckSettings:
    http_port: int = 80
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
    """Private, loopback and special ranges (the SSRF rule of §7.4)."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


_UNREACHABLE_V6 = "unreachable-v6"


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

    async def _http(self, hostname: str, token: str) -> str | None:
        """None when every reachable public address answers correctly."""
        try:
            addresses = await asyncio.wait_for(
                self._resolve(hostname, self._settings.http_port),
                HTTP_TIMEOUT_SECONDS,
            )
        except (OSError, asyncio.TimeoutError):
            return "Der Name ist im DNS nicht auflösbar."
        allowed = [
            address
            for address in addresses
            if self._settings.allow_private_addresses or not forbidden_address(address)
        ]
        if not allowed:
            return "Der Name zeigt auf keine öffentliche Adresse."
        expected = check_answer(hostname, token)
        passed = 0
        for address in allowed:
            problem = await self._fetch(address, hostname, token, expected)
            if problem is None:
                passed += 1
            elif problem != _UNREACHABLE_V6:
                return problem
        if passed == 0:
            return "Der Server ist unter diesem Namen nicht erreichbar."
        return None

    async def _fetch(
        self, address: str, hostname: str, token: str, expected: str
    ) -> str | None:
        ip = ipaddress.ip_address(address)
        literal = f"[{address}]" if ip.version == 6 else address
        url = f"http://{literal}:{self._settings.http_port}{HOST_CHECK_PREFIX}{token}"
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
                            "LeonAid-Prüfseite. Zeigt der DNS-Eintrag auf diesen "
                            "Server?"
                        )
        except httpx.TimeoutException:
            return f"{address}: keine Antwort innerhalb von 5 Sekunden."
        except httpx.HTTPError as error:
            # Containers often have no IPv6 egress; only a wrong answer over
            # IPv6 fails the check, an unreachable route does not.
            if ip.version == 6 and isinstance(error, httpx.ConnectError):
                return _UNREACHABLE_V6
            return f"{address}: Port {self._settings.http_port} nicht erreichbar."
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
