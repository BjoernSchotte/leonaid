"""Operator command that creates a Core System Admin (./leonaid pilot-create-system-admin).

A fresh pilot has no LeonAid account at all: nobody can sign in, invite
members or complete the CMS setup. This command, run inside the api
container of the running installation, creates (or promotes) one account
with the global ``system_admin`` role and then sends the normal sign-in mail
(code and link through the outbox and the worker); no password exists.

Usage inside the Core image::

    python -m leonaid.entrypoints.system_admin --email admin@club.org \\
        --display-name "Ada Admin" [--additional]

Idempotent: an account that already is an active System Admin is left
unchanged (no mail). Without ``--additional`` the command refuses once any
active System Admin exists, so a typo cannot add a second administrator.
Every change is an ``audit_event`` without an actor (the operator).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import uuid4

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.sessions import AsyncpgSessionRepository
from leonaid.adapters.postgres.system_admin import (
    SystemAdminOutcome,
    SystemAdminRefused,
    ensure_system_admin,
)
import re
from leonaid.application.sessions import SessionService
from leonaid.configuration import ConfigurationError, load_settings
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invitations import normalize_email

PREFIX = "pilot-create-system-admin"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog=PREFIX, description=__doc__.splitlines()[0])
    result.add_argument("--email", required=True)
    result.add_argument("--display-name", required=True)
    result.add_argument(
        "--operator",
        default="unknown",
        help="who runs it (user@host), recorded in the audit payload",
    )
    result.add_argument(
        "--additional",
        action="store_true",
        help="add a System Admin although one exists already",
    )
    return result


async def run(email: str, display_name: str, *, additional: bool, operator: str) -> int:
    settings = load_settings()
    request_id = f"{PREFIX}:{uuid4()}"
    pool = await create_pool(
        settings.core_database_url.get_secret_value(), minimum_size=1, maximum_size=2
    )
    try:
        result = await ensure_system_admin(
            pool,
            email=email,
            display_name=display_name,
            additional=additional,
            request_id=request_id,
            operator=operator,
        )
        outcome = result.outcome
        if outcome is SystemAdminOutcome.ALREADY:
            print(
                f"{PREFIX}: OK: {email} already is an active System Admin; "
                "nothing changed, no mail sent (sign in at /login)"
            )
            return 0
        sessions = SessionService(
            AsyncpgSessionRepository(pool),
            SecureMailPayload(settings.mail_payload_secret.get_secret_value()),
            hmac_secret=settings.invitation_hmac_secret.get_secret_value(),
            links=settings.links,
        )
        await sessions.request_login(email, request_id=request_id)
        if result.recovery:
            print(
                f"{PREFIX}: NOTE: no active System Admin was left (all suspended "
                "or archived); access restored without --additional"
            )
        if outcome is SystemAdminOutcome.PROMOTED:
            print(
                f"{PREFIX}: NOTE: existing member promoted; --display-name is "
                "ignored, the member keeps their name"
            )
        what = "created" if outcome is SystemAdminOutcome.CREATED else "promoted"
        print(
            f"{PREFIX}: OK: System Admin {what}; the sign-in mail for {email} "
            "is queued (the worker sends it)"
        )
        return 0
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        email = normalize_email(arguments.email)
    except DomainInvariantError:
        print(f"{PREFIX}: ERROR: --email is no valid address", file=sys.stderr)
        return 64
    display_name = " ".join(arguments.display_name.split())
    if not display_name or len(display_name) > 200:
        print(
            f"{PREFIX}: ERROR: --display-name must have 1 to 200 characters",
            file=sys.stderr,
        )
        return 64
    operator = arguments.operator
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}(@[A-Za-z0-9._-]{1,253})?", operator):
        print(f"{PREFIX}: ERROR: --operator must be user@host", file=sys.stderr)
        return 64
    try:
        return asyncio.run(
            run(
                email,
                display_name,
                additional=arguments.additional,
                operator=operator,
            )
        )
    except SystemAdminRefused as error:
        print(f"{PREFIX}: BLOCKED: {error}", file=sys.stderr)
        return 1
    except ConfigurationError as error:
        print(f"{PREFIX}: ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
