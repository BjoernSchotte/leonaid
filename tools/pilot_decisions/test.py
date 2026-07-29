#!/usr/bin/env python3
"""Real-file contract tests for the pilot decision register."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REGISTER = "specs/leonaid-pilot/DECISIONS.md"
EXPECTED_OPEN_BY_GATE = {
    "pilot-deploy": {
        "PILOT-MAIL-001",
        "PILOT-OPS-001",
        "PILOT-OPS-002",
        "PILOT-OPS-004",
        "PILOT-OPS-005",
        "PILOT-OPS-006",
        "PILOT-RUN-001",
    },
    "pilot-import": {
        "PILOT-MAIL-001",
        "PILOT-OPS-001",
        "PILOT-OPS-002",
        "PILOT-OPS-004",
        "PILOT-OPS-005",
        "PILOT-OPS-006",
        "PILOT-PRIV-001",
        "PILOT-RUN-001",
    },
    "pilot-backup": {
        "PILOT-MAIL-001",
        "PILOT-OPS-001",
        "PILOT-OPS-002",
        "PILOT-OPS-003",
        "PILOT-OPS-004",
        "PILOT-OPS-005",
        "PILOT-OPS-006",
        "PILOT-RUN-001",
    },
    "pilot-restore": {
        "PILOT-MAIL-001",
        "PILOT-OPS-001",
        "PILOT-OPS-002",
        "PILOT-OPS-003",
        "PILOT-OPS-004",
        "PILOT-OPS-005",
        "PILOT-OPS-006",
        "PILOT-RUN-001",
    },
    "pilot-release": {
        "PILOT-INV-001",
        "PILOT-INV-002",
        "PILOT-LEG-001",
        "PILOT-MAIL-001",
        "PILOT-OPS-001",
        "PILOT-OPS-002",
        "PILOT-OPS-003",
        "PILOT-OPS-004",
        "PILOT-OPS-005",
        "PILOT-OPS-006",
        "PILOT-PRIV-001",
        "PILOT-PRIV-002",
        "PILOT-RUN-001",
        "PILOT-TAX-001",
    },
}


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
    for gate, expected_open in EXPECTED_OPEN_BY_GATE.items():
        run(
            checker,
            root,
            ready=True,
            returncode=2,
            marker=f"pilot-doctor: BLOCKED ({gate})",
            arguments=("--gate", gate),
        )
        json_response = subprocess.run(
            [
                sys.executable,
                str(checker),
                str(root),
                "--ready",
                "--gate",
                gate,
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
            or payload["gate"] != gate
            or set(payload["openDecisionIds"]) != expected_open
            or payload["stopDecisionIds"]
        ):
            raise AssertionError(
                f"{gate} ist nicht fail-closed oder enthält Entscheidungen "
                f"aus dem falschen Gate: {payload}"
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

        invoice_contradiction = fixtures / "invoice-contradiction"
        contradictory_invoice = mutate(
            canonical,
            (
                "| PILOT-INV-001 | Rechnung | Pflichtangaben und "
                "Freigabeverantwortung | Rechtlicher Träger und "
                "Steuerberatung | 2026-07-28 | ADR-0002 | PENDING | open | "
                "PENDING | pilot-release |"
            ),
            (
                "| PILOT-INV-001 | Rechnung | Pflichtangaben und "
                "Freigabeverantwortung | Rechtlicher Träger und "
                "Steuerberatung | 2026-07-28 | ADR-0002 | "
                "EVID-INV-APPROVAL-20260728 | accepted | confirmed | "
                "pilot-release |"
            ),
        )
        write_register(invoice_contradiction, contradictory_invoice)
        run(
            checker,
            invoice_contradiction,
            returncode=1,
            marker="invoice approval contradicts open carrier or tax decision",
        )

        accounting = fixtures / "accounting-stop"
        accounting_stop = mutate(
            canonical,
            (
                "| PILOT-TAX-001 | Steuer | Steuerbehandlung der "
                "Krapfentaxi-Leistung | Steuerberatung und rechtlicher "
                "Träger | 2026-07-28 | ADR-0002 | PENDING | open | PENDING | "
                "pilot-release |"
            ),
            (
                "| PILOT-TAX-001 | Steuer | Steuerbehandlung der "
                "Krapfentaxi-Leistung | Steuerberatung und rechtlicher "
                "Träger | 2026-07-28 | ADR-0002 | "
                "EVID-TAX-SCOPE-20260728 | stop | "
                "full_accounting_required | pilot-release |"
            ),
        )
        write_register(accounting, accounting_stop)
        run(
            checker,
            accounting,
            ready=True,
            returncode=3,
            marker="pilot-doctor: STOP (pilot-release)",
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
        "pilot-decisions-test: OK: five gate-specific text/JSON checks, "
        "accepted register, both scope-STOP paths and five negative "
        "decision cases proven"
    )


if __name__ == "__main__":
    main()
