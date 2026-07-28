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
    raise AssertionError(f"unsichere Deployment-Mutation wurde erlaubt: {label}")


def main() -> None:
    path = Path(sys.argv[1])
    config = json.loads(path.read_text(encoding="utf-8"))
    validate(config)

    mutations: list[tuple[str, dict[str, Any]]] = []

    changed = copy.deepcopy(config)
    changed["services"]["api"]["ports"] = [
        {"target": 8000, "published": "8000", "protocol": "tcp"}
    ]
    mutations.append(("interner Hostport", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["build"] = {"context": "."}
    mutations.append(("Live-Build", changed))

    changed = copy.deepcopy(config)
    changed["services"]["web"]["image"] = "registry.example.org/leonaid/web:latest"
    mutations.append(("ungepinntes Image", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["environment"]["LEONAID_PUBLIC_BASE_URL"] = (
        "http://127.0.0.1:8080"
    )
    mutations.append(("Loopback-Public-URL", changed))

    changed = copy.deepcopy(config)
    changed["services"]["worker"]["environment"]["MAIL_SMTP_HOST"] = "mailpit"
    mutations.append(("Mailpit", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["environment"]["LEONAID_SECRET_KEY"] = (
        "__DEFAULT_SECRET__"
    )
    mutations.append(("Default-Secret", changed))

    changed = copy.deepcopy(config)
    changed["services"]["api"]["volumes"].append(
        {
            "type": "bind",
            "source": "/workspace/src",
            "target": "/workspace/src",
            "read_only": True,
        }
    )
    mutations.append(("Live-Code-Mount", changed))

    for label, mutation in mutations:
        rejected(mutation, label)

    print(
        "pilot-deployment-contract-test: OK: sieben reale Compose-Mutationen "
        "fail-closed abgewiesen"
    )


if __name__ == "__main__":
    main()
