"""Typed startup configuration with secret-safe diagnostics."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Configuration failed without exposing its values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["local", "test", "production"] = Field(alias="LEONAID_ENV")
    service_name: str = Field(default="leonaid-api", alias="LEONAID_SERVICE_NAME")
    service_version: str = Field(default="0.0.0", alias="LEONAID_SERVICE_VERSION")
    api_version: str = Field(default="v1", alias="LEONAID_API_VERSION")
    core_database_url: SecretStr = Field(alias="CORE_DATABASE_URL")
    invitation_hmac_secret: SecretStr = Field(alias="LEONAID_SECRET_KEY")
    mail_payload_secret: SecretStr = Field(alias="LEONAID_SESSION_ENCRYPTION_KEY")
    public_base_url: HttpUrl = Field(alias="LEONAID_PUBLIC_BASE_URL")
    allowed_origins_value: str = Field(
        default="",
        alias="LEONAID_ALLOWED_ORIGINS",
    )
    trust_proxy_headers: bool = Field(
        default=False,
        alias="LEONAID_TRUST_PROXY_HEADERS",
    )
    invitation_ttl_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        alias="LEONAID_INVITATION_TTL_MINUTES",
    )
    login_challenge_ttl_minutes: int = Field(
        default=10,
        ge=5,
        le=30,
        alias="LEONAID_LOGIN_CHALLENGE_TTL_MINUTES",
    )
    fresh_login_seconds: int = Field(
        default=900,
        ge=1,
        le=7200,
        alias="LEONAID_FRESH_LOGIN_SECONDS",
    )
    twenty_base_url: HttpUrl = Field(alias="TWENTY_BASE_URL")
    twenty_integration_api_key: SecretStr | None = Field(
        default=None,
        alias="TWENTY_INTEGRATION_API_KEY",
    )
    twenty_health_url: HttpUrl = Field(alias="TWENTY_HEALTH_URL")
    rustfs_health_url: HttpUrl = Field(alias="RUSTFS_HEALTH_URL")
    object_storage_endpoint_url: HttpUrl = Field(alias="OBJECT_STORAGE_ENDPOINT_URL")
    object_storage_access_key: SecretStr = Field(alias="OBJECT_STORAGE_ACCESS_KEY")
    object_storage_secret_key: SecretStr = Field(alias="OBJECT_STORAGE_SECRET_KEY")
    object_storage_bucket: str = Field(
        min_length=3,
        max_length=63,
        alias="OBJECT_STORAGE_BUCKET",
    )
    object_storage_region: str = Field(
        default="us-east-1",
        min_length=1,
        max_length=64,
        alias="OBJECT_STORAGE_REGION",
    )
    object_storage_path_style: bool = Field(
        default=True,
        alias="OBJECT_STORAGE_PATH_STYLE",
    )

    @field_validator("twenty_integration_api_key", mode="before")
    @classmethod
    def empty_twenty_key_is_unconfigured(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("core_database_url")
    @classmethod
    def validate_core_database_url(cls, value: SecretStr) -> SecretStr:
        parsed = urlparse(value.get_secret_value())
        if (
            parsed.scheme not in {"postgresql", "postgres"}
            or parsed.hostname is None
            or parsed.username is None
            or parsed.path in {"", "/"}
        ):
            raise ValueError("ungültiger PostgreSQL-DSN")
        return value

    def safe_summary(self) -> dict[str, str]:
        return {
            "environment": self.environment,
            "serviceName": self.service_name,
            "serviceVersion": self.service_version,
            "apiVersion": self.api_version,
            "publicBaseHost": self.public_base_url.host or "invalid",
            "allowedOriginCount": str(len(self.allowed_origins)),
            "trustedProxyHeaders": str(self.trust_proxy_headers).lower(),
            "invitationTtlMinutes": str(self.invitation_ttl_minutes),
            "loginChallengeTtlMinutes": str(self.login_challenge_ttl_minutes),
            "freshLoginSeconds": str(self.fresh_login_seconds),
            "coreDatabaseHost": urlparse(
                self.core_database_url.get_secret_value()
            ).hostname
            or "invalid",
            "twentyBaseHost": self.twenty_base_url.host or "invalid",
            "twentyIntegration": (
                "configured"
                if self.twenty_integration_api_key is not None
                else "unconfigured"
            ),
            "twentyHealthHost": self.twenty_health_url.host or "invalid",
            "rustfsHealthHost": self.rustfs_health_url.host or "invalid",
            "objectStorageHost": self.object_storage_endpoint_url.host or "invalid",
            "objectStorageBucket": self.object_storage_bucket,
        }

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        configured = tuple(
            item.strip().rstrip("/")
            for item in self.allowed_origins_value.split(",")
            if item.strip()
        )
        public_origin = (
            f"{self.public_base_url.scheme}://{self.public_base_url.host}"
            + (
                f":{self.public_base_url.port}"
                if self.public_base_url.port is not None
                else ""
            )
        )
        return tuple(dict.fromkeys((*configured, public_origin.rstrip("/"))))


def load_settings() -> Settings:
    try:
        # BaseSettings resolves required aliases from the process environment.
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        diagnostics = sorted(
            {
                f"{'.'.join(str(part) for part in item['loc'])}:{item['type']}"
                for item in error.errors(include_url=False, include_input=False)
            }
        )
        raise ConfigurationError(
            "LeonAid-Konfiguration ist ungültig: " + ", ".join(diagnostics)
        ) from None
