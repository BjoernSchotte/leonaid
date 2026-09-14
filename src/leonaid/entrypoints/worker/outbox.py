"""Operational CLI for the durable outbox; process path remains stable."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID

from leonaid.bootstrap.worker import build_worker
from leonaid.domain.outbox import OutboxState


async def execute(arguments: argparse.Namespace) -> int:
    database_url = os.environ["CORE_DATABASE_URL"]
    pool, queue, worker = await build_worker(
        database_url=database_url,
        worker_id=arguments.worker_id,
        max_attempts=arguments.max_attempts,
        base_backoff_seconds=arguments.base_backoff_seconds,
        claim_lease_seconds=arguments.claim_lease_seconds,
    )
    try:
        if arguments.command == "run-once":
            print(
                json.dumps(
                    {"handled": await worker.run_once()},
                    separators=(",", ":"),
                )
            )
            return 0
        if arguments.command == "run-until-idle":
            handled = await worker.run_until_idle(
                maximum_events=arguments.maximum_events
            )
            print(json.dumps({"handled": handled}, separators=(",", ":")))
            return 0
        if arguments.command == "retry":
            retried_state = await queue.manual_retry(
                event_id=UUID(arguments.event_id),
                operator=arguments.operator,
                now=datetime.now(timezone.utc),
            )
            print(json.dumps(_json_state(retried_state), separators=(",", ":")))
            return 0
        if arguments.command == "status":
            current_state = await queue.state(UUID(arguments.event_id))
            if current_state is None:
                print(
                    json.dumps(
                        {"errorCode": "outbox_event_not_found"},
                        separators=(",", ":"),
                    )
                )
                return 4
            print(json.dumps(_json_state(current_state), separators=(",", ":")))
            return 0
        raise RuntimeError(f"Unbekannter Worker-Befehl: {arguments.command}")
    finally:
        try:
            await worker.close()
        finally:
            await pool.close()


def _json_state(state: OutboxState) -> dict[str, object]:
    values = asdict(state)
    return {
        key: (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
        )
        for key, value in values.items()
    }


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description=__doc__)
    command_parser.add_argument(
        "--worker-id",
        default=f"{socket.gethostname()}-{os.getpid()}",
    )
    command_parser.add_argument("--max-attempts", type=int, default=5)
    command_parser.add_argument("--base-backoff-seconds", type=float, default=5)
    command_parser.add_argument("--claim-lease-seconds", type=float, default=300)
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("run-once")
    run_until_idle = subcommands.add_parser("run-until-idle")
    run_until_idle.add_argument("--maximum-events", type=int, default=10_000)
    retry = subcommands.add_parser("retry")
    retry.add_argument("event_id")
    retry.add_argument("--operator", required=True)
    status = subcommands.add_parser("status")
    status.add_argument("event_id")
    return command_parser


def main() -> None:
    raise SystemExit(asyncio.run(execute(parser().parse_args())))


if __name__ == "__main__":
    main()
