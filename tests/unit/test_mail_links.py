"""LinkBuilder: absolute mail links per host (specs/multi-domain §7.6)."""

from __future__ import annotations

import pytest

from leonaid.application.links import LinkBuilder


def test_member_links_use_the_admin_host_public_links_the_site_host() -> None:
    links = LinkBuilder(
        admin_base_url="https://app.leonaid.org/",
        site_base_url="https://leonaid.org",
    )

    assert links.admin_url("/login?token=a") == "https://app.leonaid.org/login?token=a"
    assert (
        links.admin_url("/invite?token=b") == "https://app.leonaid.org/invite?token=b"
    )
    assert links.site_url("/surveys/7#invitation=c") == (
        "https://leonaid.org/surveys/7#invitation=c"
    )


def test_single_host_uses_one_base_for_both() -> None:
    links = LinkBuilder.single_host("https://portal.leonaid.org")

    assert links.admin_url("/email-change?token=x") == (
        "https://portal.leonaid.org/email-change?token=x"
    )
    assert links.site_url("/surveys/1") == "https://portal.leonaid.org/surveys/1"


@pytest.mark.parametrize(
    "path",
    ["login", "//evil.invalid/login", "/\\\\evil.invalid", "https://evil.invalid/"],
)
def test_links_accept_only_root_relative_paths(path: str) -> None:
    links = LinkBuilder.single_host("https://portal.leonaid.org")

    with pytest.raises(ValueError):
        links.admin_url(path)
    with pytest.raises(ValueError):
        links.site_url(path)


@pytest.mark.parametrize(
    "base",
    [
        "portal.leonaid.org",
        "ftp://portal.leonaid.org",
        "https://user:secret@portal.leonaid.org",
        "https://portal.leonaid.org/?next=x",
        "https://portal.leonaid.org/#x",
    ],
)
def test_bases_must_be_plain_http_origins(base: str) -> None:
    with pytest.raises(ValueError):
        LinkBuilder.single_host(base)
