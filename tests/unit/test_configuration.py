from __future__ import annotations

from pydantic import ValidationError
from pytest import raises

from leonaid.configuration import Settings


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


def test_settings_are_typed_and_secret_safe() -> None:
    settings = valid_settings()

    assert settings.environment == "test"
    assert settings.safe_summary() == {
        "environment": "test",
        "serviceName": "leonaid-api",
        "serviceVersion": "0.0.0",
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
