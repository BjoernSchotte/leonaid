"""Typed startup configuration with secret-safe diagnostics."""

from __future__ import annotations

from email.utils import parseaddr
from ipaddress import ip_address
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Configuration failed without exposing its values."""


def _is_forbidden_public_host(host: str | None) -> bool:
    if host is None:
        return True
    normalized = host.rstrip(".").casefold()
    reserved_examples = ("example.com", "example.net", "example.org")
    if (
        normalized == "localhost"
        or normalized.endswith((".localhost", ".invalid", ".test", ".example"))
        or any(
            normalized == candidate or normalized.endswith(f".{candidate}")
            for candidate in reserved_examples
        )
    ):
        return True
    try:
        address = ip_address(normalized)
    except ValueError:
        return False
    return not address.is_global


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["local", "test", "production"] = Field(alias="LEONAID_ENV")
    service_name: str = Field(default="leonaid-api", alias="LEONAID_SERVICE_NAME")
    service_version: str = Field(default="0.0.0", alias="LEONAID_SERVICE_VERSION")
    release_commit: str | None = Field(default=None, alias="LEONAID_RELEASE_COMMIT")
    api_version: str = Field(default="v1", alias="LEONAID_API_VERSION")
    core_database_url: SecretStr = Field(alias="CORE_DATABASE_URL")
    invitation_hmac_secret: SecretStr = Field(
        min_length=32,
        alias="LEONAID_SECRET_KEY",
    )
    mail_payload_secret: SecretStr = Field(
        min_length=32,
        alias="LEONAID_SESSION_ENCRYPTION_KEY",
    )
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
    maintenance_flag_path: Path = Field(
        default=Path("/run/leonaid-maintenance/enabled"),
        alias="LEONAID_MAINTENANCE_FLAG_PATH",
    )
    twenty_base_url: HttpUrl = Field(alias="TWENTY_BASE_URL")
    twenty_integration_api_key: SecretStr | None = Field(
        default=None,
        alias="TWENTY_INTEGRATION_API_KEY",
    )
    twenty_health_url: HttpUrl = Field(alias="TWENTY_HEALTH_URL")
    rustfs_health_url: HttpUrl = Field(alias="RUSTFS_HEALTH_URL")
    mail_health_url: HttpUrl = Field(
        default=HttpUrl("http://mailpit:8025/mail/api/v1/info"),
        alias="MAIL_HEALTH_URL",
    )
    worker_health_url: HttpUrl = Field(
        default=HttpUrl("http://worker:8010/health/ready"),
        alias="WORKER_HEALTH_URL",
    )
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

    @model_validator(mode="after")
    def validate_production_boundary(self) -> Settings:
        if self.environment != "production":
            return self
        if (
            self.release_commit is None
            or re.fullmatch(
                r"[0-9a-f]{40}",
                self.release_commit,
            )
            is None
        ):
            raise ValueError("Produktion erfordert einen vollständigen Release-Commit.")
        if self.public_base_url.scheme != "https" or _is_forbidden_public_host(
            self.public_base_url.host
        ):
            raise ValueError("Produktion erfordert eine öffentliche HTTPS-Basis-URL.")
        if not self.trust_proxy_headers:
            raise ValueError(
                "Produktion erfordert validierte Proxy-Header am Caddy-Rand."
            )
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if parsed.scheme != "https" or _is_forbidden_public_host(parsed.hostname):
                raise ValueError(
                    "Produktive Origins müssen öffentliche HTTPS-Origins sein."
                )
        if (self.mail_health_url.host or "").casefold() == "mailpit":
            raise ValueError("Mailpit ist in Produktion nicht erlaubt.")
        if self.object_storage_bucket == "leonaid":
            raise ValueError(
                "Produktion erfordert einen umgebungsspezifischen Object-Store-Bucket."
            )
        if (
            self.invitation_hmac_secret.get_secret_value()
            == self.mail_payload_secret.get_secret_value()
        ):
            raise ValueError(
                "Produktive HMAC- und Payload-Secrets müssen getrennt sein."
            )
        return self

    def safe_summary(self) -> dict[str, str]:
        return {
            "environment": self.environment,
            "serviceName": self.service_name,
            "serviceVersion": self.service_version,
            "releaseCommit": (
                "configured" if self.release_commit is not None else "unconfigured"
            ),
            "apiVersion": self.api_version,
            "publicBaseHost": self.public_base_url.host or "invalid",
            "allowedOriginCount": str(len(self.allowed_origins)),
            "trustedProxyHeaders": str(self.trust_proxy_headers).lower(),
            "invitationTtlMinutes": str(self.invitation_ttl_minutes),
            "loginChallengeTtlMinutes": str(self.login_challenge_ttl_minutes),
            "freshLoginSeconds": str(self.fresh_login_seconds),
            "maintenanceFlagPath": str(self.maintenance_flag_path),
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
            "mailHealthHost": self.mail_health_url.host or "invalid",
            "workerHealthHost": self.worker_health_url.host or "invalid",
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


class MailTransportSettings(BaseSettings):
    """Worker-only SMTP settings with production-safe validation."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["local", "test", "production"] = Field(
        default="local",
        alias="LEONAID_ENV",
    )
    host: str = Field(min_length=1, alias="MAIL_SMTP_HOST")
    port: int = Field(ge=1, le=65535, alias="MAIL_SMTP_PORT")
    sender: str = Field(min_length=3, alias="MAIL_FROM")
    mode: Literal["plain", "starttls", "tls"] = Field(
        default="starttls",
        alias="MAIL_SMTP_MODE",
    )
    username: str | None = Field(default=None, alias="MAIL_SMTP_USERNAME")
    password: SecretStr | None = Field(default=None, alias="MAIL_SMTP_PASSWORD")
    timeout_seconds: float = Field(
        default=10,
        gt=0,
        le=120,
        alias="MAIL_SMTP_TIMEOUT_SECONDS",
    )
    verify_certificates: bool = Field(
        default=True,
        alias="MAIL_SMTP_VERIFY_CERTIFICATES",
    )
    ca_file: Path | None = Field(default=None, alias="MAIL_SMTP_CA_FILE")

    @field_validator("username", "password", "ca_file", mode="before")
    @classmethod
    def empty_mail_credentials_are_unconfigured(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def model_post_init(self, __context: object) -> None:
        if (self.username is None) != (self.password is None):
            raise ValueError(
                "SMTP-Benutzername und -Passwort müssen gemeinsam gesetzt sein."
            )
        if self.environment == "production":
            if self.mode == "plain":
                raise ValueError("Produktiver SMTP-Versand erfordert TLS.")
            if not self.verify_certificates:
                raise ValueError(
                    "Produktiver SMTP-Versand erfordert Zertifikatsprüfung."
                )
            sender_address = parseaddr(self.sender)[1]
            sender_domain = (
                sender_address.rsplit("@", maxsplit=1)[1]
                if "@" in sender_address
                else ""
            )
            if not sender_domain or _is_forbidden_public_host(sender_domain):
                raise ValueError(
                    "Produktion erfordert eine Absenderadresse mit realer Domain."
                )
            if self.host.casefold() in {"mailpit", "localhost"}:
                raise ValueError(
                    "Mailpit und Loopback-SMTP sind in Produktion verboten."
                )

    def safe_summary(self) -> dict[str, str]:
        return {
            "host": self.host,
            "port": str(self.port),
            "mode": self.mode,
            "authentication": (
                "configured" if self.username is not None else "unconfigured"
            ),
            "certificateVerification": str(self.verify_certificates).lower(),
            "customCertificateAuthority": (
                "configured" if self.ca_file is not None else "unconfigured"
            ),
        }


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


def load_mail_transport_settings() -> MailTransportSettings:
    try:
        return MailTransportSettings()  # type: ignore[call-arg]
    except ValidationError as error:
        diagnostics = sorted(
            {
                f"{'.'.join(str(part) for part in item['loc'])}:{item['type']}"
                for item in error.errors(include_url=False, include_input=False)
            }
        )
        raise ConfigurationError(
            "LeonAid-Mailkonfiguration ist ungültig: " + ", ".join(diagnostics)
        ) from None
