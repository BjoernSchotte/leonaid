"""Hostname, segment, canonical URL and root rules (specs/multi-domain §7)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from leonaid.application.site_hosts import (
    AddSiteHost,
    BindEdition,
    SetRedirectHost,
    command_fingerprint,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.site_hosts import (
    ConfiguredHosts,
    EditionAvailability,
    LiveEdition,
    SiteHostStatus,
    canonical_url,
    default_edition_segment,
    display_hostname,
    edition_availability,
    normalize_hostname,
    public_host_path,
    redirect_status,
    root_decision,
    validate_edition_segment,
    validate_site_hostname,
)

CONFIGURED = ConfiguredHosts(
    admin="app.example.org", public="example.org", aliases=("www.example.org",)
)
NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("krapfentaxi.org", "krapfentaxi.org"),
        ("  Krapfentaxi.ORG ", "krapfentaxi.org"),
        ("weihnachtsmarkt.example.org", "weihnachtsmarkt.example.org"),
        # IDNA 2008 / UTS 46: ß stays (not "strasse"), umlauts are encoded.
        ("straße.de", "xn--strae-oqa.de"),
        ("Bücherflohmarkt.de", "xn--bcherflohmarkt-gsb.de"),
        ("xn--bcherflohmarkt-gsb.de", "xn--bcherflohmarkt-gsb.de"),
    ],
)
def test_hostnames_are_normalized(raw: str, expected: str) -> None:
    assert normalize_hostname(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "krapfentaxi.org.",
        "krapfentaxi.org:443",
        "https://krapfentaxi.org",
        "krapfentaxi.org/2025",
        "user@krapfentaxi.org",
        "192.0.2.10",
        "[2001:db8::1]",
        "2001:db8::1",
        "localhost",
        "*.example.org",
        "krapfen taxi.org",
        "-bad.example.org",
        "bad-.example.org",
        "under_score.example.org",
        "example.1",
        "a" * 64 + ".org",
        ".".join(["a" * 60] * 5) + ".org",
    ],
)
def test_invalid_hostnames_are_refused(raw: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        normalize_hostname(raw)
    assert error.value.code == "site_host_invalid"


@pytest.mark.parametrize(
    "raw",
    ["app.example.org", "x.app.example.org", "example.org", "WWW.example.org"],
)
def test_configured_hosts_are_refused(raw: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        validate_site_hostname(raw, CONFIGURED)
    assert error.value.code == "site_host_reserved"


def test_sibling_subdomain_of_the_club_domain_is_allowed() -> None:
    # A campaign subdomain is a sibling of the admin host, not below it.
    assert (
        validate_site_hostname("weihnachtsmarkt.example.org", CONFIGURED)
        == "weihnachtsmarkt.example.org"
    )
    assert validate_site_hostname("appx.example.org", CONFIGURED) == "appx.example.org"


def test_without_public_host_only_the_admin_host_is_reserved() -> None:
    configured = ConfiguredHosts(admin="app.example.org")
    assert not configured.has_public_host
    assert validate_site_hostname("example.org", configured) == "example.org"


def test_display_hostname_shows_unicode() -> None:
    assert display_hostname("xn--strae-oqa.de") == "straße.de"
    assert display_hostname("krapfentaxi.org") == "krapfentaxi.org"


@pytest.mark.parametrize("raw", ["2025", "lions-open-2025", " Edition-2 "])
def test_segments(raw: str) -> None:
    assert validate_edition_segment(raw) == raw.strip().lower()


@pytest.mark.parametrize("raw", ["", "-2025", "2025-", "a--b", "a_b", "a/b", "x" * 64])
def test_invalid_segments(raw: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        validate_edition_segment(raw)
    assert error.value.code == "site_edition_segment_invalid"


@pytest.mark.parametrize(
    "raw",
    [
        "archive",
        "campaigns",
        "api",
        "impressum",
        "datenschutz",
        "surveys",
        "admin",
        "app",
        "login",
    ],
)
def test_reserved_segments(raw: str) -> None:
    with pytest.raises(DomainInvariantError) as error:
        validate_edition_segment(raw)
    assert error.value.code == "site_edition_segment_reserved"


def test_default_segment_is_the_publication_year_else_the_slug() -> None:
    starts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    assert (
        default_edition_segment(
            publication_starts_at=starts,
            starts_on=date(2024, 1, 1),
            archive_slug="lions-open-2025",
            taken=(),
        )
        == "2025"
    )
    assert (
        default_edition_segment(
            publication_starts_at=None,
            starts_on=date(2024, 1, 1),
            archive_slug="lions-open-2024",
            taken=(),
        )
        == "2024"
    )
    assert (
        default_edition_segment(
            publication_starts_at=starts,
            starts_on=date(2025, 1, 1),
            archive_slug="lions-open-2025-b",
            taken=("2025",),
        )
        == "lions-open-2025-b"
    )
    with pytest.raises(DomainInvariantError):
        default_edition_segment(
            publication_starts_at=starts,
            starts_on=date(2025, 1, 1),
            archive_slug="x",
            taken=("2025", "x"),
        )


def test_availability() -> None:
    assert edition_availability(status="completed", published_now=False) is (
        EditionAvailability.ARCHIVE
    )
    assert edition_availability(status="archived", published_now=False) is (
        EditionAvailability.ARCHIVE
    )
    assert edition_availability(status="active", published_now=True) is (
        EditionAvailability.PUBLISHED
    )
    for status in ("draft", "scheduled", "active"):
        assert edition_availability(status=status, published_now=False) is (
            EditionAvailability.INACTIVE
        )


def edition(
    *,
    host: str = "lionsopen.de",
    status: SiteHostStatus = SiteHostStatus.ACTIVE,
    segment: str = "2025",
    at_root: bool = False,
    primary: bool = True,
    availability: EditionAvailability = EditionAvailability.PUBLISHED,
    bound_days_ago: int = 1,
) -> LiveEdition:
    return LiveEdition(
        hostname=host,
        host_status=status,
        segment=segment,
        at_root=at_root,
        is_primary=primary,
        availability=availability,
        bound_at=NOW - timedelta(days=bound_days_ago),
    )


FALLBACK = "https://example.org/campaigns/lions-open-2025/"


def test_canonical_rule_1_running_root_is_the_host_root() -> None:
    assert (
        canonical_url([edition(at_root=True)], public_fallback_url=FALLBACK)
        == "https://lionsopen.de/"
    )


@pytest.mark.parametrize(
    ("at_root", "availability"),
    [
        (True, EditionAvailability.ARCHIVE),
        (True, EditionAvailability.INACTIVE),
        (False, EditionAvailability.PUBLISHED),
        (False, EditionAvailability.ARCHIVE),
    ],
)
def test_canonical_rule_2_segment_url(
    at_root: bool, availability: EditionAvailability
) -> None:
    assert (
        canonical_url(
            [edition(at_root=at_root, availability=availability)],
            public_fallback_url=FALLBACK,
        )
        == "https://lionsopen.de/2025/"
    )


@pytest.mark.parametrize(
    "status",
    [SiteHostStatus.PENDING, SiteHostStatus.VERIFIED, SiteHostStatus.DISABLED],
)
def test_canonical_rule_3_public_host_path_without_an_active_host(
    status: SiteHostStatus,
) -> None:
    assert (
        canonical_url(
            [edition(status=status, at_root=True)], public_fallback_url=FALLBACK
        )
        == FALLBACK
    )
    assert canonical_url([], public_fallback_url=FALLBACK) == FALLBACK


def test_canonical_rule_4_no_public_url() -> None:
    assert canonical_url([], public_fallback_url=None) is None


def test_canonical_prefers_the_primary_and_falls_back_to_an_active_mirror() -> None:
    primary = edition(host="krapfentaxi.org", at_root=True)
    mirror = edition(host="krapfentaxi.example.org", at_root=True, primary=False)
    assert canonical_url([mirror, primary], public_fallback_url=None) == (
        "https://krapfentaxi.org/"
    )
    lapsed = edition(
        host="krapfentaxi.org", at_root=True, status=SiteHostStatus.DISABLED
    )
    assert canonical_url([lapsed, mirror], public_fallback_url=FALLBACK) == (
        "https://krapfentaxi.example.org/"
    )


def test_redirect_code_rule() -> None:
    assert redirect_status("https://lionsopen.de/") == 302
    assert redirect_status("https://lionsopen.de") == 302
    assert redirect_status("https://lionsopen.de/2025/") == 308
    assert redirect_status("https://example.org/campaigns/x/") == 308


def test_root_serves_the_running_root_edition() -> None:
    decision = root_decision(
        [edition(segment="2026", at_root=True), edition(segment="2025")]
    )
    assert decision is not None
    assert (decision.segment, decision.mode) == ("2026", "serve")


def test_root_falls_back_to_a_running_edition_then_the_latest_ended() -> None:
    upcoming_root = edition(
        segment="2027", at_root=True, availability=EditionAvailability.INACTIVE
    )
    running = edition(segment="2026", bound_days_ago=5)
    ended = edition(segment="2025", availability=EditionAvailability.ARCHIVE)
    decision = root_decision([upcoming_root, running, ended])
    assert decision is not None
    assert (decision.segment, decision.mode) == ("2026", "redirect")

    older = edition(segment="2024", availability=EditionAvailability.ARCHIVE)
    decision = root_decision(
        [upcoming_root, ended, older], ended_order=("2025", "2024")
    )
    assert decision is not None
    assert (decision.segment, decision.mode) == ("2025", "redirect")

    ended_root = edition(
        segment="2026", at_root=True, availability=EditionAvailability.ARCHIVE
    )
    decision = root_decision([ended_root], ended_order=("2026",))
    assert decision is not None
    assert (decision.segment, decision.mode) == ("2026", "redirect")


def test_root_without_a_public_edition_is_none() -> None:
    assert root_decision([edition(availability=EditionAvailability.INACTIVE)]) is None
    assert root_decision([]) is None


def test_public_host_path() -> None:
    running = EditionAvailability.PUBLISHED
    assert (
        public_host_path(
            archive_slug="x",
            primary_alias="x-alias",
            campaign_page=True,
            availability=running,
        )
        == "/campaigns/x/"
    )
    assert (
        public_host_path(
            archive_slug="x",
            primary_alias="x-alias",
            campaign_page=False,
            availability=running,
        )
        == "/x-alias"
    )
    assert (
        public_host_path(
            archive_slug="x",
            primary_alias=None,
            campaign_page=False,
            availability=running,
        )
        == "/archive/x"
    )
    assert (
        public_host_path(
            archive_slug="x",
            primary_alias="x-alias",
            campaign_page=True,
            availability=EditionAvailability.ARCHIVE,
        )
        == "/archive/x"
    )


def test_commands_validate_and_fingerprint() -> None:
    host = uuid4()
    with pytest.raises(DomainInvariantError):
        SetRedirectHost(uuid4(), host, 1, host)
    with pytest.raises(DomainInvariantError):
        BindEdition(uuid4(), host, 0, uuid4(), None, False)
    bind = BindEdition(uuid4(), host, 1, uuid4(), " 2025 ", True)
    assert bind.segment == "2025"
    actor = uuid4()
    add = AddSiteHost(uuid4(), "krapfentaxi.org")
    assert command_fingerprint(add, actor) == command_fingerprint(add, actor)
    assert command_fingerprint(add, actor) != command_fingerprint(add, uuid4())
    assert command_fingerprint(add, actor) != command_fingerprint(
        AddSiteHost(add.command_id, "other.org"), actor
    )
