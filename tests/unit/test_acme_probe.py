"""The real-ACME acceptance probe refuses private addresses (specs/multi-domain §14)."""

from __future__ import annotations

from tools.site_hosts import acme_probe


def test_public_addresses_only() -> None:
    assert acme_probe.public("93.184.215.14")
    assert acme_probe.public("2606:2800:21f:cb07::1")
    for address in ("10.0.0.1", "127.0.0.1", "192.168.0.1", "::1", "fe80::1"):
        assert not acme_probe.public(address)


def test_unresolvable_host_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_: object, **__: object) -> list[object]:
        raise OSError("NXDOMAIN")

    monkeypatch.setattr(acme_probe.socket, "getaddrinfo", fail)
    assert acme_probe.main(["krapfentaxi.invalid"]) == 1
