#!/usr/bin/env python3
"""Validate the public pilot decision register and readiness gate."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

EXPECTED_IDS = {
    "PILOT-LEG-001",
    "PILOT-TAX-001",
    "PILOT-INV-001",
    "PILOT-INV-002",
    "PILOT-PRIV-001",
    "PILOT-PRIV-002",
    "PILOT-MAIL-001",
    "PILOT-OPS-001",
    "PILOT-OPS-002",
    "PILOT-OPS-003",
    "PILOT-OPS-004",
    "PILOT-OPS-005",
    "PILOT-OPS-006",
    "PILOT-RUN-001",
}
HEADERS = (
    "ID",
    "Bereich",
    "Entscheidung",
    "Owner-Rolle",
    "Erfasst am",
    "Quelle",
    "Evidence-ID",
    "Status",
    "Wert",
    "Spätestes Gate",
)
STATUSES = {"open", "accepted", "stop"}
GATES = {
    "pilot-deploy",
    "pilot-release",
    "pilot-import",
    "pilot-backup",
    "pilot-restore",
}
TAX_VALUES = {"small_business", "standard_vat", "tax_exempt"}
EVIDENCE_ID = re.compile(r"^EVID-[A-Z0-9][A-Z0-9._-]{5,63}$")


class DecisionError(RuntimeError):
    """A deterministic decision-register violation."""


@dataclass(frozen=True)
class Decision:
    decision_id: str
    area: str
    subject: str
    owner: str
    captured_at: str
    source: str
    evidence_id: str
    status: str
    value: str
    latest_gate: str


def _cells(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def parse_register(path: Path) -> dict[str, Decision]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if _cells(line) == HEADERS),
        None,
    )
    if header_index is None:
        raise DecisionError("decision table header is missing or malformed")

    decisions: dict[str, Decision] = {}
    for line in lines[header_index + 2 :]:
        if not line.startswith("| PILOT-"):
            if decisions:
                break
            continue
        cells = _cells(line)
        if len(cells) != len(HEADERS):
            raise DecisionError(f"malformed decision row: {line}")
        decision = Decision(*cells)
        if decision.decision_id in decisions:
            raise DecisionError(f"duplicate decision ID: {decision.decision_id}")
        decisions[decision.decision_id] = decision

    actual_ids = set(decisions)
    if actual_ids != EXPECTED_IDS:
        raise DecisionError(
            "decision set drifted; "
            f"missing={sorted(EXPECTED_IDS - actual_ids)}, "
            f"unexpected={sorted(actual_ids - EXPECTED_IDS)}"
        )
    return decisions


def validate_register(decisions: dict[str, Decision]) -> None:
    for decision in decisions.values():
        required = {
            "area": decision.area,
            "subject": decision.subject,
            "owner": decision.owner,
            "captured_at": decision.captured_at,
            "source": decision.source,
            "evidence_id": decision.evidence_id,
            "status": decision.status,
            "value": decision.value,
            "latest_gate": decision.latest_gate,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise DecisionError(
                f"{decision.decision_id} missing required field(s): {', '.join(missing)}"
            )
        try:
            dt.date.fromisoformat(decision.captured_at)
        except ValueError as error:
            raise DecisionError(
                f"{decision.decision_id} has invalid ISO date"
            ) from error
        if decision.status not in STATUSES:
            raise DecisionError(
                f"{decision.decision_id} has invalid status {decision.status!r}"
            )
        if decision.latest_gate not in GATES:
            raise DecisionError(
                f"{decision.decision_id} has unknown gate {decision.latest_gate!r}"
            )
        if decision.status == "open":
            if decision.evidence_id != "PENDING" or decision.value != "PENDING":
                raise DecisionError(
                    f"{decision.decision_id} open decisions must use PENDING"
                )
        elif not EVIDENCE_ID.fullmatch(decision.evidence_id):
            raise DecisionError(f"{decision.decision_id} missing stable Evidence-ID")
        elif decision.value == "PENDING":
            raise DecisionError(
                f"{decision.decision_id} resolved decision has no result"
            )

    tax = decisions["PILOT-TAX-001"]
    einvoice = decisions["PILOT-INV-002"]
    if tax.value == "full_accounting_required" and tax.status != "stop":
        raise DecisionError("full accounting requirement must result in STOP")
    if tax.status == "accepted" and tax.value not in TAX_VALUES:
        raise DecisionError("accepted tax decision has unsupported value")
    if einvoice.value == "required" and einvoice.status != "stop":
        raise DecisionError("required e-invoice must result in STOP")
    if einvoice.status == "accepted" and einvoice.value != "not_required":
        raise DecisionError("accepted e-invoice decision must be not_required")

    invoice = decisions["PILOT-INV-001"]
    carrier = decisions["PILOT-LEG-001"]
    if invoice.status == "accepted" and (
        tax.status != "accepted" or carrier.status != "accepted"
    ):
        raise DecisionError("invoice approval contradicts open carrier or tax decision")


def readiness(decisions: dict[str, Decision]) -> tuple[list[str], list[str]]:
    open_ids = sorted(
        item.decision_id for item in decisions.values() if item.status == "open"
    )
    stop_ids = sorted(
        item.decision_id for item in decisions.values() if item.status == "stop"
    )
    return open_ids, stop_ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument(
        "--ready",
        action="store_true",
        help="require all decisions to be accepted for productive pilot actions",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    register = root / "specs/leonaid-pilot/DECISIONS.md"
    try:
        decisions = parse_register(register)
        validate_register(decisions)
    except (DecisionError, OSError) as error:
        print(f"pilot-decisions: ERROR: {error}", file=sys.stderr)
        return 1

    open_ids, stop_ids = readiness(decisions)
    if args.ready and stop_ids:
        print(
            "pilot-doctor: STOP: Pilot-Scope reicht nicht für " + ", ".join(stop_ids),
            file=sys.stderr,
        )
        return 3
    if args.ready and open_ids:
        print(
            "pilot-doctor: BLOCKED: offene Entscheidungen: " + ", ".join(open_ids),
            file=sys.stderr,
        )
        return 2
    if args.ready:
        print("pilot-doctor: OK: alle Pilotentscheidungen sind freigegeben")
    else:
        print(
            "pilot-decisions: OK: "
            f"{len(decisions)} Entscheidungen, {len(open_ids)} offen, "
            f"{len(stop_ids)} STOP"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
