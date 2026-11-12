"""Typed startup configuration with secret-safe diagnostics."""

from __future__ import annotations

from email.utils import parseaddr
from ipaddress import ip_address
from pathlib import Path
import hashlib
import hmac
import re
import unicodedata
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from leonaid.application.links import LinkBuilder
from leonaid.adapters.site_host_checks import HostCheckSettings
from leonaid.adapters.web_push import VapidSigner
from leonaid.domain.site_hosts import ConfiguredHosts


CLUB_NAME_MAX_LENGTH = 120
DEVELOPMENT_CLUB_NAME = "Lions Club Musterstadt"
PRODUCTION_CLUB_NAME_MISSING = (
    "Production requires LEONAID_CLUB_NAME (the club name shown in the admin rail)."
)


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


MODULE_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]*\Z")


def parse_module_ids(raw: str) -> frozenset[str]:
    """Comma-separated module IDs; blanks are ignored, malformed IDs fail."""
    names = frozenset(part.strip() for part in raw.split(",") if part.strip())
    for name in names:
        if not MODULE_ID_PATTERN.fullmatch(name):
            raise ValueError("LEONAID_DISABLED_MODULES contains an invalid module ID")
    return names


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
    disabled_modules_raw: str = Field(default="", alias="LEONAID_DISABLED_MODULES")
    core_database_url: SecretStr = Field(alias="CORE_DATABASE_URL")
    invitation_hmac_secret: SecretStr = Field(
        min_length=32,
        alias="LEONAID_SECRET_KEY",
    )
    mail_payload_secret: SecretStr = Field(
        min_length=32,
        alias="LEONAID_SESSION_ENCRYPTION_KEY",
    )
    order_submission_key: SecretStr | None = Field(
        default=None, alias="LEONAID_ORDER_SUBMISSION_KEY"
    )
    # Admin base URL: member mails (login, invitation, e-mail change). In a
    # single-host installation the only host (specs/multi-domain §6.1).
    public_base_url: HttpUrl = Field(alias="LEONAID_PUBLIC_BASE_URL")
    # Public host base URL for public links (survey invitations). Unset: the
    # admin base URL.
    site_base_url_value: HttpUrl | None = Field(
        default=None, alias="LEONAID_SITE_BASE_URL"
    )
    # One club per installation; shown in the admin rail. Required in production.
    club_name_value: str | None = Field(default=None, alias="LEONAID_CLUB_NAME")
    survey_erasure_archive_dir: Path | None = Field(
        default=None, alias="LEONAID_SURVEY_ERASURE_ARCHIVE_DIR"
    )
    allowed_origins_value: str = Field(
        default="",
        alias="LEONAID_ALLOWED_ORIGINS",
    )
    # Origins allowed for /api/v1/public/* without credentials: the public
    # host and its aliases (specs/multi-domain §6.3).
    public_origins_value: str = Field(default="", alias="LEONAID_PUBLIC_ORIGINS")
    # Extra names of the public host (www.); a campaign host must not take
    # them (specs/multi-domain §7.3). Commas or whitespace.
    public_domain_aliases_value: str = Field(
        default="", alias="LEONAID_PUBLIC_DOMAIN_ALIASES"
    )
    # False: the installation has no general public host, only the admin host
    # and campaign hosts (§6.6). Path-based campaign URLs then do not exist.
    public_host_enabled: bool = Field(default=True, alias="LEONAID_PUBLIC_HOST_ENABLED")
    # True: the campaign site (compose profile emdash) runs and serves the
    # CMS editor at /_emdash. False: no navigation entry or link leads there.
    cms_enabled: bool = Field(default=False, alias="LEONAID_CMS_ENABLED")
    # Host check of campaign hosts (specs/multi-domain §7.4). The HTTP check
    # goes to port 80 of every public address of the name; the TLS check
    # shakes hands with the edge proxy. Private addresses and a test CA are
    # for the dev stack and tests only.
    site_host_check_http_port: int = Field(
        default=80, ge=1, le=65535, alias="LEONAID_SITE_HOST_CHECK_HTTP_PORT"
    )
    site_host_check_allow_private: bool = Field(
        default=False, alias="LEONAID_SITE_HOST_CHECK_ALLOW_PRIVATE"
    )
    site_host_tls_edge: str = Field(
        default="proxy:443",
        pattern=r"^[a-z0-9.-]+:[0-9]{1,5}$",
        alias="LEONAID_SITE_HOST_TLS_EDGE",
    )
    # The edge's own public addresses; a campaign host must resolve to
    # these only. Empty: the addresses of LEONAID_SITE_HOST_EDGE_NAME, by
    # default the admin host (§7.4).
    site_host_edge_addresses_value: str = Field(
        default="", alias="LEONAID_SITE_HOST_EDGE_ADDRESSES"
    )
    site_host_edge_name: str = Field(default="", alias="LEONAID_SITE_HOST_EDGE_NAME")
    # Public resolvers that must agree with ours (split-view DNS, §7.4).
    # Unset: 1.1.1.1 and 9.9.9.9 in production, none elsewhere; "none" off.
    site_host_public_resolvers_value: str = Field(
        default="", alias="LEONAID_SITE_HOST_PUBLIC_RESOLVERS"
    )
    site_host_tls_ca_file: Path | None = Field(
        default=None, alias="LEONAID_SITE_HOST_TLS_CA_FILE"
    )
    # Periodic re-check in the API process (it has the egress the check
    # needs); 0 switches it off (tests).
    site_host_recheck_interval_seconds: float = Field(
        default=0, ge=0, le=86400, alias="LEONAID_SITE_HOST_RECHECK_INTERVAL_SECONDS"
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
    pilot_monitor_status_url: HttpUrl | None = Field(
        default=None,
        alias="PILOT_MONITOR_STATUS_URL",
    )
    pilot_alertmanager_url: HttpUrl | None = Field(
        default=None,
        alias="PILOT_ALERTMANAGER_URL",
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

    @field_validator("site_host_edge_addresses_value")
    @classmethod
    def valid_edge_addresses(cls, value: str) -> str:
        for item in re.split(r"[\s,]+", value):
            if item:
                try:
                    ip_address(item)
                except ValueError:
                    raise ValueError(
                        f"LEONAID_SITE_HOST_EDGE_ADDRESSES: {item} is no IP address"
                    ) from None
        return value

    @field_validator("site_host_public_resolvers_value")
    @classmethod
    def valid_public_resolvers(cls, value: str) -> str:
        if value.strip().casefold() == "none":
            return value
        for item in re.split(r"[\s,]+", value):
            if item:
                try:
                    ip_address(item)
                except ValueError:
                    raise ValueError(
                        f"LEONAID_SITE_HOST_PUBLIC_RESOLVERS: {item} is no IP address"
                    ) from None
        return value

    @field_validator("site_base_url_value", "site_host_tls_ca_file", mode="before")
    @classmethod
    def empty_site_base_url_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("order_submission_key", mode="before")
    @classmethod
    def validate_order_submission_key(cls, value: object) -> object:
        if value is None or value == "":
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str) or re.fullmatch(r"[0-9a-f]{64}", raw) is None:
            raise ValueError("Order submission key must be 32 random bytes as hex.")
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
            raise ValueError("invalid PostgreSQL DSN")
        return value

    @field_validator("club_name_value", mode="before")
    @classmethod
    def validate_club_name(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("LEONAID_CLUB_NAME must be text.")
        name = " ".join(value.split())
        if not name:
            return None
        if len(name) > CLUB_NAME_MAX_LENGTH or any(
            unicodedata.category(character).startswith("C") for character in name
        ):
            raise ValueError(
                f"LEONAID_CLUB_NAME must be 1 to {CLUB_NAME_MAX_LENGTH} printable characters."
            )
        return name

    @property
    def club_name(self) -> str:
        """The configured club name; local and test fall back to a sample."""
        return self.club_name_value or DEVELOPMENT_CLUB_NAME

    @model_validator(mode="after")
    def validate_production_boundary(self) -> Settings:
        if (self.pilot_monitor_status_url is None) != (
            self.pilot_alertmanager_url is None
        ):
            raise ValueError(
                "Pilot monitor status and Alertmanager must be configured together."
            )
        if self.environment != "production":
            return self
        if self.club_name_value is None:
            raise ValueError(PRODUCTION_CLUB_NAME_MISSING)
        if (
            self.release_commit is None
            or re.fullmatch(
                r"[0-9a-f]{40}",
                self.release_commit,
            )
            is None
        ):
            raise ValueError("Production requires a full release commit.")
        if self.public_base_url.scheme != "https" or _is_forbidden_public_host(
            self.public_base_url.host
        ):
            raise ValueError("Production requires a public HTTPS base URL.")
        if not self.trust_proxy_headers:
            raise ValueError(
                "Production requires validated proxy headers at the Caddy edge."
            )
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if parsed.scheme != "https" or _is_forbidden_public_host(parsed.hostname):
                raise ValueError("Production origins must be public HTTPS origins.")
        site = self.site_base_url
        if site.scheme != "https" or _is_forbidden_public_host(site.host):
            raise ValueError("Production requires a public HTTPS site base URL.")
        for origin in self.public_origins:
            parsed = urlparse(origin)
            if parsed.scheme != "https" or _is_forbidden_public_host(parsed.hostname):
                raise ValueError(
                    "Production public origins must be public HTTPS origins."
                )
        if set(self.public_origins) & set(self.allowed_origins):
            raise ValueError(
                "A public origin must not also be a credentialed admin origin."
            )
        for item in self.host_check_settings.edge_addresses:
            if not ip_address(item).is_global:
                raise ValueError("Production edge addresses must be public: " + item)
        if self.site_host_check_allow_private or self.site_host_tls_ca_file:
            raise ValueError(
                "Production checks campaign hosts on public addresses with the "
                "system trust store only."
            )
        if (self.mail_health_url.host or "").casefold() == "mailpit":
            raise ValueError("Mailpit is not allowed in production.")
        if self.object_storage_bucket == "leonaid":
            raise ValueError(
                "Production requires an environment-specific object store bucket."
            )
        if (
            self.invitation_hmac_secret.get_secret_value()
            == self.mail_payload_secret.get_secret_value()
        ):
            raise ValueError("Production HMAC and payload secrets must differ.")
        return self

    @field_validator("disabled_modules_raw")
    @classmethod
    def disabled_modules_are_well_formed(cls, value: str) -> str:
        parse_module_ids(value)
        return value

    @property
    def disabled_modules(self) -> frozenset[str]:
        return parse_module_ids(self.disabled_modules_raw)

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
            "siteBaseHost": self.site_base_url.host or "invalid",
            "publicOriginCount": str(len(self.public_origins)),
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
            "pilotMonitoring": (
                "configured"
                if self.pilot_monitor_status_url is not None
                else "unconfigured"
            ),
            "objectStorageHost": self.object_storage_endpoint_url.host or "invalid",
            "objectStorageBucket": self.object_storage_bucket,
        }

    @property
    def site_base_url(self) -> HttpUrl:
        return self.site_base_url_value or self.public_base_url

    @property
    def links(self) -> LinkBuilder:
        return LinkBuilder(
            admin_base_url=str(self.public_base_url),
            site_base_url=str(self.site_base_url),
        )

    @property
    def configured_hosts(self) -> ConfiguredHosts:
        """Hosts from the environment that no site host may take (§7.3)."""
        admin = (self.public_base_url.host or "").casefold()
        aliases = tuple(
            dict.fromkeys(
                item.strip().rstrip(".").casefold()
                for item in re.split(r"[\s,]+", self.public_domain_aliases_value)
                if item.strip()
            )
        )
        public = (
            (self.site_base_url.host or "").casefold()
            if self.public_host_enabled
            else None
        )
        return ConfiguredHosts(
            admin=admin,
            public=public,
            aliases=aliases,
            allow_test_names=self.environment != "production",
        )

    @property
    def site_host_public_resolvers(self) -> tuple[str, ...]:
        value = self.site_host_public_resolvers_value.strip()
        if value.casefold() == "none":
            return ()
        if not value:
            return ("1.1.1.1", "9.9.9.9") if self.environment == "production" else ()
        return tuple(item for item in re.split(r"[\s,]+", value) if item)

    @property
    def site_host_check_secret(self) -> str:
        """A key of its own for the host check answer, from the HMAC secret."""
        return hmac.new(
            self.invitation_hmac_secret.get_secret_value().encode("utf-8"),
            b"leonaid.site-host-check.v1",
            hashlib.sha256,
        ).hexdigest()

    @property
    def host_check_settings(self) -> HostCheckSettings:
        edge_host, _, edge_port = self.site_host_tls_edge.rpartition(":")
        return HostCheckSettings(
            secret=self.site_host_check_secret,
            edge_addresses=tuple(
                item
                for item in re.split(r"[\s,]+", self.site_host_edge_addresses_value)
                if item
            ),
            edge_name=self.site_host_edge_name.strip()
            or (self.public_base_url.host or ""),
            http_port=self.site_host_check_http_port,
            allow_private_addresses=self.site_host_check_allow_private,
            tls_edge_host=edge_host,
            tls_edge_port=int(edge_port),
            tls_ca_file=(
                str(self.site_host_tls_ca_file) if self.site_host_tls_ca_file else None
            ),
            public_resolvers=self.site_host_public_resolvers,
        )

    @property
    def public_origins(self) -> tuple[str, ...]:
        """Static credential-free origins of the public API (§6.3)."""
        # Commas or whitespace, like every other host list (ruling R3).
        return tuple(
            dict.fromkeys(
                item.rstrip("/").casefold()
                for item in re.split(r"[\s,]+", self.public_origins_value)
                if item
            )
        )

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        configured = tuple(
            item.strip().rstrip("/")
            for item in self.allowed_origins_value.split(",")
            if item.strip()
        )
        url = self.public_base_url
        # Browsers omit the scheme's default port in Origin.
        default_port = {"http": 80, "https": 443}.get(url.scheme)
        public_origin = f"{url.scheme}://{url.host}" + (
            f":{url.port}" if url.port not in (None, default_port) else ""
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
    envelope_from: str | None = Field(default=None, alias="MAIL_ENVELOPE_FROM")
    reply_to: str | None = Field(default=None, alias="MAIL_REPLY_TO")
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
    # Staging only: Mailpit plays the relay with a private CA. The pilot
    # doctor and deployment contract allow it on a staging installation only.
    staging_mailpit: bool = Field(default=False, alias="LEONAID_STAGING_MAILPIT")

    @field_validator(
        "username",
        "password",
        "ca_file",
        "envelope_from",
        "reply_to",
        mode="before",
    )
    @classmethod
    def empty_mail_credentials_are_unconfigured(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def model_post_init(self, __context: object) -> None:
        if (self.username is None) != (self.password is None):
            raise ValueError("SMTP username and password must be set together.")
        if self.environment == "production":
            if self.mode == "plain":
                raise ValueError("Production SMTP delivery requires TLS.")
            if not self.verify_certificates:
                raise ValueError(
                    "Production SMTP delivery requires certificate verification."
                )
            sender_address = parseaddr(self.sender)[1]
            sender_domain = (
                sender_address.rsplit("@", maxsplit=1)[1]
                if "@" in sender_address
                else ""
            )
            if not sender_domain or _is_forbidden_public_host(sender_domain):
                raise ValueError(
                    "Production requires a sender address with a real domain."
                )
            for label, value in (
                ("Envelope-From", self.envelope_from),
                ("Reply-To", self.reply_to),
            ):
                address = parseaddr(value or "")[1]
                domain = (
                    address.rsplit("@", maxsplit=1)[1]
                    if address.count("@") == 1
                    else ""
                )
                if not domain or _is_forbidden_public_host(domain):
                    raise ValueError(
                        f"Production requires an explicit {label} with a real domain."
                    )
            host = self.host.casefold()
            staging_relay = (
                host == "mailpit" and self.staging_mailpit and self.ca_file is not None
            )
            if host in {"mailpit", "localhost"} and not staging_relay:
                raise ValueError(
                    "Mailpit and loopback SMTP are forbidden in production."
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
            "envelopeFrom": (
                "configured"
                if self.envelope_from is not None
                else "derived-from-visible-sender"
            ),
            "replyTo": ("configured" if self.reply_to is not None else "unconfigured"),
        }


class RetentionSettings(BaseSettings):
    """Worker-only retention of finished technical rows.

    Only successfully completed outbox jobs that nothing references any more
    are deleted after ``outbox_days``; pending, processing and dead-letter jobs
    stay until they are handled. Expired rate-limit attempts are removed on
    the same cadence instead of on every API request.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    outbox_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        alias="OUTBOX_RETENTION_DAYS",
    )
    interval_seconds: float = Field(
        default=3600,
        ge=1,
        le=86400,
        alias="OUTBOX_RETENTION_INTERVAL_SECONDS",
    )
    batch_size: int = Field(
        default=500,
        ge=1,
        le=10000,
        alias="OUTBOX_RETENTION_BATCH_SIZE",
    )
    max_batches: int = Field(
        default=20,
        ge=1,
        le=1000,
        alias="OUTBOX_RETENTION_MAX_BATCHES",
    )


DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_TILE_ORIGIN = "https://tile.openstreetmap.org"
DEFAULT_ATTRIBUTION = "© OpenStreetMap-Mitwirkende"
DEFAULT_GEOCODER_URL = "https://nominatim.openstreetmap.org/search"
_HEADER_TEXT = re.compile(r"[\x20-\x7e]+\Z")


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{(parsed.hostname or '').casefold()}{port}"


class MapSettings(BaseSettings):
    """Map tiles and the geocoder of the installation (specs/krapfentaxi-touren §8).

    The browser loads tiles from ``tile_url``; the CSP opens ``img-src`` for
    ``tile_origin`` only, so an absolute tile URL must name that origin. A
    path (``/tiles/...``) is served by the own host. The worker sends only
    street, postal code, city and country to ``geocoder_url`` (a Nominatim
    JSON API) with ``geocoder_user_agent``, as the Nominatim usage policy
    asks.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    tile_url: str = Field(default=DEFAULT_TILE_URL, alias="LEONAID_MAP_TILE_URL")
    tile_origin: str = Field(
        default=DEFAULT_TILE_ORIGIN, alias="LEONAID_MAP_TILE_ORIGIN"
    )
    attribution: str = Field(
        default=DEFAULT_ATTRIBUTION, alias="LEONAID_MAP_ATTRIBUTION"
    )
    geocoder_url: str = Field(
        default=DEFAULT_GEOCODER_URL, alias="LEONAID_GEOCODER_URL"
    )
    geocoder_user_agent_value: str = Field(
        default="", alias="LEONAID_GEOCODER_USER_AGENT"
    )
    public_base_url_value: str = Field(default="", alias="LEONAID_PUBLIC_BASE_URL")
    geocoding_interval_seconds: float = Field(
        default=60, ge=5, le=86400, alias="LEONAID_GEOCODING_INTERVAL_SECONDS"
    )

    @field_validator(
        "tile_url",
        "tile_origin",
        "attribution",
        "geocoder_url",
        "geocoding_interval_seconds",
        mode="before",
    )
    @classmethod
    def blank_means_default(cls, value: object, info: ValidationInfo) -> object:
        # Compose passes unset variables as empty strings.
        if isinstance(value, str) and not value.strip():
            assert info.field_name is not None
            return cls.model_fields[info.field_name].default
        return value

    @field_validator("tile_url")
    @classmethod
    def tile_url_is_a_template(cls, value: str) -> str:
        if not value.startswith(("https://", "/")) or value.startswith("//"):
            raise ValueError("must be an https URL or a path on the own host")
        if not all(part in value for part in ("{z}", "{x}", "{y}")):
            raise ValueError("must contain {z}, {x} and {y}")
        if any(character.isspace() for character in value):
            raise ValueError("must not contain whitespace")
        return value

    @field_validator("tile_origin")
    @classmethod
    def tile_origin_is_an_origin(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
        ):
            raise ValueError("must be an https origin without a path")
        return _origin_of(value)

    @field_validator("attribution")
    @classmethod
    def attribution_is_plain_text(cls, value: str) -> str:
        text = " ".join(value.split())
        if not text or len(text) > 200 or any(char in text for char in "<>"):
            raise ValueError("must be plain text of 1 to 200 characters")
        return text

    @field_validator("geocoder_url")
    @classmethod
    def geocoder_url_is_http(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("must be an http(s) URL")
        if parsed.query or parsed.fragment or parsed.username is not None:
            raise ValueError("must not carry a query, fragment or credentials")
        return value

    @field_validator("geocoder_user_agent_value")
    @classmethod
    def user_agent_is_header_text(cls, value: str) -> str:
        text = value.strip()
        if text and (len(text) > 200 or not _HEADER_TEXT.fullmatch(text)):
            raise ValueError("must be printable ASCII of at most 200 characters")
        return text

    @model_validator(mode="after")
    def tiles_come_from_the_named_origin(self) -> MapSettings:
        if self.tile_url.startswith("https://") and (
            _origin_of(self.tile_url) != self.tile_origin
        ):
            raise ConfigurationError("LEONAID_MAP_TILE_ORIGIN:mismatch")
        if not self.geocoder_user_agent_value and not self.public_base_url_value:
            raise ConfigurationError("LEONAID_GEOCODER_USER_AGENT:missing")
        return self

    @property
    def geocoder_user_agent(self) -> str:
        if self.geocoder_user_agent_value:
            return self.geocoder_user_agent_value
        return f"LeonAid ({self.public_base_url_value.strip().rstrip('/')})"


class PushSettings(BaseSettings):
    """Web Push keys of the installation (ADR-0017).

    ``LEONAID_VAPID_PRIVATE_KEY`` is a P-256 private key as the base64url of
    its 32-octet scalar; ``./leonaid bootstrap`` and the pilot secret
    generation create it. ``LEONAID_VAPID_SUBJECT`` is the operator's
    contact (``mailto:`` or ``https:``) that the push services read from
    each push. Without the key push notifications are "not configured":
    the API says so and the worker sends nothing.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    environment: str = Field(default="local", alias="LEONAID_ENV")
    vapid_private_key: SecretStr | None = Field(
        default=None, alias="LEONAID_VAPID_PRIVATE_KEY"
    )
    vapid_subject: str = Field(default="", alias="LEONAID_VAPID_SUBJECT")

    @field_validator("vapid_private_key", mode="before")
    @classmethod
    def blank_key_is_unconfigured(cls, value: object) -> object:
        # Compose passes unset variables as empty strings.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def key_and_subject_fit(self) -> PushSettings:
        if self.vapid_private_key is None:
            return self
        subject = self.vapid_subject.strip()
        if not subject:
            raise ConfigurationError("LEONAID_VAPID_SUBJECT:missing")
        try:
            VapidSigner(self.vapid_private_key.get_secret_value(), subject)
        except ValueError as error:
            name = "SUBJECT" if "subject" in str(error) else "PRIVATE_KEY"
            raise ConfigurationError(f"LEONAID_VAPID_{name}:invalid") from None
        if self.environment == "production":
            host = (
                subject.rsplit("@", 1)[-1]
                if subject.startswith("mailto:")
                else urlparse(subject).hostname
            )
            if _is_forbidden_public_host(host):
                raise ConfigurationError("LEONAID_VAPID_SUBJECT:not_public")
        return self

    @property
    def configured(self) -> bool:
        return self.vapid_private_key is not None

    def signer(self) -> VapidSigner | None:
        if self.vapid_private_key is None:
            return None
        return VapidSigner(
            self.vapid_private_key.get_secret_value(), self.vapid_subject
        )

    def safe_summary(self) -> dict[str, str]:
        return {"webPush": "configured" if self.configured else "unconfigured"}


class ModuleSettings(BaseSettings):
    """Per-installation module switches, shared by the API and the worker.

    ``LEONAID_DISABLED_MODULES`` lists module IDs separated by commas. A
    switched-off module keeps its data: it contributes no navigation and no
    routes, and the worker leaves its jobs pending and runs none of its loops.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    disabled_modules_raw: str = Field(default="", alias="LEONAID_DISABLED_MODULES")

    @field_validator("disabled_modules_raw")
    @classmethod
    def disabled_modules_are_well_formed(cls, value: str) -> str:
        parse_module_ids(value)
        return value

    @property
    def disabled_modules(self) -> frozenset[str]:
        return parse_module_ids(self.disabled_modules_raw)


def load_module_settings() -> ModuleSettings:
    try:
        return ModuleSettings()
    except ValidationError:
        raise ConfigurationError(
            "LeonAid module configuration is invalid: LEONAID_DISABLED_MODULES"
        ) from None


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
        # The club name rule names the variable; its text holds no input.
        if any(
            PRODUCTION_CLUB_NAME_MISSING in item["msg"]
            for item in error.errors(include_url=False, include_input=False)
        ):
            diagnostics.insert(0, PRODUCTION_CLUB_NAME_MISSING)
        raise ConfigurationError(
            "LeonAid configuration is invalid: " + ", ".join(diagnostics)
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
            "LeonAid mail configuration is invalid: " + ", ".join(diagnostics)
        ) from None


def load_retention_settings() -> RetentionSettings:
    try:
        return RetentionSettings()
    except ValidationError as error:
        diagnostics = sorted(
            {
                f"{'.'.join(str(part) for part in item['loc'])}:{item['type']}"
                for item in error.errors(include_url=False, include_input=False)
            }
        )
        raise ConfigurationError(
            "LeonAid retention configuration is invalid: " + ", ".join(diagnostics)
        ) from None


class LinkSettings(BaseSettings):
    """Base URLs for links in mails that the worker builds itself.

    The same two variables as in ``Settings``: the admin host, and the public
    host when the installation has its own (``LEONAID_SITE_BASE_URL``). The
    delivery-day mail links the legal pages of the public host.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    public_base_url: HttpUrl = Field(alias="LEONAID_PUBLIC_BASE_URL")
    site_base_url_value: HttpUrl | None = Field(
        default=None, alias="LEONAID_SITE_BASE_URL"
    )

    @field_validator("site_base_url_value", mode="before")
    @classmethod
    def empty_site_base_url_is_unset(cls, value: object) -> object:
        # Compose passes unset variables as empty strings.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def links(self) -> LinkBuilder:
        return LinkBuilder(
            admin_base_url=str(self.public_base_url),
            site_base_url=str(self.site_base_url_value or self.public_base_url),
        )


def load_link_settings() -> LinkSettings:
    try:
        # BaseSettings resolves the required alias from the environment.
        return LinkSettings()  # type: ignore[call-arg]
    except ValidationError as error:
        diagnostics = sorted(
            {
                f"{_alias_of(item['loc'])}:{item['type']}"
                for item in error.errors(include_url=False, include_input=False)
            }
        )
        raise ConfigurationError(
            "LeonAid link configuration is invalid: " + ", ".join(diagnostics)
        ) from None


def load_map_settings() -> MapSettings:
    try:
        return MapSettings()
    except ConfigurationError:
        raise
    except ValidationError as error:
        diagnostics = sorted(
            {
                f"{_alias_of(item['loc'])}:{item['type']}"
                for item in error.errors(include_url=False, include_input=False)
            }
        )
        raise ConfigurationError(
            "LeonAid map configuration is invalid: " + ", ".join(diagnostics)
        ) from None


def load_push_settings() -> PushSettings:
    try:
        return PushSettings()
    except ConfigurationError as error:
        raise ConfigurationError(
            f"LeonAid push configuration is invalid: {error}"
        ) from None
    except ValidationError:
        raise ConfigurationError(
            "LeonAid push configuration is invalid: LEONAID_VAPID_PRIVATE_KEY"
        ) from None


def _alias_of(location: tuple[int | str, ...]) -> str:
    name = ".".join(str(part) for part in location)
    field = MapSettings.model_fields.get(name)
    return field.alias if field is not None and field.alias else name
