#!/usr/bin/env python3
"""Prove readiness assessment against real files and real Git repositories."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from tools.pilot_readiness.check import checksum_report, write_report


def run(
    *arguments: str,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def run_checker(
    checker: Path,
    root: Path,
    expected_status: str,
    expected_return_code: int,
) -> dict[str, Any]:
    result = run(
        sys.executable,
        str(checker),
        str(root),
        "--json",
        cwd=root,
        check=False,
    )
    if result.returncode != expected_return_code:
        raise AssertionError(
            f"readiness return code drifted: {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    payload: dict[str, Any] = json.loads(result.stdout)
    if payload.get("status") != expected_status:
        raise AssertionError(f"readiness status drifted: {payload}")
    return payload


def complete_plan(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^### \[ \] (PILOT-\d{3}) ",
        r"### [x] \1 ",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"^- \[ \] ", "- [x] ", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")


def complete_traceability(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^(\| PILOT-\d{3} \| )open( \|)",
        r"\1complete\2",
        text,
        flags=re.MULTILINE,
    )
    path.write_text(text, encoding="utf-8")


def complete_proofs(root: Path) -> None:
    proof_root = root / "specs/leonaid-pilot/proofs"
    proof_root.mkdir(parents=True, exist_ok=True)
    for task_id in re.findall(
        r"^### \[x\] (PILOT-\d{3}) ",
        (root / "specs/leonaid-pilot/PLAN.md").read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    ):
        (proof_root / f"{task_id}.md").write_text(
            f"# {task_id} – Readiness-Testfixture\n\n"
            f"Task-ID: `{task_id}`  \n"
            "Status: vollständig bewiesen\n",
            encoding="utf-8",
        )


def complete_decisions(path: Path) -> None:
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| PILOT-"):
            lines.append(line)
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        decision_id = cells[0]
        cells[6] = f"EVID-{decision_id.removeprefix('PILOT-')}"
        cells[7] = "accepted"
        cells[8] = (
            "small_business"
            if decision_id == "PILOT-TAX-001"
            else "not_required"
            if decision_id == "PILOT-INV-002"
            else "confirmed"
        )
        lines.append("| " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def initialize_git(root: Path) -> None:
    run("git", "init", "--initial-branch=main", cwd=root)
    run("git", "config", "user.name", "LeonAid Readiness Proof", cwd=root)
    run(
        "git",
        "config",
        "user.email",
        "readiness-proof@leonaid.invalid",
        cwd=root,
    )
    run("git", "add", "specs", cwd=root)
    run("git", "commit", "-m", "complete readiness fixture", cwd=root)
    run(
        "git",
        "update-ref",
        "refs/remotes/origin/main",
        "HEAD",
        cwd=root,
    )


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise AssertionError(f"fixture mutation is not unique: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    checker = root / "tools/pilot_readiness/check.py"

    current = run_checker(checker, root, "blocked", 2)
    if (
        current["summary"]["hardGateCount"] != 16
        or len(current["tasks"]) != 21
        or not current["summary"]["openDecisionIds"]
    ):
        raise AssertionError("current blocked readiness coverage is incomplete")
    checksum = current.pop("checksumSha256")
    if checksum != checksum_report(current):
        raise AssertionError("readiness checksum is not reproducible")
    current["checksumSha256"] = checksum
    serialized = json.dumps(current, sort_keys=True).casefold()
    forbidden = ("@", "cookie", "payload", "sponsor", ".local/pilot")
    if any(value in serialized for value in forbidden):
        raise AssertionError("readiness report contains private or business payload")
    if arguments.report is not None:
        write_report(arguments.report.resolve(), current)

    with tempfile.TemporaryDirectory() as temporary:
        ready_root = Path(temporary) / "ready"
        shutil.copytree(
            root / "specs/leonaid-pilot", ready_root / "specs/leonaid-pilot"
        )
        complete_plan(ready_root / "specs/leonaid-pilot/PLAN.md")
        complete_traceability(ready_root / "specs/leonaid-pilot/TRACEABILITY.md")
        complete_proofs(ready_root)
        complete_decisions(ready_root / "specs/leonaid-pilot/DECISIONS.md")
        initialize_git(ready_root)

        ready = run_checker(checker, ready_root, "ready", 0)
        if (
            ready["summary"]["blockedGateIds"]
            or not ready["repository"]["remoteSynced"]
        ):
            raise AssertionError("complete fixture was not fully ready")

        missing_proof = ready_root / "specs/leonaid-pilot/proofs/PILOT-052.md"
        missing_proof.unlink()
        missing = run_checker(checker, ready_root, "blocked", 2)
        if "PILOT-052" not in missing["summary"]["missingProofTaskIds"]:
            raise AssertionError("missing proof was not reported")
        run("git", "restore", "specs/leonaid-pilot/proofs/PILOT-052.md", cwd=ready_root)

        proof = ready_root / "specs/leonaid-pilot/proofs/PILOT-051.md"
        replace_once(proof, "Status: vollständig bewiesen", "Status: Teilnachweis")
        partial = run_checker(checker, ready_root, "blocked", 2)
        if "PILOT-051" not in partial["summary"]["incompleteProofTaskIds"]:
            raise AssertionError("incomplete proof was not reported")
        run("git", "restore", "specs/leonaid-pilot/proofs/PILOT-051.md", cwd=ready_root)

        (ready_root / "untracked-private-note.txt").write_text(
            "synthetic dirty-tree canary",
            encoding="utf-8",
        )
        dirty = run_checker(checker, ready_root, "blocked", 2)
        if "working_tree_dirty" not in dirty["summary"]["repositoryBlockers"]:
            raise AssertionError("dirty working tree was not reported")

        drift_root = Path(temporary) / "drift"
        shutil.copytree(
            root / "specs/leonaid-pilot", drift_root / "specs/leonaid-pilot"
        )
        initialize_git(drift_root)
        plan = drift_root / "specs/leonaid-pilot/PLAN.md"
        replace_once(plan, "PILOT-GATE-016", "PILOT-GATE-999")
        result = run(
            sys.executable,
            str(checker),
            str(drift_root),
            "--json",
            cwd=drift_root,
            check=False,
        )
        if result.returncode != 1 or "hard gate set drifted" not in result.stderr:
            raise AssertionError("hard-gate drift was not rejected")

    print(
        "pilot-readiness-test: OK: real blocked state, complete fixture, "
        "missing/partial proof, dirty Git and hard-gate drift proven"
    )


if __name__ == "__main__":
    main()
