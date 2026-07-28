#!/usr/bin/env python3
"""Validate the executable LeonAid pilot plan and its public proof contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TASK_HEADING = re.compile(r"^### \[([ x])\] (PILOT-\d{3}) (.+)$")
CHECKBOX = re.compile(r"^- \[([ x])\] (.+)$")
DEPENDENCIES = re.compile(r"^Abhängigkeiten: (.+)$")
TASK_ID = re.compile(r"PILOT-\d{3}")
GATE_ROW = re.compile(r"^\| (PILOT-GATE-\d{3}) \| (.+?) \| (.+?) \|$")
TRACE_ROW = re.compile(
    r"^\| (PILOT-\d{3}) \| (open|complete) \| "
    r"\[([^\]]+)\]\((proofs/PILOT-\d{3}\.md)\) \|$"
)
EXPECTED_TASK_IDS = {
    "PILOT-000",
    "PILOT-001",
    "PILOT-002",
    "PILOT-010",
    "PILOT-011",
    "PILOT-012",
    "PILOT-013",
    "PILOT-020",
    "PILOT-021",
    "PILOT-030",
    "PILOT-031",
    "PILOT-032",
    "PILOT-040",
    "PILOT-041",
    "PILOT-042",
    "PILOT-043",
    "PILOT-044",
    "PILOT-050",
    "PILOT-051",
    "PILOT-052",
    "PILOT-053",
}
EXPECTED_GATE_IDS = {f"PILOT-GATE-{number:03d}" for number in range(1, 17)}


class ContractError(RuntimeError):
    """A deterministic pilot-plan contract violation."""


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    complete: bool
    text: str
    line: int


@dataclass(frozen=True)
class Task:
    task_id: str
    complete: bool
    title: str
    dependencies: tuple[str, ...]
    criteria: tuple[Criterion, ...]
    line: int


@dataclass(frozen=True)
class TraceEntry:
    task_id: str
    status: str
    proof_path: str


def normalize_text(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


def criterion_id(task_id: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12].upper()
    return f"{task_id}-C-{digest}"


def parse_criteria(
    lines: list[str], start: int, end: int, task_id: str
) -> tuple[Criterion, ...]:
    criteria: list[Criterion] = []
    index = start
    while index < end:
        match = CHECKBOX.match(lines[index])
        if match is None:
            index += 1
            continue
        parts = [match.group(2)]
        cursor = index + 1
        while cursor < end and lines[cursor].startswith("      "):
            parts.append(lines[cursor].strip())
            cursor += 1
        text = normalize_text(parts)
        criteria.append(
            Criterion(
                criterion_id=criterion_id(task_id, text),
                complete=match.group(1) == "x",
                text=text,
                line=index + 1,
            )
        )
        index = cursor
    return tuple(criteria)


def parse_plan(plan: Path) -> dict[str, Task]:
    lines = plan.read_text(encoding="utf-8").splitlines()
    headings: list[tuple[int, re.Match[str]]] = []
    first_task_line: int | None = None
    for index, line in enumerate(lines):
        heading = TASK_HEADING.match(line)
        if heading is not None:
            headings.append((index, heading))
            first_task_line = index if first_task_line is None else first_task_line

    if not headings:
        raise ContractError("no pilot task headings found")

    for index, line in enumerate(lines):
        if CHECKBOX.match(line) and (
            first_task_line is None or index < first_task_line
        ):
            raise ContractError(f"orphan criterion outside a task on line {index + 1}")

    tasks: dict[str, Task] = {}
    for position, (start, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        task_id = heading.group(2)
        if task_id in tasks:
            raise ContractError(f"duplicate task ID: {task_id}")

        dependency_lines = [
            match.group(1)
            for line in lines[start + 1 : end]
            if (match := DEPENDENCIES.match(line)) is not None
        ]
        if len(dependency_lines) != 1:
            raise ContractError(
                f"{task_id} must have exactly one dependency declaration"
            )
        dependency_text = dependency_lines[0]
        dependencies = tuple(dict.fromkeys(TASK_ID.findall(dependency_text)))
        if task_id == "PILOT-000":
            if dependency_text != "abgeschlossener PoC":
                raise ContractError("PILOT-000 must depend on the completed PoC")
        elif not dependencies:
            raise ContractError(f"{task_id} has no machine-readable dependency")

        criteria = parse_criteria(lines, start + 1, end, task_id)
        if not criteria:
            raise ContractError(f"{task_id} has no acceptance or proof criteria")
        tasks[task_id] = Task(
            task_id=task_id,
            complete=heading.group(1) == "x",
            title=heading.group(3),
            dependencies=dependencies,
            criteria=criteria,
            line=start + 1,
        )

    actual_ids = set(tasks)
    if actual_ids != EXPECTED_TASK_IDS:
        missing = sorted(EXPECTED_TASK_IDS - actual_ids)
        unexpected = sorted(actual_ids - EXPECTED_TASK_IDS)
        raise ContractError(
            f"pilot task set drifted; missing={missing}, unexpected={unexpected}"
        )
    return tasks


def validate_dependencies(tasks: dict[str, Task]) -> None:
    for task in tasks.values():
        for dependency in task.dependencies:
            if dependency not in tasks:
                raise ContractError(
                    f"unknown dependency {dependency} referenced by {task.task_id}"
                )
            if dependency == task.task_id:
                raise ContractError(f"{task.task_id} depends on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ContractError(f"dependency cycle includes {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in tasks[task_id].dependencies:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(tasks):
        visit(task_id)


def parse_traceability(path: Path) -> dict[str, TraceEntry]:
    entries: dict[str, TraceEntry] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| PILOT-"):
            continue
        match = TRACE_ROW.match(line)
        if match is None:
            if line.startswith("| PILOT-GATE-"):
                continue
            task_match = TASK_ID.search(line)
            task = task_match.group(0) if task_match else "unknown"
            raise ContractError(f"proof link missing or malformed for {task}")
        task_id, status, label, proof_path = match.groups()
        if task_id in entries:
            raise ContractError(f"duplicate traceability row: {task_id}")
        expected_path = f"proofs/{task_id}.md"
        if label != task_id or proof_path != expected_path:
            raise ContractError(f"proof link missing or malformed for {task_id}")
        entries[task_id] = TraceEntry(task_id, status, proof_path)
    if set(entries) != EXPECTED_TASK_IDS:
        missing = sorted(EXPECTED_TASK_IDS - set(entries))
        unexpected = sorted(set(entries) - EXPECTED_TASK_IDS)
        raise ContractError(
            f"traceability task set drifted; missing={missing}, unexpected={unexpected}"
        )
    return entries


def parse_hard_gates(plan: Path, tasks: dict[str, Task]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        plan.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = GATE_ROW.match(line)
        if match is None:
            continue
        gate_id, text, task_text = match.groups()
        if gate_id in seen:
            raise ContractError(f"duplicate hard gate ID: {gate_id}")
        seen.add(gate_id)
        referenced_tasks = tuple(dict.fromkeys(TASK_ID.findall(task_text)))
        if not referenced_tasks:
            raise ContractError(f"{gate_id} has no task mapping")
        for task_id in referenced_tasks:
            if task_id not in tasks:
                raise ContractError(
                    f"unknown task {task_id} referenced by hard gate {gate_id}"
                )
        gates.append(
            {
                "gate_id": gate_id,
                "text": text,
                "tasks": referenced_tasks,
                "line": line_number,
            }
        )
    if seen != EXPECTED_GATE_IDS:
        missing = sorted(EXPECTED_GATE_IDS - seen)
        unexpected = sorted(seen - EXPECTED_GATE_IDS)
        raise ContractError(
            f"hard gate set drifted; missing={missing}, unexpected={unexpected}"
        )
    return gates


def validate_completion(
    root: Path,
    tasks: dict[str, Task],
    traceability: dict[str, TraceEntry],
) -> None:
    for task_id, task in tasks.items():
        trace = traceability[task_id]
        expected_status = "complete" if task.complete else "open"
        if trace.status != expected_status:
            raise ContractError(
                f"{task_id} plan status {expected_status} differs from "
                f"traceability status {trace.status}"
            )
        if not task.complete:
            continue
        open_criteria = [
            criterion.criterion_id
            for criterion in task.criteria
            if not criterion.complete
        ]
        if open_criteria:
            raise ContractError(
                f"prematurely completed task {task_id} has open criteria: "
                f"{', '.join(open_criteria)}"
            )
        for dependency in task.dependencies:
            if not tasks[dependency].complete:
                raise ContractError(
                    f"prematurely completed task {task_id} has open dependency "
                    f"{dependency}"
                )
        proof = root / "specs/leonaid-pilot" / trace.proof_path
        if not proof.is_file():
            raise ContractError(f"completed task has no proof document: {task_id}")
        proof_text = proof.read_text(encoding="utf-8")
        if f"Task-ID: `{task_id}`" not in proof_text:
            raise ContractError(f"proof document has no exact Task-ID: {task_id}")
        if "Status: vollständig bewiesen" not in proof_text:
            raise ContractError(f"proof document is not complete: {task_id}")


def build_report(tasks: dict[str, Task], gates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "leonaid.pilot-contract/v1",
        "tasks": [
            {
                "task_id": task.task_id,
                "title": task.title,
                "complete": task.complete,
                "dependencies": task.dependencies,
                "criteria": [
                    {
                        "criterion_id": criterion.criterion_id,
                        "complete": criterion.complete,
                        "text": criterion.text,
                        "line": criterion.line,
                    }
                    for criterion in task.criteria
                ],
                "line": task.line,
            }
            for task in tasks.values()
        ],
        "hard_gates": gates,
    }


def check(root: Path) -> dict[str, Any]:
    plan = root / "specs/leonaid-pilot/PLAN.md"
    traceability_path = root / "specs/leonaid-pilot/TRACEABILITY.md"
    if not plan.is_file():
        raise ContractError(f"missing pilot plan: {plan}")
    if not traceability_path.is_file():
        raise ContractError(f"missing pilot traceability: {traceability_path}")
    tasks = parse_plan(plan)
    validate_dependencies(tasks)
    traceability = parse_traceability(traceability_path)
    gates = parse_hard_gates(plan, tasks)
    validate_completion(root, tasks, traceability)
    return build_report(tasks, gates)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    try:
        report = check(arguments.root.resolve())
    except ContractError as error:
        print(f"pilot-contract: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if arguments.report is not None:
        report_path = arguments.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    task_count = len(report["tasks"])
    criterion_count = sum(len(task["criteria"]) for task in report["tasks"])
    gate_count = len(report["hard_gates"])
    completed_count = sum(bool(task["complete"]) for task in report["tasks"])
    print(
        "pilot-contract: OK: "
        f"{task_count} tasks, {criterion_count} criteria, "
        f"{gate_count} hard gates, {completed_count} complete"
    )


if __name__ == "__main__":
    main()
