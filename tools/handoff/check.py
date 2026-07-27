#!/usr/bin/env python3
"""Validate the PoC handoff documentation as an executable contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

REQUIRED_CONTENT: dict[str, tuple[str, ...]] = {
    "README.md": (
        "In höchstens 30 Minuten zur Golden Journey",
        "./leonaid bootstrap",
        "./leonaid provision-twenty",
        "./leonaid test-golden-journey",
        "http://127.0.0.1:8080/krapfentaxi",
        "specs/leonaid-poc/KNOWN-LIMITS.md",
    ),
    "specs/leonaid-poc/ARCHITECTURE.md": (
        "Laufzeitbild",
        "Daten- und Transaktionsgrenzen",
        "API- und Sicherheitsvertrag",
        "packages/api-client/openapi.json",
    ),
    "specs/leonaid-poc/RUNBOOKS.md": (
        "Normalbetrieb",
        "Benutzerverwaltung",
        "Incident-Runbook",
        "infra/upgrade/maintenance.sh enable",
        "Direkte Datenbankänderung ist verboten",
    ),
    "specs/leonaid-poc/KNOWN-LIMITS.md": (
        "keine bekannten P0-/P1-Defekte",
        "Account-Sperre",
        "Mailpit ist ausschließlich lokales Testsystem",
        "Produktiv- oder Pilotfreigabe",
    ),
    "specs/leonaid-poc/ACCEPTANCE.md": (
        "ace42c1fc39857f1e6cb64b404d98bd8d93c3c5e",
        "Version 1.0.0",
        "cold_run=true",
        "Produktverantwortlicher nimmt diesen PoC-Schnitt ausdrücklich ab",
    ),
}


def local_links(path: Path, content: str) -> list[Path]:
    result: list[Path] = []
    for raw_target in MARKDOWN_LINK.findall(content):
        target = raw_target.strip().strip("<>")
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        relative = target.split("#", 1)[0]
        if relative:
            result.append((path.parent / relative).resolve())
    return result


def check(root: Path) -> list[str]:
    problems: list[str] = []
    for relative, snippets in REQUIRED_CONTENT.items():
        path = root / relative
        if not path.is_file():
            problems.append(f"Übergabedokument fehlt: {relative}")
            continue
        content = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in content:
                problems.append(f"{relative}: Pflichtinhalt fehlt: {snippet}")
        for target in local_links(path, content):
            if not target.exists():
                problems.append(
                    f"{relative}: lokaler Link zeigt auf fehlendes Ziel: {target}"
                )
    return problems


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = check(root)
    if problems:
        for problem in problems:
            print(f"handoff-check: ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print(
        "handoff-check: OK: Onboarding, Architektur, Runbooks, Grenzen und "
        "Abnahmeprotokoll vollständig verlinkt"
    )


if __name__ == "__main__":
    main()
