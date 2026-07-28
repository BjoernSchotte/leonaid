#!/usr/bin/env python3
"""Real-file contract tests for the pilot decision register."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REGISTER = "specs/leonaid-pilot/DECISIONS.md"


def run(
    checker: Path,
    root: Path,
    *,
    ready: bool = False,
    returncode: int = 0,
    marker: str,
    arguments: tuple[str, ...] = (),
) -> None:
    command = [sys.executable, str(checker), str(root)]
    if ready:
        command.append("--ready")
    command.extend(arguments)
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    output = result.stdout + result.stderr
    if result.returncode != returncode or marker not in output:
        raise AssertionError(f"expected rc={returncode} and {marker!r}, got:\n{output}")


def mutate(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise AssertionError(f"fixture mutation is not unique: {old!r}")
    return text.replace(old, new, 1)


def write_register(root: Path, text: str) -> None:
    target = root / REGISTER
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")


def accepted_register(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if not line.startswith("| PILOT-"):
            lines.append(line)
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        decision_id = cells[0]
        cells[6] = f"EVID-{decision_id.removeprefix('PILOT-')}-20260728"
        cells[7] = "accepted"
        if decision_id == "PILOT-TAX-001":
            cells[8] = "small_business"
        elif decision_id == "PILOT-INV-002":
            cells[8] = "not_required"
        else:
            cells[8] = "confirmed"
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    checker = root / "tools/pilot_decisions/check.py"
    canonical = (root / REGISTER).read_text(encoding="utf-8")

    run(checker, root, marker="pilot-decisions: OK: 14 Entscheidungen")
    run(
        checker,
        root,
        ready=True,
        returncode=2,
        marker="pilot-doctor: BLOCKED (pilot-release)",
    )
    run(
        checker,
        root,
        ready=True,
        returncode=2,
        marker="pilot-doctor: BLOCKED (pilot-deploy)",
        arguments=("--gate", "pilot-deploy"),
    )
    json_response = subprocess.run(
        [
            sys.executable,
            str(checker),
            str(root),
            "--ready",
            "--gate",
            "pilot-deploy",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(json_response.stdout)
    if (
        json_response.returncode != 2
        or payload["status"] != "blocked"
        or payload["gate"] != "pilot-deploy"
        or "PILOT-TAX-001" in payload["openDecisionIds"]
        or "PILOT-OPS-001" not in payload["openDecisionIds"]
    ):
        raise AssertionError(
            "gate-spezifischer JSON-Status ist nicht fail-closed oder "
            "enthält noch nicht fällige Entscheidungen"
        )
    help_response = subprocess.run(
        [sys.executable, str(checker), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    if help_response.returncode != 0 or "--gate" not in help_response.stdout:
        raise AssertionError("pilot-doctor besitzt keine vollständige Hilfe")

    with tempfile.TemporaryDirectory() as temporary:
        fixtures = Path(temporary)

        accepted = fixtures / "accepted"
        write_register(accepted, accepted_register(canonical))
        run(
            checker,
            accepted,
            ready=True,
            marker="pilot-doctor: OK (pilot-release)",
        )

        missing_owner = fixtures / "missing-owner"
        write_register(
            missing_owner,
            mutate(
                canonical,
                "| Rechtlicher Träger | 2026-07-28 | ADR-0001 |",
                "|  | 2026-07-28 | ADR-0001 |",
            ),
        )
        run(
            checker,
            missing_owner,
            returncode=1,
            marker="missing required field(s): owner",
        )

        missing_evidence = fixtures / "missing-evidence"
        bad_evidence = mutate(
            accepted_register(canonical),
            "| EVID-LEG-001-20260728 | accepted |",
            "|  | accepted |",
        )
        write_register(missing_evidence, bad_evidence)
        run(
            checker,
            missing_evidence,
            returncode=1,
            marker="missing required field(s): evidence_id",
        )

        contradiction = fixtures / "contradiction"
        bad_tax = mutate(
            accepted_register(canonical),
            "| accepted | small_business | pilot-release |",
            "| accepted | full_accounting_required | pilot-release |",
        )
        write_register(contradiction, bad_tax)
        run(
            checker,
            contradiction,
            returncode=1,
            marker="full accounting requirement must result in STOP",
        )

        einvoice = fixtures / "einvoice-stop"
        stop_text = mutate(
            accepted_register(canonical),
            "| accepted | not_required | pilot-release |",
            "| stop | required | pilot-release |",
        )
        write_register(einvoice, stop_text)
        run(
            checker,
            einvoice,
            ready=True,
            returncode=3,
            marker="pilot-doctor: STOP (pilot-release)",
        )

    print(
        "pilot-decisions-test: OK: gate-specific text/JSON/help, accepted "
        "register and four negative decision cases proven"
    )


if __name__ == "__main__":
    main()
