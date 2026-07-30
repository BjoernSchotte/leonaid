#!/usr/bin/env python3
"""Positive and drift tests for the real LeonAid pilot plan contract."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run_checker(
    checker: Path,
    fixture_root: Path,
    expected_error: str | None = None,
    report: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(checker), str(fixture_root)]
    if report is not None:
        command.extend(["--report", str(report)])
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    output = result.stdout + result.stderr
    if expected_error is None:
        if result.returncode != 0:
            raise AssertionError(f"valid pilot contract failed:\n{output}")
    elif result.returncode == 0 or expected_error not in output:
        raise AssertionError(
            f"expected error {expected_error!r} was not proven:\n{output}"
        )
    return result


def copy_fixture(root: Path, target: Path) -> None:
    source = root / "specs/leonaid-pilot"
    destination = target / "specs/leonaid-pilot"
    destination.parent.mkdir(parents=True)
    shutil.copytree(source, destination)


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise AssertionError(f"fixture mutation is no longer unique: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    checker = root / "tools/pilot_contract/check.py"

    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        report = workspace / "pilot-contract.json"
        result = run_checker(checker, root, report=report)
        if "pilot-contract: OK" not in result.stdout:
            raise AssertionError("positive contract did not emit its stable OK marker")
        payload = json.loads(report.read_text(encoding="utf-8"))
        criterion_ids = [
            criterion["criterion_id"]
            for task in payload["tasks"]
            for criterion in task["criteria"]
        ]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise AssertionError("criterion IDs are not globally unique")
        if len(payload["tasks"]) != 21 or len(payload["hard_gates"]) != 16:
            raise AssertionError("pilot contract baseline count drifted")

        decision_intake = (root / "specs/leonaid-pilot/DECISION-INTAKE.md").read_text(
            encoding="utf-8"
        )
        doctor_examples = decision_intake.split("./leonaid pilot-doctor")[1:]
        if len(doctor_examples) != 4:
            raise AssertionError(
                "decision intake must contain four pilot-doctor examples"
            )
        for example in doctor_examples:
            command = example.split("./leonaid pilot-doctor", 1)[0]
            required_arguments = ("--env-file", "--backup-manifest", "--gate")
            if not all(argument in command for argument in required_arguments):
                raise AssertionError(
                    "every pilot-doctor example must pass private environment, "
                    "backup manifest and gate"
                )

        missing_proof = workspace / "missing-proof"
        copy_fixture(root, missing_proof)
        traceability = missing_proof / "specs/leonaid-pilot/TRACEABILITY.md"
        traceability_text = traceability.read_text(encoding="utf-8")
        traceability_text, replacements = re.subn(
            r"(\| PILOT-000 \| (?:open|complete) \| )"
            r"\[PILOT-000\]\(proofs/PILOT-000\.md\)( \|)",
            r"\1–\2",
            traceability_text,
            count=1,
        )
        if replacements != 1:
            raise AssertionError("PILOT-000 proof-link fixture could not be mutated")
        traceability.write_text(traceability_text, encoding="utf-8")
        run_checker(checker, missing_proof, "proof link missing or malformed")

        orphan = workspace / "orphan"
        copy_fixture(root, orphan)
        plan = orphan / "specs/leonaid-pilot/PLAN.md"
        replace_once(
            plan,
            "## 1. Ziel des Pilot-Milestones",
            "- [ ] Verwaistes Kriterium ohne Pilot-Task\n\n"
            "## 1. Ziel des Pilot-Milestones",
        )
        run_checker(checker, orphan, "orphan criterion outside a task")

        unknown_dependency = workspace / "unknown-dependency"
        copy_fixture(root, unknown_dependency)
        plan = unknown_dependency / "specs/leonaid-pilot/PLAN.md"
        replace_once(
            plan,
            "Abhängigkeiten: PILOT-000\n\nIn Scope:\n\n"
            "- `specs/leonaid-pilot/DECISIONS.md`",
            "Abhängigkeiten: PILOT-999\n\nIn Scope:\n\n"
            "- `specs/leonaid-pilot/DECISIONS.md`",
        )
        run_checker(
            checker,
            unknown_dependency,
            "unknown dependency PILOT-999 referenced by PILOT-001",
        )

        premature = workspace / "premature"
        copy_fixture(root, premature)
        plan = premature / "specs/leonaid-pilot/PLAN.md"
        replace_once(
            plan,
            "- [x] Jeder Pilot-Task, jedes Akzeptanzkriterium und jeder harte Gate besitzt",
            "- [ ] Jeder Pilot-Task, jedes Akzeptanzkriterium und jeder harte Gate besitzt",
        )
        run_checker(checker, premature, "prematurely completed task PILOT-000")

    print("pilot-contract-test: OK: positive plan and four contract-drift cases passed")


if __name__ == "__main__":
    main()
