"""TLS monitoring covers every host of the installation (specs/multi-domain)."""

from leonaid.entrypoints.monitoring.exporter import (
    combined_certificate_metrics,
    tls_hosts,
)


def test_tls_hosts_cover_public_admin_and_alias_names() -> None:
    assert tls_hosts("portal.leonaid.org  ") == ("portal.leonaid.org",)
    assert tls_hosts(
        "leonaid.org app.leonaid.org www.leonaid.org, web.leonaid.org"
    ) == (
        "leonaid.org",
        "app.leonaid.org",
        "www.leonaid.org",
        "web.leonaid.org",
    )
    assert tls_hosts("leonaid.org leonaid.org") == ("leonaid.org",)


def test_one_invalid_certificate_fails_and_the_earliest_expiry_counts() -> None:
    assert combined_certificate_metrics([(1, 900.0), (1, 300.0)]) == (1, 300.0)
    assert combined_certificate_metrics([(1, 900.0), (0, 0.0)]) == (0, 0.0)
    assert combined_certificate_metrics([]) == (0, 0.0)
