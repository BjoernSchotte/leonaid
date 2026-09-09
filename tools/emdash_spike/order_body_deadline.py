"""Real TLS requests prove order ingress limits before Core/CRM mutation."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
from time import monotonic

import asyncpg
import httpx

from tools.emdash_spike.valid_order_ingress_proof import snapshot


def decoded_body(wire: bytes, *, chunked: bool) -> bytes:
    if not chunked:
        return wire
    result = bytearray()
    while True:
        length, separator, wire = wire.partition(b"\r\n")
        assert separator, "Incomplete chunk header"
        size = int(length.partition(b";")[0], 16)
        if size == 0:
            assert wire == b"\r\n", "Incomplete or unexpected response trailers"
            return bytes(result)
        assert len(wire) >= size + 2 and wire[size : size + 2] == b"\r\n"
        result.extend(wire[:size])
        wire = wire[size + 2 :]


async def call(path: str, case: str, *, direct: bool = False) -> None:
    print(
        f"order-body-deadline: starting {case}; route={path.split('?')[0]}", flush=True
    )
    chunked = case in {"slow-chunked", "overflow"}
    multipart = case == "slow-multipart"
    payload = b"x=1"
    if case in {"overflow", "declared-overflow"}:
        payload = b"x" * 65537
    if case == "exact-limit":
        payload = b"website=" + b"x" * (65536 - len(b"website="))
    content_type = (
        "multipart/form-data; boundary=synthetic-order-boundary"
        if multipart
        else "application/x-www-form-urlencoded"
    )
    headers = [
        f"POST {path} HTTP/1.1",
        "Host: proxy:8443",
        f"Origin: {'http' if direct else 'https'}://proxy:8443",
        f"Content-Type: {content_type}",
    ]
    if chunked:
        headers.append("Transfer-Encoding: chunked")
        wire_body = f"{len(payload):x}\r\n".encode() + payload + b"\r\n"
        # Deliberately omit the terminal chunk, including for oversized input.
    else:
        length = 65537 if case == "declared-overflow" else len(payload)
        if case.startswith("slow-"):
            length += 100
        headers.append(f"Content-Length: {length}")
        wire_body = b"" if case == "declared-overflow" else payload
    if case == "exact-limit":
        headers.append("Connection: close")
    tls = None if direct else ssl.create_default_context(cafile="/proof/root.crt")
    reader, writer = await asyncio.open_connection(
        "public" if direct else "proxy",
        3000 if direct else 8443,
        ssl=tls,
        server_hostname=None if direct else "proxy",
    )
    try:
        started = monotonic()
        writer.write("\r\n".join(headers).encode() + b"\r\n\r\n" + wire_body)
        await writer.drain()
        async with asyncio.timeout(8):
            response_headers = await reader.readuntil(b"\r\n\r\n")
            status = int(response_headers.split(b" ", 2)[1])
            print(
                f"order-body-deadline: {case}; response headers status={status}",
                flush=True,
            )
            response_fields = {}
            for line in response_headers.decode("latin1").split("\r\n")[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    response_fields[name.lower()] = value.strip()
            print(
                f"order-body-deadline: {case}; close={response_fields.get('connection') == 'close'}; "
                f"chunked={response_fields.get('transfer-encoding') == 'chunked'}; "
                f"length={response_fields.get('content-length', 'absent')}",
                flush=True,
            )
            size = 0
            wire_response = bytearray()
            while chunk := await reader.read(65536):
                size += len(chunk)
                assert size < 1024 * 1024
                wire_response.extend(chunk)
                print(f"order-body-deadline: {case}; received bytes={size}", flush=True)
        elapsed = monotonic() - started
        body = decoded_body(
            bytes(wire_response),
            chunked=response_fields.get("transfer-encoding") == "chunked",
        )
        if "content-length" in response_fields:
            assert len(body) == int(response_fields["content-length"])
        lowered = response_headers.lower()
        assert b"cache-control: no-store\r\n" in lowered
        assert b"set-cookie:" not in lowered
        if case.startswith("slow-"):
            assert status == 408 and 3.8 <= elapsed < 7
        elif case == "exact-limit":
            # It reaches Astro validation, not the body guard. Ordinary valid
            # form acceptance is proven by the subsequent 24-order matrix.
            if path.startswith("/_actions/"):
                # Astro ActionInputError uses BAD_REQUEST (400), not Core's
                # UNPROCESSABLE_CONTENT (422). Prove actual schema validation.
                assert status == 400
                result = json.loads(body)
                assert result["type"] == "AstroActionInputError"
                assert any(
                    issue["path"] == ["website"] and issue["code"] == "too_big"
                    for issue in result["issues"]
                )
            else:
                assert status == 200
        else:
            assert status == 413 and elapsed < 4
        print(
            f"order-body-deadline: {case}; route={path.split('?')[0]}; "
            f"status={status}; complete response and connection EOF in {round(elapsed * 1000)}ms",
            flush=True,
        )
    finally:
        writer.close()
        try:
            async with asyncio.timeout(1):
                await writer.wait_closed()
        except TimeoutError:
            # A failed EOF assertion must not leave the diagnostic itself
            # waiting for the peer's TLS shutdown indefinitely.
            writer.transport.abort()


async def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    core = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=5)
    try:
        async with httpx.AsyncClient(
            base_url="http://twenty-server:3000",
            timeout=15,
            headers={
                "Authorization": f"Bearer {os.environ['TWENTY_INTEGRATION_API_KEY']}"
            },
        ) as twenty:
            before = await snapshot(core, twenty)
            for path in (
                "/campaigns/krapfentaxi-2026/?_action=createPublicOrder",
                "/krapfentaxi?_action=createPublicOrder",
                "/_actions/createPublicOrder",
            ):
                for case in (
                    "slow-length",
                    "slow-chunked",
                    "slow-multipart",
                    "declared-overflow",
                    "overflow",
                    "exact-limit",
                ):
                    await call(path, case)
            assert await snapshot(core, twenty) == before, (
                "Rejected or invalid order bodies mutated Core or Twenty"
            )
            print(
                "order-body-deadline: 18 real TLS cases across both native renderers and RPC; seven Core tables and Twenty unchanged",
                flush=True,
            )
    finally:
        await core.close()


async def transport_only() -> None:
    print(
        "order-body-deadline: direct Astro control before the TLS proxy cases",
        flush=True,
    )
    await call("/_actions/createPublicOrder", "declared-overflow", direct=True)
    for case in (
        "declared-overflow",
        "overflow",
        "slow-length",
        "slow-chunked",
        "slow-multipart",
        "exact-limit",
    ):
        await call("/_actions/createPublicOrder", case)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--transport-only"]:
            asyncio.run(transport_only())
        elif not sys.argv[1:]:
            asyncio.run(main())
        else:
            raise SystemExit(2)
    except Exception as error:
        print(f"order-body-deadline: failed; type={type(error).__name__}", flush=True)
        raise SystemExit(1) from None
