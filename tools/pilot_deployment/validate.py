"""Fail-closed contract for the merged LeonAid pilot deployment."""

from __future__ import annotations

import argparse
import base64
import binascii
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
# Campaign pages and the EmDash editor (specs/multi-domain stage 0), present
# only when the env file enables the emdash profile.
CMS_SERVICE = "campaign-site"
CMS_SECRETS = ("PGPASSWORD", "S3_SECRET_ACCESS_KEY", "EMDASH_ENCRYPTION_KEY")
# Caddyfile per host mode (tools/proxy/caddyfiles.py): one host, or the
# admin host plus the public host (specs/multi-domain stage 1).
CADDYFILES = {
    "single": "/infra/pilot/Caddyfile",
    "split": "/infra/pilot/Caddyfile.split",
    # Admin host plus campaign hosts, no general public host (§6.6).
    "admin-only": "/infra/pilot/Caddyfile.admin-only",
}
# Isolated test projects only: the hand-written test proxy, and the product's
# single-host route table rendered with an internal CA by tools/proxy/
# caddyfiles.py (`--render pilot-single --tls-internal`, pilot install proof).
TEST_CADDYFILES = ("/infra/pilot/Caddyfile.test", "/Caddyfile.pilot-single-test")
# Caddy reads the aliases as site addresses: separated by ", " or spaces.
HOSTNAME = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$"
)
PRIVATE_NETWORKS = {"core-data", "crm-data", "mail-data", "storage-data", "telemetry"}
# The only network with a route out of the host besides the public edge. It
# carries SMTP of the two mail senders and nothing else.
MAIL_EGRESS_NETWORK = "mail-egress"
MAIL_EGRESS_SERVICES = {"twenty-worker", "worker"}
# Twenty 2.54 hands host, port and credentials to nodemailer, which uses
# implicit TLS exactly on port 465 and otherwise upgrades with STARTTLS only
# if the relay offers it. Twenty has no option to require STARTTLS, so it may
# send mail only with MAIL_SMTP_MODE=tls; the entrypoint below selects the
# logger driver (no mail) for every other mode.
IMPLICIT_TLS_PORT = "465"
TWENTY_MAIL_SERVICES = ("twenty-server", "twenty-worker")
TWENTY_MAIL_POLICY_SCRIPT = (
    'if [ "${MAIL_SMTP_MODE}" = tls ]; then EMAIL_DRIVER=SMTP; '
    "else EMAIL_DRIVER=logger; fi\n"
    "export EMAIL_DRIVER\n"
    'exec /app/entrypoint.sh "$@"\n'
)
# The CRM UI is admin-only: twenty-server publishes its port on the host's
# loopback interface for an SSH tunnel and joins no network the proxy uses.
TWENTY_ADMIN_SERVICE = "twenty-server"
TWENTY_ADMIN_TARGET_PORT = 3000
TWENTY_ADMIN_NETWORK = "crm-admin"
TWENTY_ADMIN_NETWORKS = {"crm-data", TWENTY_ADMIN_NETWORK}
LOOPBACK = "127.0.0.1"
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
        raise DeploymentContractError(f"{label} is missing or not an object")
    return value


def string_value(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise DeploymentContractError(f"{key} is missing")
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
        raise DeploymentContractError(f"{label} is not a production HTTPS URL")


# Order of the P-256 group; a VAPID private key is a scalar in [1, n-1].
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def vapid_problem(private_key: str, subject: str) -> str | None:
    """What is wrong with the Web Push settings, or None (ADR-0017).

    Both empty means push is "not configured", which is allowed. With a key
    the subject must be a contact the push services can reach.
    """
    if not private_key:
        return None
    if is_placeholder(private_key):
        return "LEONAID_VAPID_PRIVATE_KEY is a placeholder"
    try:
        scalar = base64.b64decode(
            private_key + "=" * (-len(private_key) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError):
        scalar = b""
    if len(scalar) != 32 or not 1 <= int.from_bytes(scalar, "big") < P256_ORDER:
        return "LEONAID_VAPID_PRIVATE_KEY is no P-256 private key"
    if subject.startswith("mailto:"):
        # The domain of the address must be a public one, like a URL's host.
        address = subject.removeprefix("mailto:")
        local, _, domain = address.rpartition("@")
        well_formed = bool(local and domain) and parseaddr(address)[1] == address
        contact = f"https://{domain}" if well_formed else ""
    else:
        contact = subject
    try:
        validate_public_url(contact, "LEONAID_VAPID_SUBJECT")
    except DeploymentContractError:
        return "LEONAID_VAPID_SUBJECT is no public mailto: or https: contact"
    return None


def validate_push(
    api_environment: dict[str, Any], worker_environment: dict[str, Any]
) -> None:
    """The API publishes the key the worker signs with; both must match."""
    key = str(api_environment.get("LEONAID_VAPID_PRIVATE_KEY") or "")
    subject = str(api_environment.get("LEONAID_VAPID_SUBJECT") or "")
    problem = vapid_problem(key, subject)
    if problem is not None:
        raise DeploymentContractError(problem)
    for name, value in (
        ("LEONAID_VAPID_PRIVATE_KEY", key),
        ("LEONAID_VAPID_SUBJECT", subject if key else ""),
    ):
        if key and str(worker_environment.get(name) or "") != value:
            raise DeploymentContractError(f"API and worker use different {name}")
    if not key and worker_environment.get("LEONAID_VAPID_PRIVATE_KEY"):
        raise DeploymentContractError(
            "API and worker use different LEONAID_VAPID_PRIVATE_KEY"
        )


def positive_number(value: object) -> bool:
    try:
        return float(str(value)) > 0
    except ValueError:
        return False


# Memory budget of the pilot VPS (DOC-P027, "Runtime limits and identity").
# Limits are ceilings, not reservations, but their sum must still fit the host
# so that no single service can push the kernel into a host-wide OOM kill.
PILOT_HOST_MEMORY_MIB = 8192
HOST_RESERVE_MIB = 1536  # operating system, Docker daemon, page cache
# pilot-exporter 128m + prometheus 256m + alertmanager 64m (infra/pilot).
MONITORING_MEMORY_MIB = 448
CORE_MEMORY_BUDGET_MIB = (
    PILOT_HOST_MEMORY_MIB - HOST_RESERVE_MIB - MONITORING_MEMORY_MIB
)
# A pinned V8 heap must leave room for native memory (buffers, code, stacks)
# below the container limit, or the kernel kills Node before V8 throws.
NODE_NATIVE_RESERVE_MIB = 256
MAX_OLD_SPACE = re.compile(r"--max-old-space-size=(\d+)")
MEMORY_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
MEMORY_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*([bkmg]?)b?", re.IGNORECASE)


def memory_mib(value: object) -> float:
    """Compose mem_limit (bytes or a value with b/k/m/g suffix) in MiB."""
    match = MEMORY_VALUE.fullmatch(str(value).strip())
    if match is None:
        raise DeploymentContractError(f"unreadable mem_limit: {value!r}")
    return float(match.group(1)) * MEMORY_UNITS[match.group(2).lower()] / 1024**2


def validate_memory_budget(services: dict[str, Any]) -> None:
    total = 0.0
    for service_name, service in services.items():
        limit = memory_mib(service["mem_limit"])
        total += limit
        environment = service.get("environment")
        node_options = (
            str(environment.get("NODE_OPTIONS", ""))
            if isinstance(environment, dict)
            else ""
        )
        heap = MAX_OLD_SPACE.search(node_options)
        if heap is not None and int(heap.group(1)) + NODE_NATIVE_RESERVE_MIB > limit:
            raise DeploymentContractError(
                f"{service_name}: --max-old-space-size={heap.group(1)} leaves less "
                f"than {NODE_NATIVE_RESERVE_MIB} MiB native memory below mem_limit"
            )
    if total > CORE_MEMORY_BUDGET_MIB:
        raise DeploymentContractError(
            f"memory limits total {total:.0f} MiB and exceed the pilot budget of "
            f"{CORE_MEMORY_BUDGET_MIB} MiB (8 GiB host minus OS reserve and "
            "monitoring)"
        )


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
        raise DeploymentContractError("Compose project is not environment-specific")

    services = object_value(config.get("services"), "services")
    if set(services) - {CMS_SERVICE} != REQUIRED_SERVICES:
        raise DeploymentContractError("active service set differs from the pilot core")

    published: list[tuple[str, int, int]] = []
    published_hosts: list[tuple[str, str]] = []
    for service_name, raw_service in services.items():
        service = object_value(raw_service, f"services.{service_name}")
        validate_runtime_limits(service_name, service)
        if "build" in service:
            raise DeploymentContractError(f"{service_name} contains a production build")
        image = string_value(service, "image")
        if IMAGE_DIGEST.search(image) is None and not (
            isolated_test_mode and LOCAL_IMAGE_ID.fullmatch(image) is not None
        ):
            raise DeploymentContractError(f"{service_name} is not pinned by digest")
        for raw_port in service.get("ports", []):
            port = object_value(raw_port, f"{service_name}.ports")
            published.append(
                (
                    service_name,
                    int(port.get("target", 0)),
                    int(port.get("published", 0)),
                )
            )
            published_hosts.append((service_name, str(port.get("host_ip", ""))))
        for raw_volume in service.get("volumes", []):
            volume = object_value(raw_volume, f"{service_name}.volumes")
            if volume.get("type") != "bind":
                continue
            source = str(volume.get("source", ""))
            target = str(volume.get("target", ""))
            if (
                service_name != "proxy"
                or not source.endswith(
                    (*CADDYFILES.values(), *TEST_CADDYFILES)
                    if isolated_test_mode
                    else tuple(CADDYFILES.values())
                )
                or target != "/etc/caddy/Caddyfile"
                or volume.get("read_only") is not True
            ):
                raise DeploymentContractError(
                    f"{service_name} contains an unapproved bind mount"
                )

    validate_memory_budget(services)

    admin_ports = [
        host_port
        for service, target, host_port in published
        if service == TWENTY_ADMIN_SERVICE and target == TWENTY_ADMIN_TARGET_PORT
    ]
    if len(admin_ports) != 1 or not 1 <= admin_ports[0] <= 65535:
        raise DeploymentContractError(
            "twenty-server must publish port 3000 exactly once for the admin tunnel"
        )
    admin_port = admin_ports[0]
    if any(
        host != LOOPBACK
        for service, host in published_hosts
        if service == TWENTY_ADMIN_SERVICE
    ):
        raise DeploymentContractError(
            "twenty-server may publish its port on 127.0.0.1 only"
        )
    others = [
        (service, target, host_port)
        for service, target, host_port in published
        if (service, target) != (TWENTY_ADMIN_SERVICE, TWENTY_ADMIN_TARGET_PORT)
    ]
    if isolated_test_mode:
        if (
            sorted((service, target) for service, target, _ in others)
            != [("proxy", 80), ("proxy", 443)]
            or any(host_port < 1 for _, _, host_port in others)
            or any(host != LOOPBACK for _, host in published_hosts)
        ):
            raise DeploymentContractError(
                "isolated test may publish only Caddy target ports 80/443"
            )
    elif sorted(others) != [("proxy", 80, 80), ("proxy", 443, 443)]:
        raise DeploymentContractError("only Caddy may publish exactly 80/443")

    networks = object_value(config.get("networks"), "networks")
    for network_name in PRIVATE_NETWORKS:
        network = object_value(networks.get(network_name), f"networks.{network_name}")
        if network.get("internal") is not True:
            raise DeploymentContractError(f"{network_name} is not internal")

    for service_name in sorted(HARDENED_SERVICES):
        validate_hardened_runtime(service_name, services[service_name])
    # Caddy as PID 1 never reaps orphaned exec children (healthcheck helpers);
    # their zombies exhaust pids_limit and abort the Go runtime.
    if services["proxy"].get("init") is not True:
        raise DeploymentContractError(
            "proxy runs without an init process that reaps zombies"
        )
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
        raise DeploymentContractError("API does not run with LEONAID_ENV=production")
    if worker_environment.get("LEONAID_ENV") != "production":
        raise DeploymentContractError("worker does not run with LEONAID_ENV=production")
    if "MAIL_TEST_API_URL" in api_environment:
        raise DeploymentContractError("production API contains a mail test API")

    club_name = string_value(api_environment, "LEONAID_CLUB_NAME")
    if not club_name.strip() or is_placeholder(club_name):
        raise DeploymentContractError("production API has no club name")
    public_url = string_value(api_environment, "LEONAID_PUBLIC_BASE_URL")
    validate_public_url(public_url, "LEONAID_PUBLIC_BASE_URL")
    for origin in string_value(api_environment, "LEONAID_ALLOWED_ORIGINS").split(","):
        validate_public_url(origin.strip(), "LEONAID_ALLOWED_ORIGINS")
    release_commit = string_value(api_environment, "LEONAID_RELEASE_COMMIT")
    if FULL_COMMIT.fullmatch(release_commit) is None:
        raise DeploymentContractError("release is not bound to a full commit")

    bucket = string_value(api_environment, "OBJECT_STORAGE_BUCKET")
    if bucket == "leonaid" or "__" in bucket:
        raise DeploymentContractError(
            "object storage bucket is not environment-specific"
        )
    if worker_environment.get("OBJECT_STORAGE_BUCKET") != bucket:
        raise DeploymentContractError("API and worker use different buckets")
    # The worker builds the legal links of the delivery-day mail itself; they
    # must point to the same hosts as the links the API writes into jobs.
    for key in ("LEONAID_PUBLIC_BASE_URL", "LEONAID_SITE_BASE_URL"):
        if str(worker_environment.get(key) or "") != str(
            api_environment.get(key) or ""
        ):
            raise DeploymentContractError(f"API and worker use different {key}")

    secret_keys = (
        "LEONAID_SECRET_KEY",
        "LEONAID_SESSION_ENCRYPTION_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    )
    for key in secret_keys:
        value = string_value(api_environment, key)
        if is_placeholder(value) or len(value) < 24:
            raise DeploymentContractError(f"{key} is a placeholder or too short")
    if (
        api_environment["LEONAID_SECRET_KEY"]
        == api_environment["LEONAID_SESSION_ENCRYPTION_KEY"]
    ):
        raise DeploymentContractError("production application secrets are not distinct")

    mail_host = string_value(worker_environment, "MAIL_SMTP_HOST").casefold()
    mail_from = string_value(worker_environment, "MAIL_FROM").casefold()
    mail_envelope_from = string_value(
        worker_environment, "MAIL_ENVELOPE_FROM"
    ).casefold()
    mail_reply_to = string_value(worker_environment, "MAIL_REPLY_TO").casefold()
    if mail_host in {"mailpit", "localhost"} or mail_host.startswith("127."):
        raise DeploymentContractError("production SMTP host is local")
    if any(
        ".invalid" in identity
        for identity in (mail_from, mail_envelope_from, mail_reply_to)
    ):
        raise DeploymentContractError("production mail identity uses .invalid")
    if worker_environment.get("MAIL_SMTP_MODE") == "plain":
        raise DeploymentContractError("production SMTP transport is unencrypted")
    if worker_environment.get("MAIL_SMTP_VERIFY_CERTIFICATES") != "true":
        raise DeploymentContractError("production SMTP certificate verification is off")
    validate_mail_egress(services, networks)
    validate_twenty_admin_access(services, networks, api_environment, admin_port)
    validate_twenty_mail(services, worker_environment)
    validate_push(api_environment, worker_environment)
    validate_hosts(services, api_environment, isolated_test_mode=isolated_test_mode)
    if CMS_SERVICE in services:
        validate_cms(services, api_environment)


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}".casefold()


def split_hosts(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item for item in re.split(r"[,\s]+", value.strip().casefold()) if item]


def valid_hostname(value: str, label: str) -> None:
    if HOSTNAME.fullmatch(value) is None:
        raise DeploymentContractError(f"{label} is not a host name: {value!r}")
    validate_public_url(f"https://{value}/", label)


def mounted_caddyfile(proxy: dict[str, Any]) -> str:
    for raw_volume in proxy.get("volumes", []):
        volume = object_value(raw_volume, "proxy.volumes")
        if volume.get("target") == "/etc/caddy/Caddyfile":
            return str(volume.get("source", ""))
    raise DeploymentContractError("proxy mounts no Caddyfile")


def validate_hosts(
    services: dict[str, Any],
    api_environment: dict[str, Any],
    *,
    isolated_test_mode: bool = False,
) -> None:
    """One host, or admin host plus public host (specs/multi-domain §6.1)."""

    proxy = object_value(services["proxy"], "services.proxy")
    proxy_environment = object_value(proxy.get("environment"), "proxy.environment")
    caddyfile = mounted_caddyfile(proxy)
    public_domain = str(proxy_environment.get("LEONAID_PUBLIC_DOMAIN") or "").casefold()
    admin_domain = str(proxy_environment.get("LEONAID_ADMIN_DOMAIN") or "").casefold()
    raw_aliases = str(proxy_environment.get("LEONAID_PUBLIC_DOMAIN_ALIASES") or "")
    aliases = split_hosts(raw_aliases)
    public_origins = split_hosts(api_environment.get("LEONAID_PUBLIC_ORIGINS"))
    site_base = str(api_environment.get("LEONAID_SITE_BASE_URL") or "")
    admin_base = string_value(api_environment, "LEONAID_PUBLIC_BASE_URL")
    allowed = split_hosts(api_environment.get("LEONAID_ALLOWED_ORIGINS"))
    if caddyfile.endswith(CADDYFILES["admin-only"]):
        validate_admin_only(
            services,
            api_environment,
            public_domain=public_domain,
            admin_domain=admin_domain,
            aliases=aliases,
            public_origins=public_origins,
            site_base=site_base,
            admin_base=admin_base,
            allowed=allowed,
        )
        return
    if str(api_environment.get("LEONAID_PUBLIC_HOST_ENABLED", "true")).casefold() != (
        "true"
    ):
        raise DeploymentContractError(
            "LEONAID_PUBLIC_HOST_ENABLED=false needs Caddyfile.admin-only"
        )
    valid_hostname(public_domain, "LEONAID_PUBLIC_DOMAIN")
    if not admin_domain:
        if not (
            caddyfile.endswith(CADDYFILES["single"])
            or isolated_test_mode
            and caddyfile.endswith(TEST_CADDYFILES)
        ):
            raise DeploymentContractError(
                "one host needs infra/pilot/Caddyfile (LEONAID_PROXY_CADDYFILE unset)"
            )
        if aliases or public_origins or site_base:
            raise DeploymentContractError(
                "public host aliases, public origins and a site base URL need "
                "LEONAID_ADMIN_DOMAIN"
            )
        return
    valid_hostname(admin_domain, "LEONAID_ADMIN_DOMAIN")
    if not caddyfile.endswith(CADDYFILES["split"]):
        raise DeploymentContractError(
            "an admin host needs LEONAID_PROXY_CADDYFILE=Caddyfile.split"
        )
    for alias in aliases:
        valid_hostname(alias, "LEONAID_PUBLIC_DOMAIN_ALIASES")
    if re.search(r",(?! )", raw_aliases):
        raise DeploymentContractError(
            "LEONAID_PUBLIC_DOMAIN_ALIASES must separate names with ', ' (Caddy)"
        )
    if admin_domain == public_domain or admin_domain in aliases:
        raise DeploymentContractError(
            "the admin host must differ from the public host and its aliases"
        )
    if public_domain in aliases or len(set(aliases)) != len(aliases):
        raise DeploymentContractError("public host aliases repeat a host")
    admin_origin = f"https://{admin_domain}"
    public_origin = f"https://{public_domain}"
    if origin_of(admin_base) != admin_origin:
        raise DeploymentContractError(
            "LEONAID_PUBLIC_BASE_URL must be the admin host origin"
        )
    if origin_of(site_base) != public_origin:
        raise DeploymentContractError("LEONAID_SITE_BASE_URL must be the public host")
    # Sessions and credentialed CORS stay on the admin origin (G6).
    if allowed != [admin_origin]:
        raise DeploymentContractError(
            "LEONAID_ALLOWED_ORIGINS must be exactly the admin origin"
        )
    # Aliases redirect every path at the edge, so no page runs on them; only
    # the public host itself calls the public API.
    if public_origins != [public_origin]:
        raise DeploymentContractError(
            "LEONAID_PUBLIC_ORIGINS must be exactly the public host origin"
        )
    public = object_value(services["public"], "services.public")
    public_environment = object_value(public.get("environment"), "public.environment")
    if (
        str(public_environment.get("LEONAID_ADMIN_DOMAIN") or "").casefold()
        != admin_domain
        or str(public_environment.get("LEONAID_PUBLIC_DOMAIN") or "").casefold()
        != public_domain
    ):
        raise DeploymentContractError("public app hosts differ from the proxy hosts")


# Released after the EmDash admin-only proof passed in CI (now the second
# round of case campaign-hosts; run 42417644446, #109). Kept as a switch so the
# contract test can prove the refusal path.
ADMIN_ONLY_RELEASED = True


def validate_admin_only(
    services: dict[str, Any],
    api_environment: dict[str, Any],
    *,
    public_domain: str,
    admin_domain: str,
    aliases: list[str],
    public_origins: list[str],
    site_base: str,
    admin_base: str,
    allowed: list[str],
) -> None:
    """Admin host plus campaign hosts, no general public host (§6.6)."""

    if not ADMIN_ONLY_RELEASED:
        raise DeploymentContractError(
            "Caddyfile.admin-only (no public host) is not released yet: its "
            "stack proof (test-emdash-spike --case campaign-hosts, admin-only round) "
            "must pass in CI first"
        )
    if public_domain or aliases or public_origins:
        raise DeploymentContractError(
            "without a public host LEONAID_PUBLIC_DOMAIN, its aliases and "
            "LEONAID_PUBLIC_ORIGINS stay empty"
        )
    valid_hostname(admin_domain, "LEONAID_ADMIN_DOMAIN")
    admin_origin = f"https://{admin_domain}"
    if origin_of(admin_base) != admin_origin:
        raise DeploymentContractError(
            "LEONAID_PUBLIC_BASE_URL must be the admin host origin"
        )
    # Survey links and legal pages stay on the admin host (§6.6).
    if site_base and origin_of(site_base) != admin_origin:
        raise DeploymentContractError(
            "without a public host LEONAID_SITE_BASE_URL is the admin host"
        )
    if allowed != [admin_origin]:
        raise DeploymentContractError(
            "LEONAID_ALLOWED_ORIGINS must be exactly the admin origin"
        )
    if str(api_environment.get("LEONAID_PUBLIC_HOST_ENABLED") or "").casefold() != (
        "false"
    ):
        raise DeploymentContractError(
            "Caddyfile.admin-only needs LEONAID_PUBLIC_HOST_ENABLED=false"
        )
    public = object_value(services["public"], "services.public")
    public_environment = object_value(public.get("environment"), "public.environment")
    if str(
        public_environment.get("LEONAID_ADMIN_DOMAIN") or ""
    ).casefold() != admin_domain or str(
        public_environment.get("LEONAID_PUBLIC_DOMAIN") or ""
    ):
        raise DeploymentContractError("public app hosts differ from the proxy hosts")
    cms = services.get(CMS_SERVICE)
    if cms is not None:
        cms_environment = object_value(
            object_value(cms, CMS_SERVICE).get("environment"),
            "campaign-site.environment",
        )
        if str(cms_environment.get("LEONAID_PUBLIC_HOST_ENABLED") or "").casefold() != (
            "false"
        ):
            raise DeploymentContractError(
                "without a public host the campaign site needs "
                "LEONAID_PUBLIC_HOST_ENABLED=false"
            )


def validate_cms(services: dict[str, Any], api_environment: dict[str, Any]) -> None:
    """Campaign site in production (specs/multi-domain stage 0)."""

    cms = object_value(services[CMS_SERVICE], f"services.{CMS_SERVICE}")
    if cms.get("ports"):
        raise DeploymentContractError("campaign-site may not publish a port")
    environment = object_value(cms.get("environment"), "campaign-site.environment")
    site_url = string_value(environment, "EMDASH_SITE_URL")
    validate_public_url(site_url, "EMDASH_SITE_URL")
    # The editor and its sign-in links belong to the admin origin.
    if origin_of(site_url) != origin_of(
        string_value(api_environment, "LEONAID_PUBLIC_BASE_URL")
    ):
        raise DeploymentContractError("EMDASH_SITE_URL must be the admin origin")
    if str(environment.get("LEONAID_SITE_BASE_URL") or "") != str(
        api_environment.get("LEONAID_SITE_BASE_URL") or ""
    ):
        raise DeploymentContractError(
            "campaign-site and api use different public base URLs"
        )
    for key in CMS_SECRETS:
        value = str(environment.get(key) or "")
        if is_placeholder(value) or len(value) < 24:
            raise DeploymentContractError(
                f"campaign-site {key} is a placeholder or too short"
            )
    if environment.get("LEONAID_ORDER_SUBMISSION_KEY") != api_environment.get(
        "LEONAID_ORDER_SUBMISSION_KEY"
    ):
        raise DeploymentContractError(
            "campaign-site and api use different order submission keys"
        )


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


def validate_twenty_admin_access(
    services: dict[str, Any],
    networks: dict[str, Any],
    api_environment: dict[str, Any],
    admin_port: int,
) -> None:
    """Twenty is reachable only through the loopback port and its tunnel URL."""

    admin_network = object_value(
        networks.get(TWENTY_ADMIN_NETWORK), f"networks.{TWENTY_ADMIN_NETWORK}"
    )
    # Docker publishes no port of a container that is only on internal networks.
    if admin_network.get("internal") is True:
        raise DeploymentContractError(
            "crm-admin is internal; the admin port of twenty-server cannot be published"
        )
    attached = {
        name
        for name, service in services.items()
        if TWENTY_ADMIN_NETWORK in service_networks(object_value(service, name))
    }
    if attached != {TWENTY_ADMIN_SERVICE}:
        raise DeploymentContractError(
            "crm-admin must connect only twenty-server, found "
            + ",".join(sorted(attached))
        )
    server_networks = service_networks(
        object_value(services[TWENTY_ADMIN_SERVICE], TWENTY_ADMIN_SERVICE)
    )
    if server_networks != TWENTY_ADMIN_NETWORKS:
        raise DeploymentContractError(
            "twenty-server must join exactly crm-data and crm-admin, found "
            + ",".join(sorted(server_networks))
        )
    tunnel_url = f"http://localhost:{admin_port}"
    for service_name in TWENTY_MAIL_SERVICES:
        environment = object_value(
            object_value(services[service_name], service_name).get("environment"),
            f"{service_name}.environment",
        )
        for key in ("SERVER_URL", "AUTH_COOKIE_ALLOWED_ORIGINS"):
            if environment.get(key) != tunnel_url:
                raise DeploymentContractError(
                    f"{service_name} {key} must be the admin tunnel URL {tunnel_url}"
                )
    if api_environment.get("TWENTY_ORIGIN") != tunnel_url:
        raise DeploymentContractError(
            f"api TWENTY_ORIGIN must be the admin tunnel URL {tunnel_url}"
        )


def twenty_mail_enabled(mode: object) -> bool:
    """Whether the mail policy lets Twenty send mail (implicit TLS only)."""

    return mode == "tls"


def unescape_compose(value: object) -> object:
    # `docker compose config` keeps "$$" escaped; the container sees "$".
    return value.replace("$$", "$") if isinstance(value, str) else value


def address_domain(value: str) -> str:
    address = parseaddr(value)[1]
    if address.count("@") != 1:
        return ""
    return address.rsplit("@", 1)[1].rstrip(".").casefold()


def validate_twenty_mail(
    services: dict[str, Any], worker_environment: dict[str, Any]
) -> None:
    """Twenty sends only through the core relay, only with implicit TLS and an
    aligned sender; its entrypoint picks the logger driver for other modes."""

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
    expected_entrypoint = [
        "/bin/sh",
        "-c",
        TWENTY_MAIL_POLICY_SCRIPT,
        "twenty-mail-policy",
    ]
    expected = {
        "MAIL_SMTP_MODE": str(mode),
        "EMAIL_SMTP_NO_TLS": "false",
        "EMAIL_SMTP_HOST": string_value(worker_environment, "MAIL_SMTP_HOST"),
        "EMAIL_SMTP_PORT": port,
        "EMAIL_SMTP_USER": str(worker_environment.get("MAIL_SMTP_USERNAME") or ""),
        "EMAIL_SMTP_PASSWORD": str(worker_environment.get("MAIL_SMTP_PASSWORD") or ""),
    }
    for service_name in TWENTY_MAIL_SERVICES:
        service = object_value(services[service_name], f"services.{service_name}")
        entrypoint = service.get("entrypoint")
        if (
            not isinstance(entrypoint, list)
            or [unescape_compose(item) for item in entrypoint] != expected_entrypoint
        ):
            raise DeploymentContractError(
                f"{service_name} does not start through the Twenty mail policy"
            )
        environment = object_value(
            service.get("environment"), f"{service_name}.environment"
        )
        if "EMAIL_DRIVER" in environment:
            raise DeploymentContractError(
                f"{service_name} sets EMAIL_DRIVER; only the mail policy may choose it"
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
        validate(object_value(payload, "Compose configuration"))
    except (DeploymentContractError, json.JSONDecodeError, OSError) as error:
        print(f"pilot-deployment-contract: BLOCKED: {error}", file=sys.stderr)
        return 1
    print(
        "pilot-deployment-contract: OK: release, port, network, mount and production boundaries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
