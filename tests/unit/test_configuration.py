from __future__ import annotations

from pydantic import ValidationError
from pytest import raises

from leonaid.configuration import (
    DEVELOPMENT_CLUB_NAME,
    PRODUCTION_CLUB_NAME_MISSING,
    ConfigurationError,
    MailTransportSettings,
    Settings,
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
