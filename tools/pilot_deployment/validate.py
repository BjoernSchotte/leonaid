"""Fail-closed contract for the merged LeonAid pilot deployment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REQUIRED_SERVICES = {
    "api",
    "core-postgres",
    "core-volume-init",
    "proxy",
    "public",
    "pwa",
    "rustfs",
    "survey-validator",
    "twenty-postgres",
    "twenty-redis",
    "twenty-server",
    "twenty-worker",
    "web",
    "worker",
}
PRIVATE_NETWORKS = {"core-data", "crm-data", "mail-data", "storage-data", "telemetry"}
# The only network with a route out of the host besides the public edge. It
# carries SMTP of the two mail senders and nothing else.
MAIL_EGRESS_NETWORK = "mail-egress"
MAIL_EGRESS_SERVICES = {"twenty-worker", "worker"}
# Twenty 2.24 hands host, port and credentials to nodemailer, which uses
# implicit TLS exactly on port 465 and otherwise upgrades with STARTTLS.
IMPLICIT_TLS_PORT = "465"
TWENTY_MAIL_SERVICES = ("twenty-server", "twenty-worker")
IMAGE_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
LOCAL_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
FULL_COMMIT = re.compile(r"[0-9a-f]{40}$")
# Template placeholders look like __RANDOM_PASSWORD__. Generated and issued
# secrets (URL-safe tokens, the Twenty JWT) may contain "__" by chance, so
# only the template shape and well-known dummy words count as unfilled.
TEMPLATE_PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
PLACEHOLDER_WORDS = ("changeme", "replace-me", "default-secret")


def is_placeholder(value: str) -> bool:
    return TEMPLATE_PLACEHOLDER.search(value) is not None or any(
        word in value.casefold() for word in PLACEHOLDER_WORDS
    )
CORE_RUNTIME_USER = "10001:10001"
HARDENED_SERVICES = {"api", "worker", "web", "pwa", "public", "survey-validator"}


class DeploymentContractError(RuntimeError):
    """The merged topology is unsafe for a pilot deployment."""


def object_value(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeploymentContractError(f"{label} fehlt oder ist kein Objekt")
    return value


def string_value(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise DeploymentContractError(f"{key} fehlt")
    return value


def validate_public_url(value: str, label: str) -> None:
    parsed = urlparse(value)
    host = (parsed.hostname or "").rstrip(".").casefold()
    reserved_examples = ("example.com", "example.net", "example.org")
    if (
        parsed.scheme != "https"
        or not host
        or host == "localhost"
        or host.startswith("127.")
        or host.endswith((".localhost", ".invalid", ".test", ".example"))
        or any(
            host == candidate or host.endswith(f".{candidate}")
            for candidate in reserved_examples
        )
    ):
        raise DeploymentContractError(f"{label} ist keine produktive HTTPS-URL")


def positive_number(value: object) -> bool:
    try:
        return float(str(value)) > 0
    except ValueError:
        return False


def validate_runtime_limits(service_name: str, service: dict[str, Any]) -> None:
    for key in ("mem_limit", "cpus", "pids_limit"):
        if not positive_number(service.get(key)):
            raise DeploymentContractError(f"{service_name} has no {key}")
    logging = service.get("logging")
    if (
        not isinstance(logging, dict)
        or logging.get("driver") != "local"
        or not isinstance(logging.get("options"), dict)
        or "max-size" not in logging["options"]
    ):
        raise DeploymentContractError(f"{service_name} has no log rotation")


def validate_hardened_runtime(service_name: str, service: dict[str, Any]) -> None:
    if (
        service.get("read_only") is not True
        or "ALL" not in service.get("cap_drop", [])
        or service.get("cap_add")
        or "no-new-privileges:true" not in service.get("security_opt", [])
    ):
        raise DeploymentContractError(
            f"{service_name} runs without a read-only root filesystem, "
            "dropped capabilities or no-new-privileges"
        )


def validate(config: dict[str, Any], *, isolated_test_mode: bool = False) -> None:
    project = string_value(config, "name")
    if project == "leonaid" or not project.startswith("leonaid-"):
        raise DeploymentContractError("Compose-Projekt ist nicht umgebungsspezifisch")

    services = object_value(config.get("services"), "services")
    if set(services) != REQUIRED_SERVICES:
        raise DeploymentContractError("aktive Service-Menge weicht vom Pilot-Core ab")

    published: list[tuple[str, int, int]] = []
    published_hosts: list[str] = []
    for service_name, raw_service in services.items():
        service = object_value(raw_service, f"services.{service_name}")
        validate_runtime_limits(service_name, service)
        if "build" in service:
            raise DeploymentContractError(
                f"{service_name} enthält einen produktiven Build"
            )
        image = string_value(service, "image")
        if IMAGE_DIGEST.search(image) is None and not (
            isolated_test_mode and LOCAL_IMAGE_ID.fullmatch(image) is not None
        ):
            raise DeploymentContractError(f"{service_name} ist nicht digest-gepinnt")
        for raw_port in service.get("ports", []):
            port = object_value(raw_port, f"{service_name}.ports")
            published.append(
                (
                    service_name,
                    int(port.get("target", 0)),
                    int(port.get("published", 0)),
                )
            )
            published_hosts.append(str(port.get("host_ip", "")))
        for raw_volume in service.get("volumes", []):
            volume = object_value(raw_volume, f"{service_name}.volumes")
            if volume.get("type") != "bind":
                continue
            source = str(volume.get("source", ""))
            target = str(volume.get("target", ""))
            if (
                service_name != "proxy"
                or not source.endswith(
                    (
                        "/infra/pilot/Caddyfile",
                        "/infra/pilot/Caddyfile.test",
                    )
                    if isolated_test_mode
                    else ("/infra/pilot/Caddyfile",)
                )
                or target != "/etc/caddy/Caddyfile"
                or volume.get("read_only") is not True
            ):
                raise DeploymentContractError(
                    f"{service_name} enthält einen nicht freigegebenen Bind-Mount"
                )

    if isolated_test_mode:
        if (
            sorted((service, target) for service, target, _ in published)
            != [
                ("proxy", 80),
                ("proxy", 443),
            ]
            or any(host_port < 1 for _, _, host_port in published)
            or any(host != "127.0.0.1" for host in published_hosts)
        ):
            raise DeploymentContractError(
                "isolierter Test darf nur Caddys Zielports 80/443 veröffentlichen"
            )
    elif sorted(published) != [("proxy", 80, 80), ("proxy", 443, 443)]:
        raise DeploymentContractError("nur Caddy darf exakt 80/443 veröffentlichen")

    networks = object_value(config.get("networks"), "networks")
    for network_name in PRIVATE_NETWORKS:
        network = object_value(networks.get(network_name), f"networks.{network_name}")
        if network.get("internal") is not True:
            raise DeploymentContractError(f"{network_name} ist nicht intern")

    for service_name in sorted(HARDENED_SERVICES):
        validate_hardened_runtime(service_name, services[service_name])
    for service_name in ("api", "worker"):
        if services[service_name].get("user") != CORE_RUNTIME_USER:
            raise DeploymentContractError(
                f"{service_name} does not run as core user {CORE_RUNTIME_USER}"
            )
    init_command = services["core-volume-init"].get("command")
    if not isinstance(init_command, list) or CORE_RUNTIME_USER not in init_command:
        raise DeploymentContractError(
            "core-volume-init does not hand the volumes to the core user"
        )

    api = object_value(services["api"], "services.api")
    api_environment = object_value(api.get("environment"), "api.environment")
    worker = object_value(services["worker"], "services.worker")
    worker_environment = object_value(
        worker.get("environment"),
        "worker.environment",
    )
    if api_environment.get("LEONAID_ENV") != "production":
        raise DeploymentContractError("API läuft nicht mit LEONAID_ENV=production")
    if worker_environment.get("LEONAID_ENV") != "production":
        raise DeploymentContractError("Worker läuft nicht mit LEONAID_ENV=production")
    if "MAIL_TEST_API_URL" in api_environment:
        raise DeploymentContractError("produktive API enthält eine Mail-Test-API")

    public_url = string_value(api_environment, "LEONAID_PUBLIC_BASE_URL")
    validate_public_url(public_url, "LEONAID_PUBLIC_BASE_URL")
    for origin in string_value(api_environment, "LEONAID_ALLOWED_ORIGINS").split(","):
        validate_public_url(origin.strip(), "LEONAID_ALLOWED_ORIGINS")
    release_commit = string_value(api_environment, "LEONAID_RELEASE_COMMIT")
    if FULL_COMMIT.fullmatch(release_commit) is None:
        raise DeploymentContractError(
            "Release ist nicht an einen vollständigen Commit gebunden"
        )

    bucket = string_value(api_environment, "OBJECT_STORAGE_BUCKET")
    if bucket == "leonaid" or "__" in bucket:
        raise DeploymentContractError(
            "Object-Store-Bucket ist nicht umgebungsspezifisch"
        )
    if worker_environment.get("OBJECT_STORAGE_BUCKET") != bucket:
        raise DeploymentContractError("API und Worker verwenden verschiedene Buckets")

    secret_keys = (
        "LEONAID_SECRET_KEY",
        "LEONAID_SESSION_ENCRYPTION_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    )
    for key in secret_keys:
        value = string_value(api_environment, key)
        if is_placeholder(value) or len(value) < 24:
            raise DeploymentContractError(f"{key} ist ein Placeholder oder zu kurz")
    if (
        api_environment["LEONAID_SECRET_KEY"]
        == api_environment["LEONAID_SESSION_ENCRYPTION_KEY"]
    ):
        raise DeploymentContractError("produktive Anwendungsecrets sind nicht getrennt")

    mail_host = string_value(worker_environment, "MAIL_SMTP_HOST").casefold()
    mail_from = string_value(worker_environment, "MAIL_FROM").casefold()
    mail_envelope_from = string_value(
        worker_environment, "MAIL_ENVELOPE_FROM"
    ).casefold()
    mail_reply_to = string_value(worker_environment, "MAIL_REPLY_TO").casefold()
    if mail_host in {"mailpit", "localhost"} or mail_host.startswith("127."):
        raise DeploymentContractError("produktiver SMTP-Host ist lokal")
    if any(
        ".invalid" in identity
        for identity in (mail_from, mail_envelope_from, mail_reply_to)
    ):
        raise DeploymentContractError("produktive Mailidentität verwendet .invalid")
    if worker_environment.get("MAIL_SMTP_MODE") == "plain":
        raise DeploymentContractError("produktiver SMTP-Transport ist unverschlüsselt")
    if worker_environment.get("MAIL_SMTP_VERIFY_CERTIFICATES") != "true":
        raise DeploymentContractError("produktive SMTP-Zertifikatsprüfung ist aus")
    validate_mail_egress(services, networks)
    validate_twenty_mail(services, worker_environment)


def service_networks(service: dict[str, Any]) -> set[str]:
    networks = service.get("networks") or {}
    return set(networks) if isinstance(networks, (dict, list)) else set()


def validate_mail_egress(services: dict[str, Any], networks: dict[str, Any]) -> None:
    egress = object_value(
        networks.get(MAIL_EGRESS_NETWORK), f"networks.{MAIL_EGRESS_NETWORK}"
    )
    if egress.get("internal") is True:
        raise DeploymentContractError(
            "mail-egress is internal; no SMTP relay is reachable"
        )
    attached = {
        name
        for name, service in services.items()
        if MAIL_EGRESS_NETWORK in service_networks(object_value(service, name))
    }
    if attached != MAIL_EGRESS_SERVICES:
        raise DeploymentContractError(
            "mail-egress must connect exactly worker and twenty-worker, found "
            + ",".join(sorted(attached))
        )


def address_domain(value: str) -> str:
    address = parseaddr(value)[1]
    if address.count("@") != 1:
        return ""
    return address.rsplit("@", 1)[1].rstrip(".").casefold()


def validate_twenty_mail(
    services: dict[str, Any], worker_environment: dict[str, Any]
) -> None:
    """Twenty must send through the core relay with TLS and an aligned sender."""

    mode = worker_environment.get("MAIL_SMTP_MODE")
    port = str(worker_environment.get("MAIL_SMTP_PORT", ""))
    if mode == "tls" and port != IMPLICIT_TLS_PORT:
        raise DeploymentContractError(
            "MAIL_SMTP_MODE=tls needs port 465; Twenty uses implicit TLS only there"
        )
    if mode == "starttls" and port == IMPLICIT_TLS_PORT:
        raise DeploymentContractError(
            "MAIL_SMTP_MODE=starttls cannot use port 465, which Twenty treats as implicit TLS"
        )
    if mode not in {"starttls", "tls"}:
        raise DeploymentContractError("MAIL_SMTP_MODE must be starttls or tls")
    if worker_environment.get("MAIL_SMTP_CA_FILE"):
        raise DeploymentContractError(
            "MAIL_SMTP_CA_FILE is not supported in the pilot; Twenty trusts only public CAs"
        )
    sender_domain = address_domain(string_value(worker_environment, "MAIL_FROM"))
    expected = {
        "EMAIL_DRIVER": "SMTP",
        "EMAIL_SMTP_NO_TLS": "false",
        "EMAIL_SMTP_HOST": string_value(worker_environment, "MAIL_SMTP_HOST"),
        "EMAIL_SMTP_PORT": port,
        "EMAIL_SMTP_USER": str(worker_environment.get("MAIL_SMTP_USERNAME") or ""),
        "EMAIL_SMTP_PASSWORD": str(worker_environment.get("MAIL_SMTP_PASSWORD") or ""),
    }
    for service_name in TWENTY_MAIL_SERVICES:
        service = object_value(services[service_name], f"services.{service_name}")
        environment = object_value(
            service.get("environment"), f"{service_name}.environment"
        )
        for key, value in expected.items():
            if str(environment.get(key) or "") != value:
                # Never echo the value: the password is among the keys.
                raise DeploymentContractError(
                    f"{service_name} {key} differs from the core SMTP relay"
                )
        from_address = str(environment.get("EMAIL_FROM_ADDRESS") or "")
        if (
            not sender_domain
            or ".invalid" in from_address.casefold()
            or address_domain(from_address) != sender_domain
            or parseaddr(from_address)[1] != from_address
        ):
            raise DeploymentContractError(
                f"{service_name} EMAIL_FROM_ADDRESS must be a bare address "
                "in the MAIL_FROM domain"
            )
        if not str(environment.get("EMAIL_FROM_NAME") or "").strip():
            raise DeploymentContractError(f"{service_name} EMAIL_FROM_NAME is missing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        payload = json.loads(arguments.config.read_text(encoding="utf-8"))
        validate(object_value(payload, "Compose-Konfiguration"))
    except (DeploymentContractError, json.JSONDecodeError, OSError) as error:
        print(f"pilot-deployment-contract: BLOCKED: {error}", file=sys.stderr)
        return 1
    print(
        "pilot-deployment-contract: OK: Release-, Port-, Netz-, Mount- und Produktionsgrenzen"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
