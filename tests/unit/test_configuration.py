from __future__ import annotations

from pydantic import ValidationError
from pytest import raises

from leonaid.configuration import (
    DEVELOPMENT_CLUB_NAME,
    PRODUCTION_CLUB_NAME_MISSING,
    ConfigurationError,
    MailTransportSettings,
    Settings,
    load_link_settings,
    load_map_settings,
    load_push_settings,
    load_settings,
)


def valid_settings(**overrides: str) -> Settings:
    values = {
        "LEONAID_ENV": "test",
        "LEONAID_SERVICE_NAME": "leonaid-api",
        "LEONAID_SERVICE_VERSION": "0.0.0",
        "LEONAID_API_VERSION": "v1",
        "CORE_DATABASE_URL": "postgresql://golden-user:top-secret@core-postgres/leonaid",
        "LEONAID_SECRET_KEY": "invitation-hmac-secret-with-at-least-32-characters",
        "LEONAID_SESSION_ENCRYPTION_KEY": (
            "mail-payload-secret-with-at-least-32-characters"
        ),
        "LEONAID_PUBLIC_BASE_URL": "http://localhost:8080",
        "TWENTY_BASE_URL": "http://twenty-server:3000",
        "TWENTY_HEALTH_URL": "http://twenty-server:3000/healthz",
        "RUSTFS_HEALTH_URL": "http://rustfs:9000/health",
        "OBJECT_STORAGE_ENDPOINT_URL": "http://rustfs:9000",
        "OBJECT_STORAGE_ACCESS_KEY": "golden-storage-access",
        "OBJECT_STORAGE_SECRET_KEY": "golden-storage-secret",
        "OBJECT_STORAGE_BUCKET": "leonaid",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def valid_production_settings(**overrides: str) -> Settings:
    values = {
        "LEONAID_ENV": "production",
        "LEONAID_RELEASE_COMMIT": "0123456789abcdef0123456789abcdef01234567",
        "LEONAID_TRUST_PROXY_HEADERS": "true",
        "LEONAID_PUBLIC_BASE_URL": "https://portal.leonaid.org",
        "LEONAID_ALLOWED_ORIGINS": "https://portal.leonaid.org",
        "MAIL_HEALTH_URL": "https://status.mail-provider.org/health",
        "OBJECT_STORAGE_BUCKET": "leonaid-production-club-111",
        "LEONAID_CLUB_NAME": "Lions Club Beispielstadt",
    }
    values.update(overrides)
    return valid_settings(**values)


def test_settings_are_typed_and_secret_safe() -> None:
    settings = valid_settings()

    assert settings.environment == "test"
    assert settings.safe_summary() == {
        "environment": "test",
        "serviceName": "leonaid-api",
        "serviceVersion": "0.0.0",
        "releaseCommit": "unconfigured",
        "apiVersion": "v1",
        "publicBaseHost": "localhost",
        "allowedOriginCount": "1",
        "siteBaseHost": "localhost",
        "publicOriginCount": "0",
        "trustedProxyHeaders": "false",
        "invitationTtlMinutes": "30",
        "loginChallengeTtlMinutes": "10",
        "freshLoginSeconds": "900",
        "maintenanceFlagPath": "/run/leonaid-maintenance/enabled",
        "coreDatabaseHost": "core-postgres",
        "twentyBaseHost": "twenty-server",
        "twentyIntegration": "unconfigured",
        "twentyHealthHost": "twenty-server",
        "rustfsHealthHost": "rustfs",
        "mailHealthHost": "mailpit",
        "workerHealthHost": "worker",
        "pilotMonitoring": "unconfigured",
        "objectStorageHost": "rustfs",
        "objectStorageBucket": "leonaid",
    }
    assert "top-secret" not in repr(settings)
    assert "top-secret" not in repr(settings.safe_summary())
    assert settings.allowed_origins == ("http://localhost:8080",)


def test_single_host_links_use_the_one_base_url() -> None:
    settings = valid_settings(LEONAID_SITE_BASE_URL="")

    assert settings.site_base_url == settings.public_base_url
    assert settings.public_origins == ()
    assert settings.links.admin_url("/login?token=t") == (
        "http://localhost:8080/login?token=t"
    )
    assert settings.links.site_url("/surveys/1") == "http://localhost:8080/surveys/1"


def test_admin_and_public_host_split_links_and_origins() -> None:
    settings = valid_production_settings(
        LEONAID_PUBLIC_BASE_URL="https://app.leonaid.org",
        LEONAID_ALLOWED_ORIGINS="https://app.leonaid.org",
        LEONAID_SITE_BASE_URL="https://leonaid.org",
        LEONAID_PUBLIC_ORIGINS="https://leonaid.org, https://WWW.leonaid.org/",
    )

    assert settings.links.admin_url("/invite?token=t") == (
        "https://app.leonaid.org/invite?token=t"
    )
    assert settings.links.site_url("/surveys/7") == "https://leonaid.org/surveys/7"
    assert settings.allowed_origins == ("https://app.leonaid.org",)
    assert settings.public_origins == (
        "https://leonaid.org",
        "https://www.leonaid.org",
    )
    assert settings.safe_summary()["siteBaseHost"] == "leonaid.org"
    assert settings.safe_summary()["publicOriginCount"] == "2"


def test_production_rejects_unsafe_public_hosts() -> None:
    split = {
        "LEONAID_PUBLIC_BASE_URL": "https://app.leonaid.org",
        "LEONAID_ALLOWED_ORIGINS": "https://app.leonaid.org",
    }
    for overrides in (
        {"LEONAID_SITE_BASE_URL": "http://leonaid.org"},
        {"LEONAID_SITE_BASE_URL": "https://leonaid.test"},
        {"LEONAID_PUBLIC_ORIGINS": "http://leonaid.org"},
        {"LEONAID_PUBLIC_ORIGINS": "https://localhost"},
        # A public origin with credentials would open the admin API to it.
        {"LEONAID_PUBLIC_ORIGINS": "https://app.leonaid.org"},
    ):
        with raises(ValidationError):
            valid_production_settings(**split, **overrides)


def test_allowed_origins_are_normalized_and_deduplicated() -> None:
    settings = valid_settings(
        LEONAID_ALLOWED_ORIGINS=(
            "http://localhost:8080/, https://portal.leonaid.invalid"
        )
    )

    assert settings.allowed_origins == (
        "http://localhost:8080",
        "https://portal.leonaid.invalid",
    )


def test_pilot_monitoring_sources_must_be_configured_together() -> None:
    with raises(ValidationError):
        valid_settings(
            PILOT_MONITOR_STATUS_URL="http://pilot-monitor-exporter:9108/status"
        )
    with raises(ValidationError):
        valid_settings(PILOT_ALERTMANAGER_URL="http://alertmanager:9093")

    settings = valid_settings(
        PILOT_MONITOR_STATUS_URL="http://pilot-monitor-exporter:9108/status",
        PILOT_ALERTMANAGER_URL="http://alertmanager:9093",
    )

    assert settings.pilot_monitor_status_url is not None
    assert settings.pilot_alertmanager_url is not None
    assert settings.safe_summary()["pilotMonitoring"] == "configured"


def test_settings_reject_non_database_target() -> None:
    with raises(ValidationError):
        valid_settings(CORE_DATABASE_URL="https://example.invalid/database")


def test_production_settings_require_public_edges_and_separate_secrets() -> None:
    settings = valid_production_settings()
    assert settings.environment == "production"

    unsafe_values = (
        {"LEONAID_PUBLIC_BASE_URL": "http://portal.leonaid.org"},
        {"LEONAID_RELEASE_COMMIT": "main"},
        {"LEONAID_PUBLIC_BASE_URL": "https://127.0.0.1"},
        {"LEONAID_PUBLIC_BASE_URL": "https://portal.leonaid.invalid"},
        {"LEONAID_PUBLIC_BASE_URL": "https://portal.example.org"},
        {"LEONAID_TRUST_PROXY_HEADERS": "false"},
        {"LEONAID_ALLOWED_ORIGINS": "http://portal.leonaid.org"},
        {"MAIL_HEALTH_URL": "http://mailpit:8025/mail/api/v1/info"},
        {"OBJECT_STORAGE_BUCKET": "leonaid"},
        {
            "LEONAID_SESSION_ENCRYPTION_KEY": (
                "invitation-hmac-secret-with-at-least-32-characters"
            )
        },
    )
    for unsafe in unsafe_values:
        with raises(ValidationError):
            valid_production_settings(**unsafe)


def test_runtime_secrets_require_minimum_length() -> None:
    with raises(ValidationError):
        valid_settings(LEONAID_SECRET_KEY="too-short")
    with raises(ValidationError):
        valid_settings(LEONAID_SESSION_ENCRYPTION_KEY="too-short")


def test_mail_transport_settings_are_generic_and_secret_safe() -> None:
    settings = MailTransportSettings.model_validate(
        {
            "LEONAID_ENV": "production",
            "MAIL_SMTP_HOST": "smtp.provider.org",
            "MAIL_SMTP_PORT": "465",
            "MAIL_FROM": "LeonAid <postmaster@provider.org>",
            "MAIL_ENVELOPE_FROM": "bounces@provider.org",
            "MAIL_REPLY_TO": "support@provider.org",
            "MAIL_SMTP_MODE": "tls",
            "MAIL_SMTP_USERNAME": "smtp-user",
            "MAIL_SMTP_PASSWORD": "provider-secret",
            "MAIL_SMTP_TIMEOUT_SECONDS": "15",
            "MAIL_SMTP_VERIFY_CERTIFICATES": "true",
        }
    )

    assert settings.safe_summary() == {
        "host": "smtp.provider.org",
        "port": "465",
        "mode": "tls",
        "authentication": "configured",
        "certificateVerification": "true",
        "customCertificateAuthority": "unconfigured",
        "envelopeFrom": "configured",
        "replyTo": "configured",
    }
    assert "provider-secret" not in repr(settings)
    assert "provider-secret" not in repr(settings.safe_summary())


def test_production_mail_rejects_plaintext_and_disabled_verification() -> None:
    base = {
        "LEONAID_ENV": "production",
        "MAIL_SMTP_HOST": "smtp.provider.invalid",
        "MAIL_SMTP_PORT": "587",
        "MAIL_FROM": "LeonAid <postmaster@provider.invalid>",
        "MAIL_ENVELOPE_FROM": "bounces@provider.invalid",
        "MAIL_REPLY_TO": "support@provider.invalid",
    }
    with raises(ValidationError):
        MailTransportSettings.model_validate(
            {
                **base,
                "MAIL_SMTP_MODE": "plain",
                "MAIL_SMTP_VERIFY_CERTIFICATES": "true",
            }
        )
    with raises(ValidationError):
        MailTransportSettings.model_validate(
            {
                **base,
                "MAIL_SMTP_HOST": "smtp.example.org",
                "MAIL_FROM": "LeonAid <noreply@example.org>",
                "MAIL_SMTP_MODE": "starttls",
                "MAIL_SMTP_VERIFY_CERTIFICATES": "true",
            }
        )
    with raises(ValidationError):
        MailTransportSettings.model_validate(
            {
                **base,
                "MAIL_SMTP_MODE": "starttls",
                "MAIL_SMTP_VERIFY_CERTIFICATES": "false",
            }
        )
    with raises(ValidationError):
        MailTransportSettings.model_validate(
            {
                **base,
                "MAIL_SMTP_HOST": "mailpit",
                "MAIL_FROM": "LeonAid <noreply@leonaid.invalid>",
                "MAIL_SMTP_MODE": "starttls",
                "MAIL_SMTP_VERIFY_CERTIFICATES": "true",
            }
        )


def test_staging_mailpit_relay_needs_its_flag_and_private_ca() -> None:
    staging = {
        "LEONAID_ENV": "production",
        "MAIL_SMTP_HOST": "mailpit",
        "MAIL_SMTP_PORT": "465",
        "MAIL_SMTP_MODE": "tls",
        "MAIL_SMTP_VERIFY_CERTIFICATES": "true",
        "MAIL_FROM": "LeonAid Staging <noreply@leonaid.org>",
        "MAIL_ENVELOPE_FROM": "bounces@leonaid.org",
        "MAIL_REPLY_TO": "support@leonaid.org",
        "MAIL_SMTP_CA_FILE": "/run/leonaid-staging-mail/ca.pem",
        "LEONAID_STAGING_MAILPIT": "true",
    }
    settings = MailTransportSettings.model_validate(staging)
    assert settings.host == "mailpit"
    assert settings.staging_mailpit
    for missing in ("LEONAID_STAGING_MAILPIT", "MAIL_SMTP_CA_FILE"):
        with raises(ValidationError):
            MailTransportSettings.model_validate(
                {key: value for key, value in staging.items() if key != missing}
            )
    with raises(ValidationError):
        MailTransportSettings.model_validate({**staging, "MAIL_SMTP_HOST": "localhost"})


def test_production_mail_requires_explicit_delivery_identities() -> None:
    base = {
        "LEONAID_ENV": "production",
        "MAIL_SMTP_HOST": "smtp.provider.org",
        "MAIL_SMTP_PORT": "587",
        "MAIL_FROM": "LeonAid <postmaster@provider.org>",
        "MAIL_SMTP_MODE": "starttls",
        "MAIL_SMTP_VERIFY_CERTIFICATES": "true",
    }
    with raises(ValidationError, match="Envelope-From"):
        MailTransportSettings.model_validate(
            {
                **base,
                "MAIL_REPLY_TO": "support@provider.org",
            }
        )
    with raises(ValidationError, match="Reply-To"):
        MailTransportSettings.model_validate(
            {
                **base,
                "MAIL_ENVELOPE_FROM": "bounces@provider.org",
            }
        )


def test_mail_credentials_must_be_complete() -> None:
    with raises(ValidationError):
        MailTransportSettings.model_validate(
            {
                "LEONAID_ENV": "test",
                "MAIL_SMTP_HOST": "mailpit",
                "MAIL_SMTP_PORT": "1025",
                "MAIL_FROM": "LeonAid <noreply@leonaid.invalid>",
                "MAIL_SMTP_MODE": "plain",
                "MAIL_SMTP_USERNAME": "only-a-user",
            }
        )


def test_club_name_defaults_outside_production_and_is_normalised() -> None:
    assert valid_settings().club_name == DEVELOPMENT_CLUB_NAME
    assert valid_settings(LEONAID_CLUB_NAME="   ").club_name == DEVELOPMENT_CLUB_NAME
    assert (
        valid_settings(LEONAID_CLUB_NAME="  Lions Club   Am See ").club_name
        == "Lions Club Am See"
    )


def test_club_name_rejects_control_characters_and_overlong_values() -> None:
    for value in ("Lions\u0000Club", "Lions Club\u200b", "L" * 121):
        with raises(ValidationError):
            valid_settings(LEONAID_CLUB_NAME=value)
    assert valid_settings(LEONAID_CLUB_NAME="L" * 120).club_name == "L" * 120


def test_production_requires_a_club_name() -> None:
    assert valid_production_settings().club_name == "Lions Club Beispielstadt"
    for missing in ("", "  "):
        with raises(ValidationError, match="LEONAID_CLUB_NAME"):
            valid_production_settings(LEONAID_CLUB_NAME=missing)


def test_startup_names_the_missing_club_name(monkeypatch) -> None:
    production = {
        "LEONAID_ENV": "production",
        "LEONAID_RELEASE_COMMIT": "0123456789abcdef0123456789abcdef01234567",
        "LEONAID_TRUST_PROXY_HEADERS": "true",
        "LEONAID_PUBLIC_BASE_URL": "https://portal.leonaid.org",
        "LEONAID_ALLOWED_ORIGINS": "https://portal.leonaid.org",
        "MAIL_HEALTH_URL": "https://status.mail-provider.org/health",
        "OBJECT_STORAGE_BUCKET": "leonaid-production-club-111",
        "CORE_DATABASE_URL": "postgresql://golden-user:top-secret@core-postgres/leonaid",
        "LEONAID_SECRET_KEY": "invitation-hmac-secret-with-at-least-32-characters",
        "LEONAID_SESSION_ENCRYPTION_KEY": "mail-payload-secret-with-at-least-32-characters",
        "TWENTY_BASE_URL": "http://twenty-server:3000",
        "TWENTY_HEALTH_URL": "http://twenty-server:3000/healthz",
        "RUSTFS_HEALTH_URL": "http://rustfs:9000/health",
        "OBJECT_STORAGE_ENDPOINT_URL": "http://rustfs:9000",
        "OBJECT_STORAGE_ACCESS_KEY": "golden-storage-access",
        "OBJECT_STORAGE_SECRET_KEY": "golden-storage-secret",
    }
    monkeypatch.delenv("LEONAID_CLUB_NAME", raising=False)
    for key, value in production.items():
        monkeypatch.setenv(key, value)
    with raises(
        ConfigurationError,
        match=PRODUCTION_CLUB_NAME_MISSING.replace("(", r"\(").replace(")", r"\)"),
    ):
        load_settings()
    monkeypatch.setenv("LEONAID_CLUB_NAME", "Lions Club Beispielstadt")
    assert load_settings().club_name == "Lions Club Beispielstadt"


def test_site_host_check_settings_are_validated_at_startup() -> None:
    """specs/multi-domain §7.4, review N2 and R1."""
    with raises(ValidationError, match="no IP address"):
        valid_settings(LEONAID_SITE_HOST_EDGE_ADDRESSES="203.0.113.10, nonsense")
    with raises(ValidationError, match="no IP address"):
        valid_settings(LEONAID_SITE_HOST_PUBLIC_RESOLVERS="dns.example")
    with raises(ValidationError, match="edge addresses must be public"):
        valid_production_settings(LEONAID_SITE_HOST_EDGE_ADDRESSES="10.0.0.5")
    settings = valid_settings(LEONAID_SITE_HOST_EDGE_ADDRESSES="93.184.215.14 ::1")
    assert settings.host_check_settings.edge_addresses == ("93.184.215.14", "::1")
    # Split-view DNS guard: on in production unless switched off.
    assert valid_settings().host_check_settings.public_resolvers == ()
    assert valid_production_settings().host_check_settings.public_resolvers == (
        "1.1.1.1",
        "9.9.9.9",
    )
    assert (
        valid_production_settings(
            LEONAID_SITE_HOST_PUBLIC_RESOLVERS="none"
        ).host_check_settings.public_resolvers
        == ()
    )


MAP_VARIABLES = (
    "LEONAID_MAP_TILE_URL",
    "LEONAID_MAP_TILE_ORIGIN",
    "LEONAID_MAP_ATTRIBUTION",
    "LEONAID_GEOCODER_URL",
    "LEONAID_GEOCODER_USER_AGENT",
    "LEONAID_GEOCODING_INTERVAL_SECONDS",
)


def test_map_settings_defaults_and_origin_mismatch(monkeypatch) -> None:
    """specs/krapfentaxi-touren §5 and §8: OSM tiles, public Nominatim."""
    for name in MAP_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LEONAID_PUBLIC_BASE_URL", "https://portal.leonaid.org/")
    settings = load_map_settings()
    assert settings.tile_url == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    assert settings.tile_origin == "https://tile.openstreetmap.org"
    assert settings.attribution == "© OpenStreetMap-Mitwirkende"
    assert settings.geocoder_url == "https://nominatim.openstreetmap.org/search"
    assert settings.geocoder_user_agent == "LeonAid (https://portal.leonaid.org)"
    assert settings.geocoding_interval_seconds == 60
    # Compose passes unset variables as empty strings.
    monkeypatch.setenv("LEONAID_MAP_TILE_URL", "")
    monkeypatch.setenv("LEONAID_GEOCODING_INTERVAL_SECONDS", " ")
    assert load_map_settings() == settings
    monkeypatch.delenv("LEONAID_PUBLIC_BASE_URL")
    with raises(ConfigurationError, match="LEONAID_GEOCODER_USER_AGENT:missing"):
        load_map_settings()
    monkeypatch.setenv("LEONAID_PUBLIC_BASE_URL", "https://portal.leonaid.org/")

    # A provider with its own host must name that host for the CSP.
    monkeypatch.setenv(
        "LEONAID_MAP_TILE_URL", "https://tiles.example.org/{z}/{x}/{y}.png"
    )
    with raises(ConfigurationError, match="LEONAID_MAP_TILE_ORIGIN:mismatch"):
        load_map_settings()
    monkeypatch.setenv("LEONAID_MAP_TILE_ORIGIN", "https://tiles.example.org")
    assert load_map_settings().tile_origin == "https://tiles.example.org"
    # A self-hosted path on the own host needs no origin.
    monkeypatch.setenv("LEONAID_MAP_TILE_URL", "/tiles/{z}/{x}/{y}.png")
    assert load_map_settings().tile_url == "/tiles/{z}/{x}/{y}.png"

    monkeypatch.setenv(
        "LEONAID_GEOCODER_USER_AGENT", "Lions Club Test (it@club.example)"
    )
    assert (
        load_map_settings().geocoder_user_agent == "Lions Club Test (it@club.example)"
    )

    for name, value in (
        ("LEONAID_MAP_TILE_URL", "http://tiles.example.org/{z}/{x}/{y}.png"),
        ("LEONAID_MAP_TILE_URL", "https://tiles.example.org/{z}/{y}.png"),
        ("LEONAID_MAP_TILE_ORIGIN", "https://tiles.example.org/path"),
        ("LEONAID_MAP_ATTRIBUTION", "<b>OSM</b>"),
        ("LEONAID_MAP_ATTRIBUTION", "x" * 201),
        ("LEONAID_GEOCODER_URL", "ftp://geo.example.org/search"),
        ("LEONAID_GEOCODER_USER_AGENT", "LeonAid\r\nX-Injected: 1"),
        ("LEONAID_GEOCODING_INTERVAL_SECONDS", "0"),
    ):
        with monkeypatch.context() as scoped:
            scoped.setenv(name, value)
            with raises(ConfigurationError, match=name) as error:
                load_map_settings()
            # Diagnostics name the variable, never its value.
            assert value not in str(error.value)


def test_link_settings_give_the_worker_the_hosts_of_the_api(monkeypatch) -> None:
    monkeypatch.setenv("LEONAID_PUBLIC_BASE_URL", "https://app.leonaid.org/")
    monkeypatch.delenv("LEONAID_SITE_BASE_URL", raising=False)
    # One host: the legal pages are on the admin host.
    links = load_link_settings().links
    assert links.site_url("/impressum") == "https://app.leonaid.org/impressum"
    # Compose passes an unset variable as an empty string.
    monkeypatch.setenv("LEONAID_SITE_BASE_URL", " ")
    assert load_link_settings().links == links
    # With a public host the delivery-day mail links that host, as the mails
    # the API queues do.
    monkeypatch.setenv("LEONAID_SITE_BASE_URL", "https://leonaid.org")
    split = load_link_settings().links
    assert split.site_url("/datenschutz") == "https://leonaid.org/datenschutz"
    assert split.admin_url("/login") == "https://app.leonaid.org/login"
    assert (
        split
        == valid_settings(
            LEONAID_PUBLIC_BASE_URL="https://app.leonaid.org/",
            LEONAID_SITE_BASE_URL="https://leonaid.org",
        ).links
    )

    monkeypatch.setenv("LEONAID_SITE_BASE_URL", "not a url")
    with raises(ConfigurationError, match="LEONAID_SITE_BASE_URL"):
        load_link_settings()
    monkeypatch.delenv("LEONAID_SITE_BASE_URL")
    monkeypatch.delenv("LEONAID_PUBLIC_BASE_URL")
    with raises(ConfigurationError, match="LEONAID_PUBLIC_BASE_URL:missing"):
        load_link_settings()


def test_push_is_unconfigured_without_the_vapid_key(monkeypatch) -> None:
    """specs/mails-documents-donations-push §10: no key, "not configured"."""
    monkeypatch.setenv("LEONAID_ENV", "production")
    # Compose passes unset variables as empty strings.
    monkeypatch.setenv("LEONAID_VAPID_PRIVATE_KEY", " ")
    monkeypatch.setenv("LEONAID_VAPID_SUBJECT", "")
    settings = load_push_settings()
    assert settings.configured is False
    assert settings.signer() is None
    assert settings.safe_summary() == {"webPush": "unconfigured"}
    monkeypatch.delenv("LEONAID_VAPID_PRIVATE_KEY")
    monkeypatch.setenv("LEONAID_VAPID_SUBJECT", "mailto:betrieb@lions-musterstadt.de")
    assert load_push_settings().configured is False


def test_push_settings_name_a_wrong_key_or_subject_without_its_value(
    monkeypatch,
) -> None:
    key = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
    monkeypatch.setenv("LEONAID_ENV", "local")
    monkeypatch.setenv("LEONAID_VAPID_PRIVATE_KEY", key)
    monkeypatch.setenv("LEONAID_VAPID_SUBJECT", "mailto:push@leonaid.invalid")
    settings = load_push_settings()
    assert settings.configured is True
    signer = settings.signer()
    assert signer is not None
    # The public key of RFC 8291's example sender belongs to this scalar.
    assert signer.public_key == (
        "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIg"
        "Dll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
    )
    assert key not in repr(settings)
    assert settings.safe_summary() == {"webPush": "configured"}

    monkeypatch.setenv("LEONAID_VAPID_SUBJECT", "")
    with raises(ConfigurationError, match="LEONAID_VAPID_SUBJECT:missing") as error:
        load_push_settings()
    assert key not in str(error.value)
    monkeypatch.setenv("LEONAID_VAPID_SUBJECT", "push@leonaid.invalid")
    with raises(ConfigurationError, match="LEONAID_VAPID_SUBJECT:invalid"):
        load_push_settings()
    monkeypatch.setenv("LEONAID_VAPID_SUBJECT", "mailto:push@leonaid.invalid")
    monkeypatch.setenv("LEONAID_VAPID_PRIVATE_KEY", "c2hvcnQ")
    with raises(ConfigurationError, match="LEONAID_VAPID_PRIVATE_KEY:invalid") as error:
        load_push_settings()
    assert "c2hvcnQ" not in str(error.value)

    # Production: the push services must be able to reach the operator.
    monkeypatch.setenv("LEONAID_VAPID_PRIVATE_KEY", key)
    monkeypatch.setenv("LEONAID_ENV", "production")
    for subject in ("mailto:push@leonaid.invalid", "https://example.org/contact"):
        monkeypatch.setenv("LEONAID_VAPID_SUBJECT", subject)
        with raises(ConfigurationError, match="LEONAID_VAPID_SUBJECT:not_public"):
            load_push_settings()
    monkeypatch.setenv("LEONAID_VAPID_SUBJECT", "mailto:betrieb@lions-musterstadt.de")
    assert load_push_settings().configured is True
