#!/usr/bin/env python3
"""Create and validate sanitized PILOT-050 synthetic rehearsal evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TASK_ID = "PILOT-050"
MODE = "synthetic"
STATUSES = {"passed", "failed"}
EXPECTED_STEPS = (
    "user-admin",
    "crm-import-golden",
    "mail-relay",
    "pilot-deployment",
    "pilot-backup",
    "pilot-alerting",
    "pilot-legal-config",
    "pilot-release",
)
EXPECTED_BROWSERS = ("chromium", "firefox", "webkit")
EXPECTED_EXTERNAL_GATES = (
    "real-mail-provider",
    "public-dns-tls",
    "controlled-private-import",
    "independent-operator-restore",
    "legal-and-tax-approval",
)
COMMIT = re.compile(r"^[0-9a-f]{40}$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ContractError(RuntimeError):
    """A rehearsal evidence contract violation."""


def parse_timestamp(value: str, field: str) -> dt.datetime:
    if not TIMESTAMP.fullmatch(value):
        raise ContractError(f"{field} is not canonical UTC")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )


def validate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContractError("evidence root must be an object")
    expected_keys = {
        "schemaVersion",
        "taskId",
        "mode",
        "status",
        "releaseCommit",
        "startedAt",
        "finishedAt",
        "completedSteps",
        "failedStep",
        "dataset",
        "browsers",
        "realServices",
        "externalGates",
        "productionReadiness",
    }
    if set(payload) != expected_keys:
        raise ContractError("evidence keys drifted")
    if payload["schemaVersion"] != SCHEMA_VERSION:
        raise ContractError("schemaVersion drifted")
    if payload["taskId"] != TASK_ID or payload["mode"] != MODE:
        raise ContractError("task or mode drifted")
    if payload["status"] not in STATUSES:
        raise ContractError("invalid rehearsal status")
    if not isinstance(payload["releaseCommit"], str) or not COMMIT.fullmatch(
        payload["releaseCommit"]
    ):
        raise ContractError("releaseCommit must be a full lowercase git SHA")

    started = parse_timestamp(payload["startedAt"], "startedAt")
    finished = parse_timestamp(payload["finishedAt"], "finishedAt")
    if finished < started:
        raise ContractError("finishedAt precedes startedAt")

    completed = payload["completedSteps"]
    if not isinstance(completed, list) or any(
        not isinstance(step, str) for step in completed
    ):
        raise ContractError("completedSteps must be a string list")
    expected_prefix = list(EXPECTED_STEPS[: len(completed)])
    if completed != expected_prefix:
        raise ContractError("completedSteps are not an exact ordered prefix")

    failed_step = payload["failedStep"]
    if payload["status"] == "passed":
        if completed != list(EXPECTED_STEPS) or failed_step is not None:
            raise ContractError("passed rehearsal is incomplete")
    else:
        next_step = (
            EXPECTED_STEPS[len(completed)]
            if len(completed) < len(EXPECTED_STEPS)
            else None
        )
        if failed_step != next_step:
            raise ContractError("failedStep is not the first incomplete step")

    if payload["dataset"] != "golden-v1":
        raise ContractError("synthetic rehearsal must use golden-v1")
    if payload["browsers"] != list(EXPECTED_BROWSERS):
        raise ContractError("browser matrix drifted")
    if payload["realServices"] is not True:
        raise ContractError("realServices must be true")
    if payload["productionReadiness"] is not False:
        raise ContractError("synthetic evidence must not claim production readiness")

    gates = payload["externalGates"]
    if not isinstance(gates, list) or gates != [
        {"gate": gate, "status": "open"} for gate in EXPECTED_EXTERNAL_GATES
    ]:
        raise ContractError("external gates must remain explicitly open")
    return payload


def write_payload(arguments: argparse.Namespace) -> None:
    completed = [step for step in arguments.completed.split(",") if step]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": TASK_ID,
        "mode": MODE,
        "status": arguments.status,
        "releaseCommit": arguments.release_commit,
        "startedAt": arguments.started_at,
        "finishedAt": arguments.finished_at,
        "completedSteps": completed,
        "failedStep": arguments.failed_step,
        "dataset": "golden-v1",
        "browsers": list(EXPECTED_BROWSERS),
        "realServices": True,
        "externalGates": [
            {"gate": gate, "status": "open"} for gate in EXPECTED_EXTERNAL_GATES
        ],
        "productionReadiness": False,
    }
    validate(payload)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"pilot-rehearsal-evidence: OK: {arguments.output}")


def verify_payload(arguments: argparse.Namespace) -> None:
    payload = json.loads(arguments.input.read_text(encoding="utf-8"))
    validate(payload)
    print(
        "pilot-rehearsal-evidence: OK: sanitized synthetic scope and "
        "external gate boundary verified"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)

    writer = subparsers.add_parser("write")
    writer.add_argument("--output", type=Path, required=True)
    writer.add_argument("--status", choices=sorted(STATUSES), required=True)
    writer.add_argument("--release-commit", required=True)
    writer.add_argument("--started-at", required=True)
    writer.add_argument("--finished-at", required=True)
    writer.add_argument("--completed", default="")
    writer.add_argument("--failed-step")
    writer.set_defaults(func=write_payload)

    verifier = subparsers.add_parser("verify")
    verifier.add_argument("input", type=Path)
    verifier.set_defaults(func=verify_payload)
    return result


def main() -> None:
    arguments = parser().parse_args()
    try:
        arguments.func(arguments)
    except (ContractError, json.JSONDecodeError, OSError) as error:
        parser().exit(70, f"pilot-rehearsal-evidence: BLOCKED: {error}\n")


if __name__ == "__main__":
    main()
