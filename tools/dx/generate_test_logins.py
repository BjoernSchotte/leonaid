#!/usr/bin/env python3
"""Generate the ignored local login handoff from Golden Data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LoginPersona:
    heading: str
    email: str
    dataset_role: str
    product_role: str
    destination_label: str
    destination_url: str


LOGIN_PERSONAS = (
    LoginPersona(
        heading="Akquisiteurin",
        email="anna.akquise@leonaid.invalid",
        dataset_role="ACQUIRER",
        product_role="Akquisiteurin für Krapfentaxi 2026",
        destination_label="Startseite nach Login",
        destination_url="http://127.0.0.1:8080/app/",
    ),
    LoginPersona(
        heading="Charity-Admin",
        email="klara.kern@leonaid.invalid",
        dataset_role="CHARITY_ADMIN",
        product_role="Charity-Admin für Krapfentaxi 2026",
        destination_label="Bestellungen",
        destination_url="http://127.0.0.1:8080/admin/orders",
    ),
    LoginPersona(
        heading="Finanzverantwortlicher",
        email="finn.finanzen@leonaid.invalid",
        dataset_role="FINANCE",
        product_role="Finanz-Lesezugriff für Krapfentaxi 2026",
        destination_label="Rechnungen und Zahlungsstatus",
        destination_url="http://127.0.0.1:8080/admin/invoices",
    ),
    LoginPersona(
        heading="System-Admin",
        email="system-admin@leonaid.invalid",
        dataset_role="SYSTEM_ADMIN",
        product_role="installationsweite System-Administration",
        destination_label="Betrieb und Feature-Flags",
        destination_url="http://127.0.0.1:8080/admin/system",
    ),
)


def require_non_production_environment() -> None:
    environment = os.environ.get("LEONAID_ENV")
    if environment not in {"local", "test"}:
        raise ValueError(
            "Golden-Testlogins sind ausschließlich in local/test erlaubt; "
            "Produktion und unbekannte Umgebungen werden abgewiesen"
        )


def load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Golden Dataset muss ein JSON-Objekt sein")
    return data


def render_test_logins(dataset: dict[str, Any]) -> str:
    raw_users = dataset.get("users")
    if not isinstance(raw_users, list):
        raise ValueError("Golden Dataset enthält keine Benutzerliste")

    users_by_email: dict[str, dict[str, Any]] = {}
    for raw_user in raw_users:
        if not isinstance(raw_user, dict):
            raise ValueError("Golden Dataset enthält einen ungültigen Benutzer")
        email = raw_user.get("email")
        if not isinstance(email, str) or not email:
            raise ValueError("Golden-Benutzer besitzt keine E-Mail-Adresse")
        if email in users_by_email:
            raise ValueError(f"Golden Dataset enthält E-Mail doppelt: {email}")
        users_by_email[email] = raw_user

    sections: list[str] = []
    for persona in LOGIN_PERSONAS:
        user = users_by_email.get(persona.email)
        if user is None:
            raise ValueError(f"Golden-Login fehlt: {persona.email}")
        if user.get("status") != "ACTIVE":
            raise ValueError(f"Golden-Login ist nicht aktiv: {persona.email}")
        if user.get("role") != persona.dataset_role:
            raise ValueError(
                f"Golden-Login {persona.email} hat Rolle {user.get('role')!r} "
                f"statt {persona.dataset_role!r}"
            )
        sections.append(
            "\n".join(
                (
                    f"## {persona.heading}",
                    "",
                    "- URL: http://127.0.0.1:8080/login",
                    f"- E-Mail: `{persona.email}`",
                    f"- Rolle: {persona.product_role}",
                    f"- {persona.destination_label}: {persona.destination_url}",
                )
            )
        )

    dataset_version = dataset.get("datasetVersion")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise ValueError("Golden Dataset besitzt keine Version")

    return (
        "# Lokale Test-Logins\n\n"
        f"Golden Dataset {dataset_version}; nur für den lokalen Stack. "
        "Diese Datei wird nicht committet.\n\n" + "\n\n".join(sections) + "\n\n"
        "## Öffentlicher Besteller oder Sponsor\n\n"
        "- Kein Login erforderlich\n"
        "- Aktionsseite und Formular: http://127.0.0.1:8080/krapfentaxi\n\n"
        "## Login-Code\n\n"
        "1. Auf der Login-Seite die gewünschte E-Mail angeben.\n"
        "2. Den frisch erzeugten sechsstelligen Code in Mailpit öffnen:\n"
        "   http://127.0.0.1:8080/mail/\n"
        "3. Den Code auf der Login-Seite bestätigen.\n\n"
        "Codes und Magic Links sind kurzlebig und werden deshalb hier nicht "
        "gespeichert.\n"
    )


def write_test_logins(dataset_path: Path, output_path: Path) -> None:
    content = render_test_logins(load_dataset(dataset_path))
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    output_path.chmod(0o600)


def check_test_logins(dataset_path: Path, output_path: Path) -> None:
    expected = render_test_logins(load_dataset(dataset_path))
    if not output_path.is_file():
        raise ValueError(f"lokale Testlogin-Datei fehlt: {output_path}")
    if output_path.read_text(encoding="utf-8") != expected:
        raise ValueError("lokale Testlogin-Datei ist nicht auf Golden-Data-Stand")
    if os.stat(output_path).st_mode & 0o777 != 0o600:
        raise ValueError("lokale Testlogin-Datei muss Dateimodus 0600 besitzen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        require_non_production_environment()
        if args.check:
            check_test_logins(args.dataset, args.output)
            print("test-login-handoff: OK: Golden-Personas, Inhalt und Modus aktuell")
            return 0
        write_test_logins(args.dataset, args.output)
    except (OSError, ValueError) as error:
        print(f"test-login-handoff: BLOCKED: {error}", file=sys.stderr)
        return 1
    print(f"test-login-handoff: OK: lokale Zugänge unter {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
