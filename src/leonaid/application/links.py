"""Absolute links in mails, per host (specs/multi-domain §7.6).

Member links (login, invitation, e-mail change) point at the admin host;
public links (survey invitations) at the public host. In a single-host
installation both bases are the same host. Stage 2 adds edition URLs of
campaign hosts, read from the site bindings at send time.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


def _base(value: str, label: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError(f"Die {label} ist ungültig.")
    return value.rstrip("/")


def _path(path: str) -> str:
    # Only server-chosen, root-relative paths; never a host from input.
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise ValueError("Ein Mail-Link braucht einen Pfad ab der Wurzel.")
    return path


@dataclass(frozen=True)
class LinkBuilder:
    """Builds absolute URLs from configured bases and root-relative paths."""

    admin_base_url: str
    site_base_url: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "admin_base_url", _base(self.admin_base_url, "Admin-Basis-URL")
        )
        object.__setattr__(
            self, "site_base_url", _base(self.site_base_url, "öffentliche Basis-URL")
        )

    @classmethod
    def single_host(cls, base_url: str) -> LinkBuilder:
        return cls(admin_base_url=base_url, site_base_url=base_url)

    def admin_url(self, path: str) -> str:
        """A page of the admin host: sign-in pages, admin web, PWA."""
        return self.admin_base_url + _path(path)

    def site_url(self, path: str) -> str:
        """A public page: surveys, legal pages, path-based campaigns."""
        return self.site_base_url + _path(path)
