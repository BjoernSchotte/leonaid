"""How many test stacks one suite may run in parallel, and the slots they hold.

A suite's leaves are independent (each starts from the restored fixture), so
they can run on several private stacks. Each stack costs about 4 GiB, so:

- `LEONAID_TEST_STACKS=N` asks for N stacks explicitly;
- in CI (`CI` set) a suite uses 1 stack unless LEONAID_TEST_STACKS is set;
- otherwise a suite uses 2 stacks only if MemAvailable is at least
  `LEONAID_PARALLEL_MIN_MEM_GB` (default 14) at start, else 1;
- with `LEONAID_STACK_SLOTS_DIR` (the host's slot directory, e.g. the slot
  wrapper's), every additional stack must also take a free slot lock
  (`slot-1.lock` … `slot-<LEONAID_STACK_SLOTS>.lock`, default 5), so the
  host-wide slot cap still holds; without a free slot it runs fewer stacks.

Additional stacks need a prepared fixture to import (the host cache or CI's);
without one a suite stays on a single stack.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import TextIO

DEFAULT_MIN_MEM_GB = 14.0
DEFAULT_AUTO_STACKS = 2


def mem_available_gb(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        return None
    return None


def wanted(leaves: int, environ: dict[str, str] | None = None) -> tuple[int, str]:
    """(stack count, reason) before slots and fixture availability."""
    environ = dict(os.environ if environ is None else environ)
    explicit = environ.get("LEONAID_TEST_STACKS")
    if not explicit and environ.get("CI"):
        # CI runs one stack per job: deterministic timing and disk use.
        return 1, "CI (set LEONAID_TEST_STACKS to opt in)"
    if explicit:
        if not explicit.isdigit() or int(explicit) < 1:
            raise ValueError("LEONAID_TEST_STACKS must be a positive integer")
        count, reason = int(explicit), f"LEONAID_TEST_STACKS={explicit}"
    else:
        try:
            minimum = float(
                environ.get("LEONAID_PARALLEL_MIN_MEM_GB", DEFAULT_MIN_MEM_GB)
            )
        except ValueError:
            raise ValueError("LEONAID_PARALLEL_MIN_MEM_GB must be a number") from None
        available = mem_available_gb(
            Path(environ.get("LEONAID_MEMINFO", "/proc/meminfo"))
        )
        if available is not None and available >= minimum:
            count = DEFAULT_AUTO_STACKS
            reason = f"MemAvailable {available:.1f} GB >= {minimum:g} GB"
        else:
            count = 1
            shown = "unknown" if available is None else f"{available:.1f} GB"
            reason = f"MemAvailable {shown} < {minimum:g} GB"
    return max(1, min(count, leaves)), reason


def take_slots(extra: int, environ: dict[str, str] | None = None) -> list[TextIO]:
    """Lock up to `extra` free host slots; return the held lock files."""
    environ = dict(os.environ if environ is None else environ)
    directory = environ.get("LEONAID_STACK_SLOTS_DIR")
    if not directory or extra < 1:
        return []
    try:
        slots = int(environ.get("LEONAID_STACK_SLOTS", "5"))
    except ValueError:
        raise ValueError("LEONAID_STACK_SLOTS must be an integer") from None
    held: list[TextIO] = []
    for index in range(1, slots + 1):
        if len(held) == extra:
            break
        lock = (Path(directory) / f"slot-{index}.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            continue
        held.append(lock)
    return held
