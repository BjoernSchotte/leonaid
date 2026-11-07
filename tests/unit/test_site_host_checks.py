"""Host check, status transitions and the TLS ask rules (specs/multi-domain §7.4, §9.1)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from leonaid.adapters.site_host_checks import (
    HostChecker,
    HostCheckSettings,
    forbidden_address,
)
from leonaid.domain.site_hosts import (
    HostCheckOutcome,
    SiteHostStatus,
    check_answer,
    check_transition,
)

NOW = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)
HOST = "krapfentaxi.org"
TOKEN = "t" * 43


def resolver(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolve(hostname: str, port: int) -> Sequence[str]:
        assert hostname == HOST
        return addresses

    return resolve


def answering(
    replies: dict[str, httpx.Response | Exception],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == HOST
        assert request.url.path == f"/.well-known/leonaid-host-check/{TOKEN}"
        reply = replies[request.url.host]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return httpx.MockTransport(handler)


def checker(
    addresses: Sequence[str],
    replies: dict[str, httpx.Response | Exception],
    *,
    allow_private: bool = False,
) -> HostChecker:
    return HostChecker(
        HostCheckSettings(allow_private_addresses=allow_private),
        resolver=resolver(*addresses),
        transport=answering(replies),
    )


GOOD = httpx.Response(200, text=check_answer(HOST, TOKEN))


def run(check: HostChecker) -> HostCheckOutcome:
    return asyncio.run(check.check(HOST, TOKEN, tls=False))


def test_every_public_address_must_answer_with_our_digest() -> None:
    outcome = run(
        checker(
            ["93.184.215.14", "2606:2800:21f:cb07::1"],
            {"93.184.215.14": GOOD, "2606:2800:21f:cb07::1": GOOD},
        )
    )
    assert outcome.http_ok, outcome


def test_an_address_of_another_server_fails() -> None:
    outcome = run(
        checker(
            ["93.184.215.14", "185.199.108.153"],
            {
                "93.184.215.14": GOOD,
                "185.199.108.153": httpx.Response(200, text="parked"),
            },
        )
    )
    assert not outcome.http_ok
    assert "185.199.108.153" in outcome.message


def test_registrar_redirects_are_not_followed() -> None:
    outcome = run(
        checker(
            ["93.184.215.14"],
            {"93.184.215.14": httpx.Response(301, headers={"Location": "https://x/"})},
        )
    )
    assert not outcome.http_ok
    assert "301" in outcome.message


def test_unreachable_ipv6_is_skipped_but_a_wrong_ipv6_answer_fails() -> None:
    outcome = run(
        checker(
            ["93.184.215.14", "2606:2800:21f:cb07::1"],
            {
                "93.184.215.14": GOOD,
                "2606:2800:21f:cb07::1": httpx.ConnectError("no route"),
            },
        )
    )
    assert outcome.http_ok
    outcome = run(
        checker(
            ["2606:2800:21f:cb07::1"],
            {"2606:2800:21f:cb07::1": httpx.ConnectError("no route")},
        )
    )
    assert not outcome.http_ok


def test_oversized_answers_fail() -> None:
    outcome = run(
        checker(
            ["93.184.215.14"], {"93.184.215.14": httpx.Response(200, text="x" * 4096)}
        )
    )
    assert not outcome.http_ok
    assert "zu groß" in outcome.message


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "172.18.0.4",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.1.1",
        "::1",
        "fc00::1",
        "::ffff:93.184.215.14",
        "203.0.113.5",
        "2001:db8::5",
        "0.0.0.0",
    ],
)
def test_private_addresses_are_never_fetched(address: str) -> None:
    assert forbidden_address(address)
    outcome = run(checker([address], {}))
    assert not outcome.http_ok
    assert "keine öffentliche Adresse" in outcome.message


def test_private_addresses_only_with_the_test_switch() -> None:
    outcome = run(checker(["172.18.0.4"], {"172.18.0.4": GOOD}, allow_private=True))
    assert outcome.http_ok


def test_unresolvable_names_fail() -> None:
    async def failing(hostname: str, port: int) -> Sequence[str]:
        raise OSError("NXDOMAIN")

    check = HostChecker(HostCheckSettings(), resolver=failing)
    outcome = asyncio.run(check.check(HOST, TOKEN, tls=False))
    assert not outcome.http_ok
    assert "nicht auflösbar" in outcome.message


def test_answer_differs_per_host_and_token() -> None:
    assert check_answer(HOST, TOKEN) != check_answer("other.org", TOKEN)
    assert check_answer(HOST, TOKEN) != check_answer(HOST, "u" * 43)
    assert TOKEN not in check_answer(HOST, TOKEN)


PASS = HostCheckOutcome(True, True, "ok")
NO_CERT = HostCheckOutcome(True, False, "noch kein Zertifikat")
FAIL = HostCheckOutcome(False, None, "kaputt")


def transition(
    status: SiteHostStatus,
    outcome: HostCheckOutcome,
    *,
    failures: int = 0,
    since: datetime | None = None,
    live: bool = True,
):  # type: ignore[no-untyped-def]
    return check_transition(
        status=status,
        has_live_bindings=live,
        consecutive_failures=failures,
        failing_since=since,
        outcome=outcome,
        now=NOW,
    )


def test_pending_becomes_verified_then_active() -> None:
    step = transition(SiteHostStatus.PENDING, NO_CERT)
    assert step.status is SiteHostStatus.VERIFIED and step.verified_now
    step = transition(SiteHostStatus.VERIFIED, PASS)
    assert step.status is SiteHostStatus.ACTIVE and not step.verified_now
    step = transition(SiteHostStatus.PENDING, PASS)
    assert step.status is SiteHostStatus.ACTIVE and step.verified_now


def test_a_failing_pending_host_stays_pending_without_counting() -> None:
    step = transition(SiteHostStatus.PENDING, FAIL, failures=0)
    assert step.status is SiteHostStatus.PENDING
    assert step.consecutive_failures == 0


def test_three_failures_over_72_hours_disable_an_active_host() -> None:
    step = transition(SiteHostStatus.ACTIVE, FAIL)
    assert (step.status, step.consecutive_failures, step.failing_since) == (
        SiteHostStatus.ACTIVE,
        1,
        NOW,
    )
    # Three failures within a few hours: still active (a short outage).
    step = transition(
        SiteHostStatus.ACTIVE, FAIL, failures=2, since=NOW - timedelta(hours=3)
    )
    assert step.status is SiteHostStatus.ACTIVE and step.consecutive_failures == 3
    # The third failure after 72 h: disabled.
    step = transition(
        SiteHostStatus.ACTIVE, FAIL, failures=2, since=NOW - timedelta(hours=72)
    )
    assert step.status is SiteHostStatus.DISABLED
    # Many failures but not yet 72 h: still active.
    step = transition(
        SiteHostStatus.VERIFIED, FAIL, failures=10, since=NOW - timedelta(hours=71)
    )
    assert step.status is SiteHostStatus.VERIFIED


def test_a_certificate_failure_of_an_active_host_counts() -> None:
    step = transition(SiteHostStatus.ACTIVE, NO_CERT)
    assert step.status is SiteHostStatus.ACTIVE and step.consecutive_failures == 1


def test_a_passing_check_resets_the_counter() -> None:
    step = transition(
        SiteHostStatus.ACTIVE, PASS, failures=2, since=NOW - timedelta(hours=30)
    )
    assert (step.status, step.consecutive_failures, step.failing_since) == (
        SiteHostStatus.ACTIVE,
        0,
        None,
    )


def test_a_lapsed_host_with_live_bindings_comes_back() -> None:
    step = transition(
        SiteHostStatus.DISABLED, NO_CERT, failures=3, since=NOW - timedelta(days=5)
    )
    assert step.status is SiteHostStatus.VERIFIED and step.consecutive_failures == 0
    step = transition(SiteHostStatus.DISABLED, PASS)
    assert step.status is SiteHostStatus.ACTIVE


def test_a_removed_host_is_never_checked_back() -> None:
    step = transition(SiteHostStatus.DISABLED, PASS, live=False)
    assert step.status is SiteHostStatus.DISABLED
