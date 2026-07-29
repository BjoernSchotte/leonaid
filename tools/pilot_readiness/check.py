#!/usr/bin/env python3
"""Assess the real pilot contract without turning open gates into approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from tools.pilot_contract.check import (
    ContractError,
    build_report as build_contract_report,
    parse_hard_gates,
    parse_plan,
    parse_traceability,
    validate_dependencies,
)
from tools.pilot_decisions.check import (
    DecisionError,
    parse_register,
    readiness as decision_readiness,
    validate_register,
)

SCHEMA = "leonaid.pilot-readiness/v1"
ProofStatus = Literal["missing", "partial", "complete"]


class ReadinessError(RuntimeError):
    """Raised when readiness cannot be assessed safely."""


def git(root: Path, *arguments: str, required: bool = True) -> str | None:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.resolve()}",
            "-C",
            str(root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if required:
        diagnostic = result.stderr.strip() or "Git-Aufruf fehlgeschlagen"
        raise ReadinessError(diagnostic)
    return None


def repository_state(root: Path) -> dict[str, Any]:
    branch = git(root, "branch", "--show-current") or ""
    head = git(root, "rev-parse", "HEAD") or ""
    origin_main = git(
        root,
        "rev-parse",
        "--verify",
        "refs/remotes/origin/main",
        required=False,
    )
    dirty = git(root, "status", "--porcelain", "--untracked-files=all") or ""
    return {
        "branch": branch,
        "commitSha": head,
        "originMainSha": origin_main,
        "workingTreeClean": not dirty,
        "onMain": branch == "main",
        "remoteSynced": origin_main == head,
    }


def proof_status(root: Path, task_id: str, proof_path: str) -> ProofStatus:
    proof = root / "specs/leonaid-pilot" / proof_path
    if not proof.is_file():
        return "missing"
    text = proof.read_text(encoding="utf-8")
    if f"Task-ID: `{task_id}`" in text and "Status: vollständig bewiesen" in text:
        return "complete"
    return "partial"


def checksum_report(report: dict[str, Any]) -> str:
    canonical = json.dumps(
        report,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def assess(root: Path) -> dict[str, Any]:
    root = root.resolve()
    plan_path = root / "specs/leonaid-pilot/PLAN.md"
    traceability_path = root / "specs/leonaid-pilot/TRACEABILITY.md"
    parsed_tasks = parse_plan(plan_path)
    validate_dependencies(parsed_tasks)
    parsed_gates = parse_hard_gates(plan_path, parsed_tasks)
    contract = build_contract_report(parsed_tasks, parsed_gates)
    traceability = parse_traceability(traceability_path)
    task_by_id = {task["task_id"]: task for task in contract["tasks"]}

    tasks: list[dict[str, Any]] = []
    task_ready: dict[str, bool] = {}
    for task_id in sorted(task_by_id):
        task = task_by_id[task_id]
        trace = traceability[task_id]
        proof = proof_status(root, task_id, trace.proof_path)
        open_criteria = [
            criterion["criterion_id"]
            for criterion in task["criteria"]
            if not criterion["complete"]
        ]
        open_dependencies = [
            dependency
            for dependency in task["dependencies"]
            if not task_by_id[dependency]["complete"]
        ]
        expected_trace_status = "complete" if task["complete"] else "open"
        traceability_matches = trace.status == expected_trace_status
        ready = (
            bool(task["complete"])
            and proof == "complete"
            and not open_criteria
            and not open_dependencies
            and traceability_matches
        )
        task_ready[task_id] = ready
        tasks.append(
            {
                "taskId": task_id,
                "complete": bool(task["complete"]),
                "openDependencyIds": open_dependencies,
                "openCriterionIds": open_criteria,
                "proofPath": trace.proof_path,
                "proofStatus": proof,
                "traceabilityStatus": trace.status,
                "traceabilityMatchesPlan": traceability_matches,
                "ready": ready,
            }
        )

    gates: list[dict[str, Any]] = []
    for gate in contract["hard_gates"]:
        reasons: list[str] = []
        for task_id in gate["tasks"]:
            task = next(item for item in tasks if item["taskId"] == task_id)
            if not task["complete"]:
                reasons.append(f"task_open:{task_id}")
            if task["openCriterionIds"]:
                reasons.append(f"criteria_open:{task_id}")
            if task["openDependencyIds"]:
                reasons.append(f"dependency_open:{task_id}")
            if not task["traceabilityMatchesPlan"]:
                reasons.append(f"traceability_mismatch:{task_id}")
            if task["proofStatus"] == "missing":
                reasons.append(f"proof_missing:{task_id}")
            elif task["proofStatus"] != "complete":
                reasons.append(f"proof_incomplete:{task_id}")
        gates.append(
            {
                "gateId": gate["gate_id"],
                "name": gate["text"],
                "taskIds": list(gate["tasks"]),
                "ready": all(task_ready[task_id] for task_id in gate["tasks"]),
                "reasons": reasons,
            }
        )

    register_path = root / "specs/leonaid-pilot/DECISIONS.md"
    decisions = parse_register(register_path)
    validate_register(decisions)
    open_decisions, stop_decisions = decision_readiness(
        decisions,
        "pilot-release",
    )
    repository = repository_state(root)
    repository_blockers = [
        reason
        for reason, blocked in (
            ("branch_not_main", not repository["onMain"]),
            ("working_tree_dirty", not repository["workingTreeClean"]),
            ("origin_main_missing", repository["originMainSha"] is None),
            ("head_not_origin_main", not repository["remoteSynced"]),
        )
        if blocked
    ]
    blocked_gates = [gate["gateId"] for gate in gates if not gate["ready"]]
    missing_proofs = [
        task["taskId"] for task in tasks if task["proofStatus"] == "missing"
    ]
    incomplete_proofs = [
        task["taskId"] for task in tasks if task["proofStatus"] == "partial"
    ]
    open_tasks = [task["taskId"] for task in tasks if not task["complete"]]
    inconsistent_traceability = [
        task["taskId"] for task in tasks if not task["traceabilityMatchesPlan"]
    ]

    status: Literal["ready", "blocked", "stop"]
    if stop_decisions:
        status = "stop"
    elif (
        blocked_gates
        or open_decisions
        or repository_blockers
        or missing_proofs
        or incomplete_proofs
        or inconsistent_traceability
    ):
        status = "blocked"
    else:
        status = "ready"

    report: dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "scope": "pilot-acceptance-readiness",
        "status": status,
        "repository": repository,
        "summary": {
            "taskCount": len(tasks),
            "openTaskIds": open_tasks,
            "hardGateCount": len(gates),
            "blockedGateIds": blocked_gates,
            "missingProofTaskIds": missing_proofs,
            "incompleteProofTaskIds": incomplete_proofs,
            "traceabilityMismatchTaskIds": inconsistent_traceability,
            "openDecisionIds": open_decisions,
            "stopDecisionIds": stop_decisions,
            "repositoryBlockers": repository_blockers,
        },
        "tasks": tasks,
        "hardGates": gates,
        "nextStep": (
            "STOP-Entscheidungen fachlich neu schneiden; keine Pilotfreigabe erteilen."
            if status == "stop"
            else (
                "Offene Gates, Proofs, Entscheidungen und Repository-Befunde "
                "schließen; danach den Report auf demselben Commit neu erzeugen."
                if status == "blocked"
                else (
                    "Technische Readiness dokumentieren. Die ausdrückliche "
                    "Abnahme der verantwortlichen Rollen bleibt separat erforderlich."
                )
            )
        ),
    }
    report["checksumSha256"] = checksum_report(report)
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def exit_code(status: str) -> int:
    return 0 if status == "ready" else 3 if status == "stop" else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bewertet Tasks, 16 Hard-Gates, Proofs, Entscheidungen und "
            "Repositoryzustand ohne eine fachliche Abnahme zu simulieren."
        )
    )
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    try:
        report = assess(arguments.root)
    except (
        ContractError,
        DecisionError,
        OSError,
        ReadinessError,
    ) as error:
        print(f"pilot-readiness: ERROR: {error}", file=sys.stderr)
        return 1

    if arguments.report is not None:
        write_report(arguments.report.resolve(), report)
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        summary = report["summary"]
        print(
            f"pilot-readiness: {report['status'].upper()}: "
            f"{len(summary['openTaskIds'])} offene Tasks, "
            f"{len(summary['blockedGateIds'])}/"
            f"{summary['hardGateCount']} blockierte Hard-Gates, "
            f"{len(summary['openDecisionIds'])} offene Entscheidungen, "
            f"{len(summary['missingProofTaskIds'])} fehlende Proofs"
        )
        print(f"pilot-readiness: NEXT: {report['nextStep']}")
    return exit_code(str(report["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
