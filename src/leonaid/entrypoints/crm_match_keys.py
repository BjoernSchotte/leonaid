"""Operator command that backfills and repairs the CRM match keys in Twenty.

Request paths find CRM parties through the stored match key instead of
listing whole collections. Records created or renamed outside LeonAid (Twenty
UI, native Twenty CSV import, installations from before the key existed) carry
no or a stale key until this idempotent command has processed them.

Usage inside the Core image::

    python -m leonaid.entrypoints.crm_match_keys                      # full run
    python -m leonaid.entrypoints.crm_match_keys --changed-within 30  # minutes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.crm import CrmGatewayError

# Leaves headroom in Twenty's shared quota for the live system during a run.
DEFAULT_REQUESTS_PER_MINUTE = 60


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"crm-match-keys: ERROR: environment variable {name} is missing"
        )
    return value


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid ISO-8601 instant: {value}"
        ) from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("the instant needs a time zone offset")
    return parsed


def _positive_minutes(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("minutes must be an integer") from error
    if minutes < 1:
        raise argparse.ArgumentTypeError("minutes must be at least 1")
    return minutes


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="crm-match-keys",
        description="Backfill or repair the LeonAid match keys stored in Twenty.",
    )
    scope = result.add_mutually_exclusive_group()
    scope.add_argument(
        "--changed-since",
        type=_instant,
        help="only records updated at or after this ISO-8601 instant",
    )
    scope.add_argument(
        "--changed-within",
        type=_positive_minutes,
        metavar="MINUTES",
        help="only records updated within the last MINUTES (for scheduled runs)",
    )
    result.add_argument(
        "--requests-per-minute",
        type=int,
        default=DEFAULT_REQUESTS_PER_MINUTE,
        help=f"Twenty request budget of this run (default {DEFAULT_REQUESTS_PER_MINUTE})",
    )
    return result


async def run(arguments: argparse.Namespace) -> list[dict[str, object]]:
    updated_since: datetime | None = arguments.changed_since
    if arguments.changed_within is not None:
        updated_since = datetime.now(timezone.utc) - timedelta(
            minutes=arguments.changed_within
        )
    settings = TwentyGatewaySettings(
        base_url=_required_env("TWENTY_BASE_URL"),
        api_key=SecretStr(_required_env("TWENTY_INTEGRATION_API_KEY")),
        timeout_seconds=15.0,
        requests_per_minute=arguments.requests_per_minute,
    )
    async with TwentyCrmGateway(settings) as gateway:
        reports = await gateway.repair_match_keys(
            updated_since=updated_since,
            correlation_id=f"crm-match-keys:{uuid4()}",
        )
    return [
        {
            "partyKind": report.party_kind.value,
            "scanned": report.scanned,
            "repaired": report.repaired,
        }
        for report in reports
    ]


def main() -> int:
    arguments = parser().parse_args()
    try:
        summary = asyncio.run(run(arguments))
    except CrmGatewayError as error:
        print(
            "crm-match-keys: ERROR: "
            + json.dumps(
                {
                    "code": error.code,
                    "operation": error.operation,
                    "retryable": error.retryable,
                    "correlationId": error.correlation_id,
                }
            ),
            file=sys.stderr,
        )
        return 1
    except ValueError as error:
        print(f"crm-match-keys: ERROR: {error}", file=sys.stderr)
        return 1
    print("crm-match-keys: OK: " + json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
