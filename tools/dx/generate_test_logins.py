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
    # Navigation labels match the German app UI the user clicks.
    destination_label: str
    destination_url: str


LOGIN_PERSONAS = (
    LoginPersona(
        heading="Acquirer",
        email="anna.akquise@leonaid.invalid",
        dataset_role="ACQUIRER",
        product_role="Acquirer for Krapfentaxi 2026",
        destination_label="Start page after login",
        destination_url="http://127.0.0.1:8080/app/",
    ),
    LoginPersona(
        heading="Charity admin",
        email="klara.kern@leonaid.invalid",
        dataset_role="CHARITY_ADMIN",
        product_role="Charity admin for Krapfentaxi 2026",
        destination_label="Bestellungen",
        destination_url="http://127.0.0.1:8080/admin/orders",
    ),
    LoginPersona(
        heading="Finance lead",
        email="finn.finanzen@leonaid.invalid",
        dataset_role="FINANCE",
        product_role="Finance read access for Krapfentaxi 2026",
        destination_label="Rechnungen und Zahlungsstatus",
        destination_url="http://127.0.0.1:8080/admin/invoices",
    ),
    LoginPersona(
        heading="System admin",
        email="system-admin@leonaid.invalid",
        dataset_role="SYSTEM_ADMIN",
        product_role="Installation-wide system administration",
        destination_label="Betrieb und Feature-Flags",
        destination_url="http://127.0.0.1:8080/admin/system",
    ),
)


def require_non_production_environment() -> None:
    environment = os.environ.get("LEONAID_ENV")
    if environment not in {"local", "test"}:
        raise ValueError(
            "Golden test logins are allowed only in local/test; "
            "production and unknown environments are rejected"
        )


def load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Golden dataset must be a JSON object")
    return data


def render_test_logins(dataset: dict[str, Any]) -> str:
    raw_users = dataset.get("users")
    if not isinstance(raw_users, list):
        raise ValueError("Golden dataset contains no user list")

    users_by_email: dict[str, dict[str, Any]] = {}
    for raw_user in raw_users:
        if not isinstance(raw_user, dict):
            raise ValueError("Golden dataset contains an invalid user")
        email = raw_user.get("email")
        if not isinstance(email, str) or not email:
            raise ValueError("Golden user has no email address")
        if email in users_by_email:
            raise ValueError(f"Golden dataset contains duplicate email: {email}")
        users_by_email[email] = raw_user

    sections: list[str] = []
    for persona in LOGIN_PERSONAS:
        user = users_by_email.get(persona.email)
        if user is None:
            raise ValueError(f"Golden login missing: {persona.email}")
        if user.get("status") != "ACTIVE":
            raise ValueError(f"Golden login is not active: {persona.email}")
        if user.get("role") != persona.dataset_role:
            raise ValueError(
                f"Golden login {persona.email} has role {user.get('role')!r} "
                f"instead of {persona.dataset_role!r}"
            )
        sections.append(
            "\n".join(
                (
                    f"## {persona.heading}",
                    "",
                    "- URL: http://127.0.0.1:8080/login",
                    f"- Email: `{persona.email}`",
                    f"- Role: {persona.product_role}",
                    f"- {persona.destination_label}: {persona.destination_url}",
                )
            )
        )

    dataset_version = dataset.get("datasetVersion")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise ValueError("Golden dataset has no version")

    return (
        "# Local test logins\n\n"
        f"Golden dataset {dataset_version}; for the local stack only. "
        "This file is not committed.\n\n" + "\n\n".join(sections) + "\n\n"
        "## Public customer or sponsor\n\n"
        "- No login required\n"
        "- Campaign page and form: http://127.0.0.1:8080/krapfentaxi\n\n"
        "## Login code\n\n"
        "1. Enter the email address on the login page.\n"
        "2. Open the newly created six-digit code in Mailpit:\n"
        "   http://127.0.0.1:8080/mail/\n"
        "3. Confirm the code on the login page.\n\n"
        "Codes and magic links are short-lived, so they are not stored "
        "here.\n"
    )


def write_test_logins(dataset_path: Path, output_path: Path) -> None:
    content = render_test_logins(load_dataset(dataset_path))
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    output_path.chmod(0o600)


def check_test_logins(dataset_path: Path, output_path: Path) -> None:
    expected = render_test_logins(load_dataset(dataset_path))
    if not output_path.is_file():
        raise ValueError(f"local test login file missing: {output_path}")
    if output_path.read_text(encoding="utf-8") != expected:
        raise ValueError("local test login file does not match the golden data")
    if os.stat(output_path).st_mode & 0o777 != 0o600:
        raise ValueError("local test login file must have file mode 0600")


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
            print(
                "test-login-handoff: OK: golden personas, content and mode up to date"
            )
            return 0
        write_test_logins(args.dataset, args.output)
    except (OSError, ValueError) as error:
        print(f"test-login-handoff: BLOCKED: {error}", file=sys.stderr)
        return 1
    print(f"test-login-handoff: OK: local logins at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
