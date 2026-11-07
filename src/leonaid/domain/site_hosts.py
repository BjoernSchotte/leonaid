"""Campaign hosts and their editions (specs/multi-domain §7).

A site host is a hostname outside the configured admin and public hosts. It
serves the editions of one campaign (series) or redirects as a whole to
another site host. An edition binds one action to a path segment of a host;
at most one live edition of a host owns the root ``/``.

Everything here is pure: hostname and segment rules, the canonical URL of an
action (§7.7.3) and the routing decision for ``/`` (§7.7.2). The persistence
adapter enforces the same rules again with constraints and partial unique
indexes.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

import idna

from leonaid.domain.actions import RESERVED_PUBLIC_ALIASES
from leonaid.domain.errors import DomainInvariantError

HOSTNAME = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")
HOSTNAME_MAX_LENGTH = 253
EDITION_SEGMENT = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EDITION_SEGMENT_MAX_LENGTH = 63

# First path segments a campaign host serves itself (§7.3). An edition must
# never shadow them.
RESERVED_EDITION_SEGMENTS = frozenset(
    {
        "archive",
        "campaigns",
        "_campaign-assets",
        "_actions",
        "_astro",
        "_image",
        "_emdash",
        "api",
        "impressum",
        "datenschutz",
        "surveys",
        "robots.txt",
        "sitemap.xml",
        "internal",
    }
    | RESERVED_PUBLIC_ALIASES
)


# Special-use top-level names (RFC 6761, 6762, 7686, 8375, 9476 and common
# private suffixes): they never resolve publicly, so such a host could never
# pass the check. Development and tests may use the first set.
TEST_TLDS = frozenset({"test", "localhost", "invalid"})
SPECIAL_USE_TLDS = TEST_TLDS | frozenset(
    {"local", "internal", "example", "onion", "arpa", "alt", "home", "lan", "corp"}
)


class SiteHostStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    ACTIVE = "active"
    DISABLED = "disabled"


# Hosts Caddy may obtain a certificate for (§9.1).
TLS_APPROVED_STATUSES = frozenset({SiteHostStatus.VERIFIED, SiteHostStatus.ACTIVE})


class EditionAvailability(StrEnum):
    """Public state of a bound action, as in ``PublicActionAvailability``.

    ``published``: running (status active, inside the publication window).
    ``archive``: ended (status completed or archived).
    ``inactive``: not yet public (draft, scheduled, active outside the window).
    """

    PUBLISHED = "published"
    ARCHIVE = "archive"
    INACTIVE = "inactive"


class BindingEndReason(StrEnum):
    SEGMENT_CHANGED = "segment_changed"
    UNBOUND = "unbound"
    HOST_REMOVED = "host_removed"


def _invalid_host(message: str) -> DomainInvariantError:
    return DomainInvariantError("site_host_invalid", message)


def normalize_hostname(raw: str) -> str:
    """Lowercase IDNA A-label without port, trailing dot or path.

    ``Krapfentaxi.ORG`` → ``krapfentaxi.org``; ``straße.de`` →
    ``xn--strae-oqa.de`` (IDNA 2008, ``ß`` kept). IP literals, wildcards,
    ports and single labels are refused.
    """
    if not isinstance(raw, str):
        raise _invalid_host("Der Hostname fehlt.")
    value = raw.strip()
    if not value:
        raise _invalid_host("Der Hostname fehlt.")
    if any(character.isspace() for character in value):
        raise _invalid_host("Der Hostname darf keine Leerzeichen enthalten.")
    if "://" in value or any(character in value for character in "/?#@\\"):
        raise _invalid_host(
            "Bitte nur den Hostnamen eingeben, ohne https:// und ohne Pfad."
        )
    if value.endswith("."):
        raise _invalid_host("Der Hostname darf nicht mit einem Punkt enden.")
    if ":" in value or value.startswith("["):
        raise _invalid_host("Der Hostname darf keinen Port enthalten.")
    if "*" in value:
        raise _invalid_host("Platzhalter-Hostnamen werden nicht unterstützt.")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise _invalid_host("Eine IP-Adresse ist kein Hostname.")
    try:
        ascii_value = idna.encode(value, uts46=True).decode("ascii")
    except (idna.IDNAError, UnicodeError):
        raise _invalid_host("Der Hostname ist kein gültiger Domainname.") from None
    ascii_value = ascii_value.lower()
    if len(ascii_value) > HOSTNAME_MAX_LENGTH or not HOSTNAME.fullmatch(ascii_value):
        raise _invalid_host(
            "Der Hostname braucht mindestens eine Domain und eine Endung, "
            "zum Beispiel krapfentaxi.org."
        )
    return ascii_value


def display_hostname(ascii_value: str) -> str:
    """The Unicode form for the admin UI (``xn--strae-oqa.de`` → ``straße.de``)."""
    try:
        return idna.decode(ascii_value)
    except (idna.IDNAError, UnicodeError):
        return ascii_value


@dataclass(frozen=True, slots=True)
class ConfiguredHosts:
    """Hosts from the environment that a site host must never take (§7.3).

    ``admin``: the admin host (in a single-host installation the only host).
    ``public``: the general public host, ``None`` without one (§6.6).
    ``aliases``: extra names of the public host (``www.``).
    """

    admin: str
    public: str | None = None
    aliases: tuple[str, ...] = ()
    # Development and tests: .test, .localhost and .invalid names.
    allow_test_names: bool = False

    @property
    def has_public_host(self) -> bool:
        return self.public is not None

    def refusal(self, hostname: str) -> DomainInvariantError | None:
        tld = hostname.rsplit(".", 1)[-1]
        if tld in SPECIAL_USE_TLDS and not (self.allow_test_names and tld in TEST_TLDS):
            return DomainInvariantError(
                "site_host_special_use",
                f"Namen unter .{tld} sind im Internet nicht erreichbar.",
            )
        if hostname == self.admin:
            return DomainInvariantError(
                "site_host_reserved", "Das ist der Host der Verwaltung."
            )
        if hostname.endswith("." + self.admin):
            return DomainInvariantError(
                "site_host_reserved",
                "Namen unterhalb des Verwaltungs-Hosts sind nicht erlaubt.",
            )
        if hostname == self.public or hostname in self.aliases:
            return DomainInvariantError(
                "site_host_reserved",
                "Das ist der allgemeine öffentliche Host dieser Installation.",
            )
        return None


def validate_site_hostname(raw: str, configured: ConfiguredHosts) -> str:
    hostname = normalize_hostname(raw)
    refusal = configured.refusal(hostname)
    if refusal is not None:
        raise refusal
    return hostname


def validate_edition_segment(raw: str) -> str:
    value = raw.strip().lower() if isinstance(raw, str) else ""
    if (
        not value
        or len(value) > EDITION_SEGMENT_MAX_LENGTH
        or not EDITION_SEGMENT.fullmatch(value)
    ):
        raise DomainInvariantError(
            "site_edition_segment_invalid",
            "Das Pfadsegment besteht aus Kleinbuchstaben, Ziffern und "
            "Bindestrichen, höchstens 63 Zeichen.",
        )
    if value in RESERVED_EDITION_SEGMENTS:
        raise DomainInvariantError(
            "site_edition_segment_reserved",
            "Dieses Pfadsegment ist für LeonAid reserviert.",
        )
    return value


def default_edition_segment(
    *,
    publication_starts_at: datetime | None,
    starts_on: date,
    archive_slug: str,
    taken: Iterable[str],
) -> str:
    """Year of the publication start, else the archive slug (§7.7.2).

    Without a publication window the action's start date gives the year.
    """
    used = set(taken)
    year = str(
        publication_starts_at.year
        if publication_starts_at is not None
        else starts_on.year
    )
    if year not in used:
        return year
    candidate = archive_slug[:EDITION_SEGMENT_MAX_LENGTH].rstrip("-")
    if candidate in used or candidate in RESERVED_EDITION_SEGMENTS:
        raise DomainInvariantError(
            "site_edition_segment_taken",
            "Bitte ein freies Pfadsegment für diese Ausgabe wählen.",
        )
    return candidate


def edition_availability(
    *,
    status: str,
    published_now: bool,
) -> EditionAvailability:
    if status in {"completed", "archived"}:
        return EditionAvailability.ARCHIVE
    if published_now:
        return EditionAvailability.PUBLISHED
    return EditionAvailability.INACTIVE


@dataclass(frozen=True, slots=True)
class LiveEdition:
    """A live binding as the canonical and routing rules see it."""

    hostname: str
    host_status: SiteHostStatus
    segment: str
    at_root: bool
    is_primary: bool
    availability: EditionAvailability
    # Ordering for fallbacks: the newer edition first.
    bound_at: datetime | None = None


def edition_url(edition: LiveEdition) -> str:
    """The permanent URL of an edition: ``https://<host>/<segment>/``."""
    return f"https://{edition.hostname}/{edition.segment}/"


def edition_canonical_url(edition: LiveEdition) -> str:
    if edition.at_root and edition.availability is EditionAvailability.PUBLISHED:
        return f"https://{edition.hostname}/"
    return edition_url(edition)


def serving_edition(editions: Sequence[LiveEdition]) -> LiveEdition | None:
    """The live binding that gives the action its canonical URL.

    The primary binding on an active host; when the primary host is not
    active, another live binding on an active host (oldest binding first),
    so a page that is still served keeps a canonical on its own host.
    """
    active = [
        edition for edition in editions if edition.host_status is SiteHostStatus.ACTIVE
    ]
    for edition in active:
        if edition.is_primary:
            return edition
    if not active:
        return None
    return sorted(
        active,
        key=lambda item: (
            item.bound_at.timestamp() if item.bound_at else 0.0,
            item.hostname,
        ),
    )[0]


def canonical_url(
    editions: Sequence[LiveEdition],
    *,
    public_fallback_url: str | None,
) -> str | None:
    """The one public URL of an action (§7.7.3).

    1. Live primary binding on an active host, at the root and running →
       ``https://<host>/``.
    2. Otherwise that binding → ``https://<host>/<segment>/``.
    3. No live binding on an active host → the public host path
       (``public_fallback_url``, ``None`` without a public host).
    4. Otherwise no public URL.
    """
    edition = serving_edition(editions)
    if edition is not None:
        return edition_canonical_url(edition)
    return public_fallback_url


def redirect_status(target_url: str) -> Literal[302, 308]:
    """302 to a host root (reused by the next edition), else 308 (§7.7.3)."""
    path = target_url.split("://", 1)[-1].partition("/")[2]
    return 302 if path == "" else 308


@dataclass(frozen=True, slots=True)
class RootDecision:
    """What ``/`` of a campaign host does (§7.7.2)."""

    segment: str
    mode: Literal["serve", "redirect"]


def root_decision(
    editions: Sequence[LiveEdition],
    *,
    ended_order: Sequence[str] = (),
) -> RootDecision | None:
    """``/`` serves the running root edition, else 302s to a fallback.

    Fallback: the running edition of this host (newest binding first), else
    the most recently ended one (``ended_order``: segments, most recently
    ended first). ``None``: no edition is public, ``/`` answers 404.
    """
    for edition in editions:
        if edition.at_root and edition.availability is EditionAvailability.PUBLISHED:
            return RootDecision(edition.segment, "serve")
    running = sorted(
        (
            edition
            for edition in editions
            if edition.availability is EditionAvailability.PUBLISHED
        ),
        key=lambda item: -(item.bound_at.timestamp() if item.bound_at else 0.0),
    )
    if running:
        return RootDecision(running[0].segment, "redirect")
    ended = {
        edition.segment
        for edition in editions
        if edition.availability is EditionAvailability.ARCHIVE
    }
    for segment in ended_order:
        if segment in ended:
            return RootDecision(segment, "redirect")
    if ended:
        return RootDecision(sorted(ended)[-1], "redirect")
    return None


def public_host_path(
    *,
    archive_slug: str,
    primary_alias: str | None,
    campaign_page: bool,
    availability: EditionAvailability,
) -> str:
    """The page of an action on the public host (rule 3 of §7.7.3).

    Running or not yet public: the CMS page, else the primary alias page,
    else the archive page (as ``public_listing_path``). Ended: the permanent
    archive page; ``/campaigns/<slug>/`` only serves running campaigns.
    """
    if availability is EditionAvailability.ARCHIVE:
        return f"/archive/{archive_slug}"
    if campaign_page:
        return f"/campaigns/{archive_slug}/"
    if primary_alias is not None:
        return f"/{primary_alias}"
    return f"/archive/{archive_slug}"
