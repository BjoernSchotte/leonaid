#!/usr/bin/env python3
"""Real public DNS smoke and deterministic mail-domain policy mutations."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

from tools.mail_domain.check import (
    MailDomainError,
    assess,
    checksum_report,
    load_expectation,
    resolve_records,
    validate_identities,
    validate_records,
    write_report,
)


def rejected(expected: str, operation: Callable[[], object]) -> None:
    try:
        operation()
    except MailDomainError as error:
        if str(error) != expected:
            raise AssertionError(
                f"expected {expected!r}, got {str(error)!r}"
            ) from error
        return
    raise AssertionError(f"mail-domain mutation was accepted: {expected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    fixture = root / "tests/fixtures/mail-domain/public-resolver-smoke-v1.json"
    checker = root / "tools/mail_domain/check.py"
    expectation = load_expectation(fixture)

    cli = subprocess.run(
        [
            sys.executable,
            str(checker),
            "--expectation",
            str(fixture),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if cli.returncode != 0:
        raise AssertionError(f"real public DNS CLI failed:\n{cli.stderr}")
    cli_report = json.loads(cli.stdout)

    records = resolve_records(expectation)
    report = assess(expectation, records)
    checksum = report.pop("checksumSha256")
    if checksum != checksum_report(report):
        raise AssertionError("mail-domain checksum is not reproducible")
    report["checksumSha256"] = checksum
    if report != cli_report:
        raise AssertionError("CLI and direct public DNS assessment drifted")

    serialized = json.dumps(report, sort_keys=True).casefold()
    forbidden = (
        expectation.envelope_from.casefold(),
        expectation.visible_from.casefold(),
        expectation.reply_to.casefold(),
        "v=spf1",
        "v=dkim1",
        "v=dmarc1",
    )
    if any(value in serialized for value in forbidden):
        raise AssertionError("public report contains identities or raw DNS records")

    rejected(
        "dmarc_policy_mismatch",
        lambda: validate_records(
            replace(expectation, dmarc_policy="reject"),
            records,
        ),
    )
    rejected(
        "spf_required_term_missing",
        lambda: validate_records(
            replace(
                expectation,
                spf_required_terms=("include:_spf.missing.invalid",),
            ),
            records,
        ),
    )
    revoked_dkim = dict(records)
    revoked_dkim["dkim"] = ("v=DKIM1; k=rsa; p=",)
    rejected(
        "dkim_public_key_missing",
        lambda: validate_records(expectation, revoked_dkim),
    )
    rejected(
        "visible_from_not_aligned",
        lambda: validate_identities(
            replace(
                expectation,
                visible_from="LeonAid <noreply@misaligned.invalid>",
            )
        ),
    )
    if arguments.report is not None:
        write_report(arguments.report.resolve(), report)
    print(
        "mail-domain-test: OK: real public DNS resolver, aligned identities, "
        "SPF, active DKIM, DMARC, privacy and four fail-closed mutations proven"
    )


if __name__ == "__main__":
    main()
