"""Negative mutation tests over a real Docker Compose production config."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from tools.pilot_deployment.validate import DeploymentContractError, validate


def rejected(config: dict[str, Any], label: str) -> None:
    try:
        validate(config)
    except DeploymentContractError:
        return
    raise AssertionError(f"unsafe deployment mutation was allowed: {label}")


def main() -> None:
    path = Path(sys.argv[1])
    config = json.loads(path.read_text(encoding="utf-8"))
    validate(config)

    mutations: list[tuple[str, dict[str, Any]]] = []

    changed = copy.deepcopy(config)
    changed["services"]["proxy"]["build"] = {"context": "../proxy/image"}
    mutations.append(("proxy live build", changed))

    changed = copy.deepcopy(config)
    changed["services"]["proxy"]["image"] = "registry.example.org/leonaid/proxy:latest"
    mutations.append(("unpinned proxy image", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["ports"] = [
        {"target": 8000, "published": "8000", "protocol": "tcp"}
    ]
    mutations.append(("internal host port", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["build"] = {"context": "."}
    mutations.append(("live build", changed))

    changed = copy.deepcopy(config)
    changed["services"]["web"]["image"] = "registry.example.org/leonaid/web:latest"
    mutations.append(("unpinned image", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["environment"]["LEONAID_PUBLIC_BASE_URL"] = (
        "http://127.0.0.1:8080"
    )
    mutations.append(("loopback public URL", changed))

    changed = copy.deepcopy(config)
    changed["services"]["worker"]["environment"]["MAIL_SMTP_HOST"] = "mailpit"
    mutations.append(("Mailpit", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["environment"]["LEONAID_SECRET_KEY"] = (
        "__DEFAULT_SECRET__"
    )
    mutations.append(("default secret", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["volumes"].append(
        {
            "type": "bind",
            "source": "/workspace/src",
            "target": "/workspace/src",
            "read_only": True,
        }
    )
    mutations.append(("live code mount", changed))

    changed = copy.deepcopy(config)
    changed["networks"]["mail-egress"]["internal"] = True
    mutations.append(("internal mail egress", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["networks"]["mail-egress"] = None
    mutations.append(("API on the mail egress", changed))

    changed = copy.deepcopy(config)
    del changed["services"]["twenty-worker"]["networks"]["mail-egress"]
    mutations.append(("twenty-worker without egress", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-worker"]["environment"]["EMAIL_DRIVER"] = "SMTP"
    mutations.append(("Twenty mail driver outside the mail policy", changed))

    changed = copy.deepcopy(config)
    del changed["services"]["twenty-server"]["entrypoint"]
    mutations.append(("Twenty server without the mail policy", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-worker"]["entrypoint"][2] = changed["services"][
        "twenty-worker"
    ]["entrypoint"][2].replace("EMAIL_DRIVER=logger", "EMAIL_DRIVER=SMTP")
    mutations.append(("Twenty mail over STARTTLS", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-worker"]["environment"]["MAIL_SMTP_MODE"] = "tls"
    mutations.append(("Twenty mail mode differs from the core worker", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-server"]["ports"][0]["host_ip"] = "0.0.0.0"
    mutations.append(("Twenty admin port on all interfaces", changed))

    changed = copy.deepcopy(config)
    del changed["services"]["twenty-server"]["ports"]
    mutations.append(("Twenty without admin port", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-server"]["networks"]["edge"] = None
    mutations.append(("Twenty on the proxy edge network", changed))

    changed = copy.deepcopy(config)
    changed["services"]["proxy"]["networks"]["crm-admin"] = None
    mutations.append(("proxy on the CRM admin network", changed))

    changed = copy.deepcopy(config)
    changed["networks"]["crm-admin"]["internal"] = True
    mutations.append(("internal CRM admin network", changed))

    changed = copy.deepcopy(config)
    for service in ("twenty-server", "twenty-worker"):
        changed["services"][service]["environment"]["SERVER_URL"] = (
            "https://crm.leonaid.org"
        )
    mutations.append(("public Twenty SERVER_URL", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-server"]["environment"][
        "AUTH_COOKIE_ALLOWED_ORIGINS"
    ] = "http://localhost:3020,https://evil.leonaid.org"
    mutations.append(("extra Twenty credentialed origin", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["environment"]["TWENTY_ORIGIN"] = (
        "https://crm.leonaid.org"
    )
    mutations.append(("API Origin outside the admin tunnel", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-server"]["environment"]["EMAIL_SMTP_NO_TLS"] = "true"
    mutations.append(("Twenty without TLS", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-worker"]["environment"]["EMAIL_SMTP_HOST"] = (
        "other-relay.leonaid.org"
    )
    mutations.append(("Twenty on another relay", changed))

    changed = copy.deepcopy(config)
    changed["services"]["twenty-worker"]["environment"]["EMAIL_FROM_ADDRESS"] = (
        "crm@unaligned.leonaid.net"
    )
    mutations.append(("unaligned Twenty sender", changed))

    changed = copy.deepcopy(config)
    for service in ("worker", "twenty-server", "twenty-worker"):
        changed["services"][service]["environment"]["MAIL_SMTP_MODE"] = "tls"
    mutations.append(("implicit TLS on a STARTTLS port", changed))

    changed = copy.deepcopy(config)
    for service in ("worker", "twenty-server", "twenty-worker"):
        key = "MAIL_SMTP_PORT" if service == "worker" else "EMAIL_SMTP_PORT"
        changed["services"][service]["environment"][key] = "465"
    mutations.append(("STARTTLS on the implicit TLS port", changed))

    changed = copy.deepcopy(config)
    changed["services"]["worker"]["environment"]["MAIL_SMTP_CA_FILE"] = (
        "/run/secrets/smtp-ca.pem"
    )
    mutations.append(("private SMTP CA", changed))

    changed = copy.deepcopy(config)
    del changed["services"]["twenty-server"]["mem_limit"]
    mutations.append(("missing memory limit", changed))

    changed = copy.deepcopy(config)
    del changed["services"]["rustfs"]["logging"]
    mutations.append(("missing log rotation", changed))

    changed = copy.deepcopy(config)
    changed["services"]["worker"]["user"] = "0:0"
    mutations.append(("root core worker", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["read_only"] = False
    mutations.append(("writable core root filesystem", changed))

    changed = copy.deepcopy(config)
    changed["services"]["core-volume-init"]["command"] = [
        "chown",
        "-R",
        "0:0",
        "/recovery/survey-erasure",
    ]
    mutations.append(("volume handover to root", changed))

    for label, mutation in mutations:
        rejected(mutation, label)

    print(
        f"pilot-deployment-contract-test: OK: {len(mutations)} real Compose "
        "mutations rejected fail-closed"
    )


if __name__ == "__main__":
    main()
