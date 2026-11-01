#!/usr/bin/env python3
"""Finish the Twenty bootstrap admin during ./leonaid pilot-install.

Production Twenty requires verified e-mail addresses. The bootstrap admin is
created while pilot-install runs Twenty without that requirement and without
public ingress. This tool then verifies the admin's address through Twenty's own
`verifyEmailAndGetLoginToken` mutation, so Twenty marks the user and refreshes
its caches itself:

- `mint-verification` creates a random one-time token and writes SQL that stores
  only its SHA-256 hash as Twenty's EMAIL_VERIFICATION_TOKEN app token. The SQL
  runs through psql inside the twenty-postgres container.
- `verify-email` redeems the token and confirms `isEmailVerified`.
- `remove-proof-company` deletes the company that `provision.py verify-key`
  writes as its permission proof, so production starts without test records.

No command prints a token, password or e-mail address.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

import httpx

from tools.seed.golden import SeedError, TwentyClient

EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}$")
TOKEN_TYPE = "EMAIL_VERIFICATION_TOKEN"
TOKEN_LIFETIME_MINUTES = 15
# Name written by tools/twenty/provision.py verify_integration_key().
PROOF_COMPANY_NAME = "POC-030 Berechtigungsnachweis"


class InstallError(RuntimeError):
    """The Twenty bootstrap admin could not be finished safely."""


def bootstrap_email() -> str:
    value = os.environ.get("TWENTY_BOOTSTRAP_EMAIL", "").strip().casefold()
    if not EMAIL.fullmatch(value):
        raise InstallError("TWENTY_BOOTSTRAP_EMAIL is missing or not an address")
    return value


def write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def verification_sql(email: str, token_hash: str) -> str:
    """SQL that stores the token hash for exactly one unverified admin."""
    if not EMAIL.fullmatch(email) or not re.fullmatch(r"[0-9a-f]{64}", token_hash):
        raise InstallError("verification input is malformed")
    # Both values are validated above and cannot contain quotes.
    return f"""\\set ON_ERROR_STOP on
DO $leonaid_install$
DECLARE
  matched integer;
BEGIN
  INSERT INTO core."appToken" ("userId", "type", "value", "expiresAt", "context")
  SELECT "id", '{TOKEN_TYPE}', '{token_hash}',
         now() + interval '{TOKEN_LIFETIME_MINUTES} minutes',
         jsonb_build_object('email', "email")
  FROM core."user"
  WHERE "email" = '{email}' AND "deletedAt" IS NULL;
  GET DIAGNOSTICS matched = ROW_COUNT;
  IF matched <> 1 THEN
    RAISE EXCEPTION 'pilot-install: expected exactly one bootstrap admin, found %',
      matched;
  END IF;
END
$leonaid_install$;
"""


def mint_verification(sql_output: Path, token_output: Path) -> None:
    email = bootstrap_email()
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    write_private(token_output, token + "\n")
    write_private(sql_output, verification_sql(email, token_hash))


def read_token(path: Path) -> str:
    if path.stat().st_mode & 0o077:
        raise InstallError("verification token file is not private")
    token = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise InstallError("verification token file is malformed")
    return token


def verify_email(token_file: Path) -> None:
    email = bootstrap_email()
    token = read_token(token_file)
    client = TwentyClient()
    try:
        verified = client.graphql(
            """
            mutation Verify($token: String!, $email: String!, $origin: String!) {
              verifyEmailAndGetLoginToken(
                emailVerificationToken: $token,
                email: $email,
                origin: $origin
              ) {
                loginToken { token }
              }
            }
            """,
            {"token": token, "email": email, "origin": client.origin},
        )
        result = verified.get("verifyEmailAndGetLoginToken")
        if not isinstance(result, dict):
            raise InstallError("Twenty did not confirm the e-mail verification")
        client.token_from(result.get("loginToken"), "loginToken")
        state = client.graphql(
            """
            query CheckUser($email: String!) {
              checkUserExists(email: $email) { exists isEmailVerified }
            }
            """,
            {"email": email},
        ).get("checkUserExists")
        if not isinstance(state, dict) or state.get("isEmailVerified") is not True:
            raise InstallError("Twenty still reports the bootstrap admin unverified")
    finally:
        client.close()


def records(payload: Any, collection: str) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get(collection) if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise InstallError(f"Twenty returned no {collection} list")
    return [item for item in items if isinstance(item, dict)]


def proof_companies(client: TwentyClient) -> list[dict[str, Any]]:
    response = client.client.get(
        f"{client.base_url}/rest/companies",
        params={"filter": f'name[eq]:"{PROOF_COMPANY_NAME}"', "limit": 60},
        headers={"Authorization": f"Bearer {client.access_token}"},
    )
    if response.status_code != 200:
        raise InstallError(
            f"listing proof companies failed: HTTP {response.status_code}"
        )
    return [
        item
        for item in records(response.json(), "companies")
        if item.get("name") == PROOF_COMPANY_NAME
    ]


def remove_proof_company() -> int:
    client = TwentyClient()
    try:
        client.authenticate()
        removed = 0
        for company in proof_companies(client):
            company_id = company.get("id")
            if not isinstance(company_id, str):
                raise InstallError("proof company has no id")
            response = client.request("DELETE", f"/rest/companies/{company_id}")
            if response.status_code not in {200, 204}:
                raise InstallError(
                    f"deleting the proof company failed: HTTP {response.status_code}"
                )
            removed += 1
        if proof_companies(client):
            raise InstallError("the proof company is still visible")
        return removed
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    mint = commands.add_parser("mint-verification")
    mint.add_argument("--sql-output", required=True, type=Path)
    mint.add_argument("--token-output", required=True, type=Path)
    verify = commands.add_parser("verify-email")
    verify.add_argument("--token-file", required=True, type=Path)
    commands.add_parser("remove-proof-company")
    arguments = parser.parse_args()
    try:
        if arguments.command == "mint-verification":
            mint_verification(arguments.sql_output, arguments.token_output)
            print("pilot-install: one-time verification token prepared")
        elif arguments.command == "verify-email":
            verify_email(arguments.token_file)
            print("pilot-install: Twenty confirmed the bootstrap admin address")
        else:
            removed = remove_proof_company()
            print(f"pilot-install: removed {removed} key-proof record(s) from Twenty")
    except (InstallError, SeedError, httpx.HTTPError, OSError) as error:
        print(f"pilot-install: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
