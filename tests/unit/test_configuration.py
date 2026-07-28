from __future__ import annotations

from pydantic import ValidationError
from pytest import raises

from leonaid.configuration import MailTransportSettings, Settings


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
        "objectStorageHost": "rustfs",
        "objectStorageBucket": "leonaid",
    }
    assert "top-secret" not in repr(settings)
    assert "top-secret" not in repr(settings.safe_summary())
    assert settings.allowed_origins == ("http://localhost:8080",)


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
    }
    assert "provider-secret" not in repr(settings)
    assert "provider-secret" not in repr(settings.safe_summary())


def test_production_mail_rejects_plaintext_and_disabled_verification() -> None:
    base = {
        "LEONAID_ENV": "production",
        "MAIL_SMTP_HOST": "smtp.provider.invalid",
        "MAIL_SMTP_PORT": "587",
        "MAIL_FROM": "LeonAid <postmaster@provider.invalid>",
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
