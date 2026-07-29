#!/usr/bin/env python3
"""Fail-closed operational readiness checks for a LeonAid pilot deployment."""

from __future__ import annotations

import argparse
import datetime as dt
from email.utils import parsedate_to_datetime
import http.client
import json
from pathlib import Path
import re
import shutil
import socket
import ssl
import sys
from typing import Any
from urllib.parse import urlparse

from tools.pilot_decisions.check import (
    DecisionError,
    parse_register,
    readiness,
    validate_register,
)
from tools.pilot_deployment.validate import (
    DeploymentContractError,
    object_value,
    validate,
)

FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SAFE_PROJECT = re.compile(r"^leonaid-(production|staging)(?:-[a-z0-9-]+)?$")
REMOTE_BACKUP_PREFIXES = (
    "azure:",
    "b2:",
    "gs:",
    "rclone:",
    "rest:",
    "s3:",
    "sftp:",
)
SECRET_KEYS = (
    "CORE_POSTGRES_PASSWORD",
    "LEONAID_SECRET_KEY",
    "LEONAID_SESSION_ENCRYPTION_KEY",
    "MAIL_SMTP_PASSWORD",
    "RUSTFS_ACCESS_KEY",
    "RUSTFS_SECRET_KEY",
    "TWENTY_ACCESS_TOKEN_SECRET",
    "TWENTY_INTEGRATION_API_KEY",
    "TWENTY_LOGIN_TOKEN_SECRET",
)
REQUIRED_ENVIRONMENT_KEYS = (
    "CADDY_ACME_EMAIL",
    "LEONAID_ALLOWED_ORIGINS",
    "LEONAID_COMPOSE_PROJECT",
    "LEONAID_CORE_IMAGE",
    "LEONAID_DEPLOYMENT_STAGE",
    "LEONAID_ENV",
    "LEONAID_PUBLIC_BASE_URL",
    "LEONAID_PUBLIC_DOMAIN",
    "LEONAID_PUBLIC_IMAGE",
    "LEONAID_PWA_IMAGE",
    "LEONAID_RELEASE_COMMIT",
    "LEONAID_WEB_IMAGE",
    "MAIL_FROM",
    "MAIL_HEALTH_URL",
    "MAIL_SMTP_HOST",
    "MAIL_SMTP_MODE",
    "RESTIC_REPOSITORY",
    "RUSTFS_BUCKET",
    "TWENTY_PUBLIC_BASE_URL",
    "TWENTY_PUBLIC_DOMAIN",
    *SECRET_KEYS,
)


class DoctorError(RuntimeError):
    """A readiness signal failed without carrying secret material."""


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise DoctorError(f"env_syntax_invalid:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise DoctorError(f"env_key_invalid:{line_number}")
        values[key] = value.strip()
    return values


def forbidden_public_host(host: str) -> bool:
    normalized = host.rstrip(".").casefold()
    reserved_examples = ("example.com", "example.net", "example.org")
    return (
        normalized in {"localhost", "mailpit"}
        or normalized.startswith("127.")
        or normalized.endswith((".invalid", ".test", ".example"))
        or any(
            normalized == candidate or normalized.endswith(f".{candidate}")
            for candidate in reserved_examples
        )
    )


def require_private_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise DoctorError(f"{label}_missing")
    if path.stat().st_mode & 0o077:
        raise DoctorError(f"{label}_permissions_not_0600")


def require_external_path(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    raise DoctorError(f"{label}_inside_repository")


def validate_environment(
    values: dict[str, str],
    *,
    root: Path,
    env_file: Path,
    compose_config: dict[str, Any],
    expected_release_commit: str,
) -> str:
    require_private_file(env_file, "environment_file")
    require_external_path(env_file, root, "environment_file")
    missing = sorted(key for key in REQUIRED_ENVIRONMENT_KEYS if not values.get(key))
    if missing:
        raise DoctorError("environment_keys_missing:" + ",".join(missing))

    if values["LEONAID_ENV"] != "production":
        raise DoctorError("environment_not_production")
    stage = values["LEONAID_DEPLOYMENT_STAGE"]
    if stage not in {"production", "staging"}:
        raise DoctorError("deployment_stage_invalid")
    project = values["LEONAID_COMPOSE_PROJECT"]
    project_match = SAFE_PROJECT.fullmatch(project)
    if project_match is None or project_match.group(1) != stage:
        raise DoctorError("compose_project_stage_mismatch")
    if compose_config.get("name") != project:
        raise DoctorError("compose_project_config_mismatch")

    release_commit = values["LEONAID_RELEASE_COMMIT"]
    if (
        FULL_COMMIT.fullmatch(release_commit) is None
        or release_commit != expected_release_commit
    ):
        raise DoctorError("release_commit_mismatch")

    placeholders = ("__", "changeme", "replace-me", "default-secret")
    secret_values: list[str] = []
    for key in SECRET_KEYS:
        value = values[key]
        if len(value) < 24 or any(
            marker in value.casefold() for marker in placeholders
        ):
            raise DoctorError(f"secret_invalid:{key}")
        secret_values.append(value)
    if len(secret_values) != len(set(secret_values)):
        raise DoctorError("secrets_not_distinct")

    bucket = values["RUSTFS_BUCKET"].casefold()
    if stage not in bucket or "__" in bucket:
        raise DoctorError("bucket_stage_mismatch")
    repository = values["RESTIC_REPOSITORY"]
    if not repository.startswith(REMOTE_BACKUP_PREFIXES):
        raise DoctorError("backup_repository_not_external")

    public_domain = values["LEONAID_PUBLIC_DOMAIN"].rstrip(".").casefold()
    crm_domain = values["TWENTY_PUBLIC_DOMAIN"].rstrip(".").casefold()
    if public_domain == crm_domain:
        raise DoctorError("public_and_crm_domains_not_distinct")
    for key in (
        "LEONAID_PUBLIC_BASE_URL",
        "TWENTY_PUBLIC_BASE_URL",
        "MAIL_HEALTH_URL",
    ):
        parsed = urlparse(values[key])
        if parsed.scheme != "https" or not parsed.hostname:
            raise DoctorError(f"https_url_invalid:{key}")
        if forbidden_public_host(parsed.hostname):
            raise DoctorError(f"public_host_invalid:{key}")
    if forbidden_public_host(values["MAIL_SMTP_HOST"]):
        raise DoctorError("smtp_host_invalid")

    validate(compose_config)
    return project


def parse_resolve(values: list[str]) -> dict[str, tuple[str, int | None]]:
    result: dict[str, tuple[str, int | None]] = {}
    for value in values:
        if "=" not in value:
            raise DoctorError("resolve_mapping_invalid")
        public_host, target = value.split("=", 1)
        public_host = public_host.rstrip(".").casefold()
        if not public_host or not target:
            raise DoctorError("resolve_mapping_invalid")
        target_host = target
        target_port: int | None = None
        if target.count(":") == 1:
            candidate_host, candidate_port = target.rsplit(":", 1)
            if candidate_port.isdigit():
                target_host = candidate_host
                target_port = int(candidate_port)
        if not target_host or target_port is not None and not 1 <= target_port <= 65535:
            raise DoctorError("resolve_mapping_invalid")
        result[public_host] = (target_host, target_port)
    return result


def tls_context(ca_file: Path | None) -> ssl.SSLContext:
    if ca_file is not None and not ca_file.is_file():
        raise DoctorError("tls_ca_file_missing")
    return ssl.create_default_context(cafile=str(ca_file) if ca_file else None)


def probe_https(
    *,
    name: str,
    url: str,
    context: ssl.SSLContext,
    resolve: dict[str, tuple[str, int | None]],
    timeout_seconds: float,
    min_certificate_validity_hours: float,
    required_headers: tuple[str, ...] = (),
) -> tuple[bytes, dt.datetime | None]:
    parsed = urlparse(url)
    public_host = (parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme != "https"
        or not public_host
        or parsed.username
        or parsed.password
    ):
        raise DoctorError(f"https_target_invalid:{name}")
    public_port = parsed.port or 443
    connect_host, override_port = resolve.get(public_host, (public_host, None))
    connect_port = override_port or public_port

    try:
        addresses = socket.getaddrinfo(
            connect_host,
            connect_port,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise DoctorError(f"dns_failed:{name}") from error
    if not addresses:
        raise DoctorError(f"dns_failed:{name}")

    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    try:
        raw_socket = socket.create_connection(
            (connect_host, connect_port),
            timeout=timeout_seconds,
        )
        tls_socket = context.wrap_socket(raw_socket, server_hostname=public_host)
        raw_socket = None
        certificate = tls_socket.getpeercert()
        if certificate is None:
            raise DoctorError(f"tls_certificate_missing:{name}")
        expires_raw = certificate.get("notAfter")
        if not isinstance(expires_raw, str):
            raise DoctorError(f"tls_expiry_missing:{name}")
        expires_at = dt.datetime.fromtimestamp(
            ssl.cert_time_to_seconds(expires_raw),
            tz=dt.timezone.utc,
        )
        remaining = expires_at - dt.datetime.now(dt.timezone.utc)
        if remaining < dt.timedelta(hours=min_certificate_validity_hours):
            raise DoctorError(f"tls_expiring:{name}")

        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        host_header = (
            public_host if public_port == 443 else f"{public_host}:{public_port}"
        )
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "User-Agent: leonaid-pilot-doctor/1\r\n"
            "Accept: application/json,text/html;q=0.8,*/*;q=0.1\r\n"
            "Connection: close\r\n\r\n"
        )
        tls_socket.sendall(request.encode("ascii"))
        response = http.client.HTTPResponse(tls_socket)
        response.begin()
        body = response.read(1_048_577)
        if response.status != 200:
            raise DoctorError(f"http_status_unhealthy:{name}")
        if len(body) > 1_048_576:
            raise DoctorError(f"http_body_too_large:{name}")
        headers = {key.casefold(): value for key, value in response.getheaders()}
        for header in required_headers:
            if not headers.get(header.casefold()):
                raise DoctorError(f"security_header_missing:{name}:{header.casefold()}")
        server_date: dt.datetime | None = None
        if "date" in headers:
            try:
                server_date = parsedate_to_datetime(headers["date"])
            except (TypeError, ValueError) as error:
                raise DoctorError(f"server_date_invalid:{name}") from error
            if server_date.tzinfo is None:
                server_date = server_date.replace(tzinfo=dt.timezone.utc)
        return body, server_date
    except DoctorError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        raise DoctorError(f"tls_or_http_failed:{name}") from error
    finally:
        if tls_socket is not None:
            tls_socket.close()
        if raw_socket is not None:
            raw_socket.close()


def validate_backup(
    path: Path,
    *,
    project: str,
    maximum_age_hours: float,
) -> None:
    if not path.is_file():
        raise DoctorError("backup_manifest_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise DoctorError("backup_manifest_invalid") from error
    if not isinstance(payload, dict):
        raise DoctorError("backup_manifest_invalid")
    if payload.get("schemaVersion") != 1 or payload.get("sourceProject") != project:
        raise DoctorError("backup_manifest_scope_mismatch")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise DoctorError("backup_manifest_inventory_missing")
    created_raw = payload.get("createdAt")
    if not isinstance(created_raw, str):
        raise DoctorError("backup_timestamp_missing")
    try:
        created_at = dt.datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise DoctorError("backup_timestamp_invalid") from error
    if created_at.tzinfo is None:
        raise DoctorError("backup_timestamp_invalid")
    age = dt.datetime.now(dt.timezone.utc) - created_at.astimezone(dt.timezone.utc)
    if age < dt.timedelta(minutes=-5):
        raise DoctorError("backup_timestamp_in_future")
    if age > dt.timedelta(hours=maximum_age_hours):
        raise DoctorError("backup_too_old")


def parse_json_body(body: bytes, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DoctorError(f"json_response_invalid:{name}") from error
    if not isinstance(payload, dict):
        raise DoctorError(f"json_response_invalid:{name}")
    return payload


def report_json(
    *,
    infrastructure_ready: bool,
    gate: str,
    open_ids: list[str],
    stop_ids: list[str],
    deployment_only: bool,
) -> str:
    status = (
        "ready"
        if infrastructure_ready and (deployment_only or not open_ids and not stop_ids)
        else "stop"
        if stop_ids
        else "blocked"
    )
    return json.dumps(
        {
            "checks": {
                "backupAge": "ok" if infrastructure_ready else "blocked",
                "dependencies": "ok" if infrastructure_ready else "blocked",
                "disk": "ok" if infrastructure_ready else "blocked",
                "dns": "ok" if infrastructure_ready else "blocked",
                "environment": "ok" if infrastructure_ready else "blocked",
                "secrets": "ok" if infrastructure_ready else "blocked",
                "time": "ok" if infrastructure_ready else "blocked",
                "tls": "ok" if infrastructure_ready else "blocked",
            },
            "deploymentOnly": deployment_only,
            "gate": gate,
            "openDecisionIds": open_ids,
            "status": status,
            "stopDecisionIds": stop_ids,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Prüft Pilot-Deployment, TLS, Abhängigkeiten, Backup und "
            "Produktentscheidungen fail-closed und ohne Secret-Ausgabe."
        )
    )
    result.add_argument("root", nargs="?", default=".", type=Path)
    result.add_argument("--env-file", required=True, type=Path)
    result.add_argument("--compose-config", required=True, type=Path)
    result.add_argument("--backup-manifest", required=True, type=Path)
    result.add_argument("--expected-release-commit", required=True)
    result.add_argument(
        "--gate",
        choices=(
            "pilot-backup",
            "pilot-deploy",
            "pilot-import",
            "pilot-release",
            "pilot-restore",
        ),
        default="pilot-release",
    )
    result.add_argument("--json", action="store_true")
    result.add_argument(
        "--deployment-only",
        action="store_true",
        help="nur Infrastruktur diagnostizieren; autorisiert keine produktive Aktion",
    )
    result.add_argument("--resolve", action="append", default=[])
    result.add_argument("--ca-file", type=Path)
    result.add_argument("--disk-path", type=Path, default=Path("/"))
    result.add_argument("--minimum-free-bytes", type=int, default=5 * 1024**3)
    result.add_argument("--maximum-backup-age-hours", type=float, default=26)
    result.add_argument("--maximum-clock-skew-seconds", type=float, default=300)
    result.add_argument("--minimum-certificate-validity-hours", type=float, default=336)
    result.add_argument("--timeout-seconds", type=float, default=10)
    return result


def main() -> int:
    arguments = parser().parse_args()
    root = arguments.root.resolve()
    try:
        if arguments.minimum_free_bytes < 1:
            raise DoctorError("minimum_free_bytes_invalid")
        if (
            arguments.maximum_backup_age_hours <= 0
            or arguments.maximum_clock_skew_seconds <= 0
            or arguments.minimum_certificate_validity_hours <= 0
            or arguments.timeout_seconds <= 0
        ):
            raise DoctorError("doctor_threshold_invalid")
        compose_config = json.loads(
            arguments.compose_config.read_text(encoding="utf-8")
        )
        compose_config = object_value(compose_config, "Compose-Konfiguration")
        environment = read_dotenv(arguments.env_file)
        project = validate_environment(
            environment,
            root=root,
            env_file=arguments.env_file,
            compose_config=compose_config,
            expected_release_commit=arguments.expected_release_commit,
        )
        validate_backup(
            arguments.backup_manifest,
            project=project,
            maximum_age_hours=arguments.maximum_backup_age_hours,
        )
        if shutil.disk_usage(arguments.disk_path).free < arguments.minimum_free_bytes:
            raise DoctorError("disk_space_insufficient")

        resolve = parse_resolve(arguments.resolve)
        context = tls_context(arguments.ca_file)
        public_base = environment["LEONAID_PUBLIC_BASE_URL"].rstrip("/")
        crm_base = environment["TWENTY_PUBLIC_BASE_URL"].rstrip("/")
        common_headers = (
            "strict-transport-security",
            "x-content-type-options",
            "referrer-policy",
            "permissions-policy",
        )
        portal_body, _ = probe_https(
            name="portal",
            url=f"{public_base}/admin/",
            context=context,
            resolve=resolve,
            timeout_seconds=arguments.timeout_seconds,
            min_certificate_validity_hours=arguments.minimum_certificate_validity_hours,
            required_headers=(*common_headers, "content-security-policy"),
        )
        if not portal_body:
            raise DoctorError("portal_response_empty")
        api_body, _ = probe_https(
            name="api",
            url=f"{public_base}/api/health/ready",
            context=context,
            resolve=resolve,
            timeout_seconds=arguments.timeout_seconds,
            min_certificate_validity_hours=arguments.minimum_certificate_validity_hours,
            required_headers=common_headers,
        )
        if parse_json_body(api_body, "api").get("status") != "ready":
            raise DoctorError("api_dependency_readiness_failed")
        crm_body, _ = probe_https(
            name="twenty",
            url=f"{crm_base}/healthz",
            context=context,
            resolve=resolve,
            timeout_seconds=arguments.timeout_seconds,
            min_certificate_validity_hours=arguments.minimum_certificate_validity_hours,
            required_headers=common_headers,
        )
        if parse_json_body(crm_body, "twenty").get("status") != "ok":
            raise DoctorError("twenty_readiness_failed")
        mail_body, provider_date = probe_https(
            name="mail-provider",
            url=environment["MAIL_HEALTH_URL"],
            context=context,
            resolve=resolve,
            timeout_seconds=arguments.timeout_seconds,
            min_certificate_validity_hours=arguments.minimum_certificate_validity_hours,
            required_headers=common_headers,
        )
        if not mail_body:
            raise DoctorError("mail_provider_response_empty")
        if provider_date is None:
            raise DoctorError("provider_date_missing")
        skew = abs(
            (
                dt.datetime.now(dt.timezone.utc)
                - provider_date.astimezone(dt.timezone.utc)
            ).total_seconds()
        )
        if skew > arguments.maximum_clock_skew_seconds:
            raise DoctorError("clock_skew_exceeded")

        open_ids: list[str] = []
        stop_ids: list[str] = []
        if not arguments.deployment_only:
            decisions = parse_register(root / "specs/leonaid-pilot/DECISIONS.md")
            validate_register(decisions)
            open_ids, stop_ids = readiness(decisions, arguments.gate)
        if arguments.json:
            print(
                report_json(
                    infrastructure_ready=True,
                    gate=arguments.gate,
                    open_ids=open_ids,
                    stop_ids=stop_ids,
                    deployment_only=arguments.deployment_only,
                )
            )
        elif stop_ids:
            print(
                f"pilot-doctor: STOP ({arguments.gate}): " + ",".join(stop_ids),
                file=sys.stderr,
            )
        elif open_ids:
            print(
                f"pilot-doctor: BLOCKED ({arguments.gate}): " + ",".join(open_ids),
                file=sys.stderr,
            )
        elif arguments.deployment_only:
            print(
                "pilot-deployment-doctor: OK: DNS, TLS, Secrets, Uhrzeit, "
                "Speicher, Backup und Abhängigkeiten"
            )
        else:
            print(
                f"pilot-doctor: OK ({arguments.gate}): "
                "Deployment und Entscheidungen sind freigegeben"
            )
        if stop_ids:
            return 3
        if open_ids:
            return 2
        return 0
    except (
        DecisionError,
        DeploymentContractError,
        DoctorError,
        json.JSONDecodeError,
        OSError,
    ) as error:
        if arguments.json:
            print(
                json.dumps(
                    {
                        "error": str(error),
                        "status": "blocked",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        else:
            print(f"pilot-deployment-doctor: BLOCKED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
