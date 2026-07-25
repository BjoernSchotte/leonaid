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
        "TWENTY_HEALTH_URL": "http://twenty-server:3000/healthz",
        "RUSTFS_HEALTH_URL": "http://rustfs:9000/health",
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
        "coreDatabaseHost": "core-postgres",
        "twentyHealthHost": "twenty-server",
        "rustfsHealthHost": "rustfs",
    }
    assert "top-secret" not in repr(settings)
    assert "top-secret" not in repr(settings.safe_summary())


def test_settings_reject_non_database_target() -> None:
    with raises(ValidationError):
        valid_settings(CORE_DATABASE_URL="https://example.invalid/database")
