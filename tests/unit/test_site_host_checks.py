"""Host check, status transitions and the TLS ask rules (specs/multi-domain §7.4, §9.1)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from leonaid.adapters.site_host_checks import (
    HostChecker,
    HostCheckSettings,
    certificate_problem,
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
SECRET = "synthetic-check-secret"
EDGE_V4 = "93.184.215.14"
EDGE_V6 = "2606:2800:21f:cb07::1"
# Stands for "this installation answers": the right HMAC for the nonce.
OURS = "ours"


def resolver(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolve(hostname: str, port: int) -> Sequence[str]:
        if hostname == "app.example.org":
            return (EDGE_V4, EDGE_V6)
        assert hostname == HOST
        return addresses

    return resolve


def answering(
    replies: dict[str, httpx.Response | Exception | str],
    seen: list[str] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == HOST
        assert request.url.path == f"/.well-known/leonaid-host-check/{TOKEN}"
        nonce = request.url.params["nonce"]
        if seen is not None:
            seen.append(nonce)
        reply = replies[request.url.host]
        if isinstance(reply, Exception):
            raise reply
        if reply == OURS:
            return httpx.Response(200, text=check_answer(SECRET, HOST, TOKEN, nonce))
        assert isinstance(reply, httpx.Response)
        return reply

    return httpx.MockTransport(handler)


def checker(
    addresses: Sequence[str],
    replies: dict[str, httpx.Response | Exception | str],
    *,
    allow_private: bool = False,
    edge: tuple[str, ...] = (),
    seen: list[str] | None = None,
) -> HostChecker:
    return HostChecker(
        HostCheckSettings(
            secret=SECRET,
            allow_private_addresses=allow_private,
            edge_addresses=edge,
            edge_name="app.example.org",
        ),
        resolver=resolver(*addresses),
        transport=answering(replies, seen),
    )


def run(check: HostChecker) -> HostCheckOutcome:
    return asyncio.run(check.check(HOST, TOKEN, tls=False))


def test_every_address_is_ours_and_answers_with_a_fresh_hmac() -> None:
    seen: list[str] = []
    outcome = run(
        checker([EDGE_V4, EDGE_V6], {EDGE_V4: OURS, EDGE_V6: OURS}, seen=seen)
    )
    assert outcome.http_ok, outcome
    assert len(seen) == 2 and len(set(seen)) == 2  # a new nonce per request


def test_a_foreign_address_fails_even_with_the_right_answer() -> None:
    # A lapsed domain someone else registered and relays to us (review I1).
    outcome = run(
        checker(
            [EDGE_V4, "185.199.108.153"],
            {EDGE_V4: OURS, "185.199.108.153": OURS},
        )
    )
    assert not outcome.http_ok
    assert "185.199.108.153 zeigt nicht auf diesen Server" in outcome.message


def test_a_foreign_aaaa_record_fails_without_any_ipv6_route() -> None:
    outcome = run(checker([EDGE_V4, "2606:4700::1111"], {EDGE_V4: OURS}))
    assert not outcome.http_ok
    assert outcome.message.startswith("AAAA-Eintrag 2606:4700::1111")


def test_a_replayed_answer_fails() -> None:
    old = check_answer(SECRET, HOST, TOKEN, "0" * 32)
    outcome = run(checker([EDGE_V4], {EDGE_V4: httpx.Response(200, text=old)}))
    assert not outcome.http_ok
    assert "nicht von dieser Installation" in outcome.message


def test_configured_edge_addresses_win_over_the_admin_host() -> None:
    outcome = run(
        checker(
            ["185.199.108.153"], {"185.199.108.153": OURS}, edge=("185.199.108.153",)
        )
    )
    assert outcome.http_ok, outcome


def test_registrar_redirects_are_not_followed() -> None:
    outcome = run(
        checker(
            [EDGE_V4],
            {EDGE_V4: httpx.Response(301, headers={"Location": "https://x/"})},
        )
    )
    assert not outcome.http_ok
    assert "301" in outcome.message


def test_our_ipv6_without_a_route_from_here_is_skipped() -> None:
    outcome = run(
        checker(
            [EDGE_V4, EDGE_V6],
            {EDGE_V4: OURS, EDGE_V6: httpx.ConnectError("no route")},
        )
    )
    assert outcome.http_ok
    outcome = run(checker([EDGE_V6], {EDGE_V6: httpx.ConnectError("no route")}))
    assert not outcome.http_ok


def test_oversized_answers_fail() -> None:
    outcome = run(checker([EDGE_V4], {EDGE_V4: httpx.Response(200, text="x" * 4096)}))
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
        "100.64.0.1",
        "100.100.100.200",
        "::1",
        "fc00::1",
        "::ffff:93.184.215.14",
        "64:ff9b::a00:1",
        "2002:a00:1::1",
        "0.0.0.0",
        "203.0.113.5",
        "2001:db8::5",
    ],
)
def test_non_global_addresses_are_never_fetched(address: str) -> None:
    assert forbidden_address(address)
    outcome = run(checker([address], {}))
    assert not outcome.http_ok
    assert "nicht öffentliche Adresse" in outcome.message


def test_private_addresses_only_with_the_test_switch() -> None:
    outcome = run(
        checker(
            ["172.18.0.4"],
            {"172.18.0.4": OURS},
            allow_private=True,
            edge=("172.18.0.4",),
        )
    )
    assert outcome.http_ok


def public_view(*addresses: str):  # type: ignore[no-untyped-def]
    async def resolve(hostname: str, nameserver: str) -> Sequence[str]:
        assert hostname == HOST
        return addresses

    return resolve


def with_public(view, addresses: Sequence[str]) -> HostChecker:  # type: ignore[no-untyped-def]
    return HostChecker(
        HostCheckSettings(
            secret=SECRET,
            edge_addresses=(EDGE_V4,),
            public_resolvers=("1.1.1.1",),
        ),
        resolver=resolver(*addresses),
        transport=answering({EDGE_V4: OURS}),
        public_resolver=view,
    )


def test_split_view_dns_fails() -> None:
    # Our resolver sees our address, the world sees another (review R1).
    outcome = run(with_public(public_view("185.199.108.153"), [EDGE_V4]))
    assert not outcome.http_ok
    assert "185.199.108.153" in outcome.message
    assert run(with_public(public_view(EDGE_V4), [EDGE_V4])).http_ok

    async def down(hostname: str, nameserver: str) -> Sequence[str]:
        raise OSError("timeout")

    outcome = run(with_public(down, [EDGE_V4]))
    assert not outcome.http_ok
    assert "1.1.1.1 antwortet nicht" in outcome.message


def test_a_certificate_close_to_expiry_fails() -> None:
    now = 1_800_000_000.0

    def peer(days: float) -> dict[str, object]:
        return {
            "notAfter": time.strftime(
                "%b %d %H:%M:%S %Y GMT", time.gmtime(now + days * 86400)
            )
        }

    assert certificate_problem(peer(60), now) is None
    assert certificate_problem(peer(21), now) is None
    problem = certificate_problem(peer(19), now)
    assert problem is not None and "19 Tagen" in problem
    assert certificate_problem(None, now) is not None


def test_unresolvable_names_fail() -> None:
    async def failing(hostname: str, port: int) -> Sequence[str]:
        raise OSError("NXDOMAIN")

    check = HostChecker(HostCheckSettings(secret=SECRET), resolver=failing)
    outcome = asyncio.run(check.check(HOST, TOKEN, tls=False))
    assert not outcome.http_ok
    assert "nicht auflösbar" in outcome.message


def test_answer_is_keyed_and_bound_to_host_token_and_nonce() -> None:
    answer = check_answer(SECRET, HOST, TOKEN, "a" * 32)
    assert answer != check_answer("other-secret", HOST, TOKEN, "a" * 32)
    assert answer != check_answer(SECRET, "other.org", TOKEN, "a" * 32)
    assert answer != check_answer(SECRET, HOST, "u" * 43, "a" * 32)
    assert answer != check_answer(SECRET, HOST, TOKEN, "b" * 32)
    assert TOKEN not in answer


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
