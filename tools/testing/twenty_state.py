"""Write detector for a Twenty kept across leaf resets (decision E-033).

The state is the transaction snapshot of the Twenty database plus a listing of
its BullMQ keys in Valkey. A write transaction advances the snapshot at
commit; pg_stat_database counters would show it only when the backend flushes
its statistics, seconds later. A job that is enqueued, scheduled, run or
finished changes the listing. The test runtime turns autovacuum off
(shared-runtime.yml), so an idle Twenty keeps one state.

`settle <project> <file>` waits until no job is pending and the state holds
still, then writes it: the baseline of a leaf that seeded a freshly restored
Twenty (owned_teardown.sh golden_seed). Before a leaf on a kept Twenty,
shared_stack.py writes the baseline itself. It keeps Twenty for the next leaf
only if the state at the end of a leaf is still its baseline.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

# Sorted "key type size" lines of every BullMQ key, strings with their value
# (job ID counters). stalled-check is the workers' own lock that comes and
# goes on a timer, not queue content.
QUEUE_LISTING = """
local lines = {}
for _, key in ipairs(redis.call('KEYS', 'bull:*')) do
  if not string.find(key, ':stalled%-check$') then
    local kind = redis.call('TYPE', key).ok
    local size = ''
    if kind == 'string' then size = redis.call('GET', key)
    elseif kind == 'list' then size = redis.call('LLEN', key)
    elseif kind == 'set' then size = redis.call('SCARD', key)
    elseif kind == 'zset' then size = redis.call('ZCARD', key)
    elseif kind == 'hash' then size = redis.call('HLEN', key)
    elseif kind == 'stream' then size = redis.call('XLEN', key) end
    table.insert(lines, key .. ' ' .. kind .. ' ' .. tostring(size))
  end
end
table.sort(lines)
return table.concat(lines, '\\n')
"""
# BullMQ keys of jobs that run now. A delayed job stays part of the state: if
# it runs later, the state changes and Twenty is reset.
PENDING = (":wait ", ":active ", ":prioritized ")
SNAPSHOT = (
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc '
    '"select pg_current_snapshot()"'
)


def container(project: str, service: str) -> str | None:
    found = subprocess.run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return found[0] if len(found) == 1 else None


def read(project: str) -> str | None:
    """The current state, or None when Twenty's stores are not both running."""
    postgres = container(project, "twenty-postgres")
    queue = container(project, "twenty-redis")
    if postgres is None or queue is None:
        return None
    snapshot = subprocess.run(
        ["docker", "exec", postgres, "sh", "-c", SNAPSHOT],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    listing = subprocess.run(
        ["docker", "exec", queue, "valkey-cli", "EVAL", QUEUE_LISTING, "0"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return f"snapshot {snapshot}\n{listing}\n"


def change(before: str, after: str) -> str:
    """A short log text: transactions and BullMQ keys since the baseline."""

    def split(state: str) -> tuple[int, set[str]]:
        first, *listing = state.splitlines()
        # "snapshot xmin:xmax:xip,..."; xmax is the next transaction ID.
        return int(first.split()[1].split(":")[1]), set(listing)

    xid_before, keys_before = split(before)
    xid_after, keys_after = split(after)
    jobs = sorted(
        {line.split()[0] for line in keys_after ^ keys_before}, key=str
    )
    return f"{xid_after - xid_before} transaction(s), BullMQ keys changed: " + (
        ", ".join(jobs[:5]) + (" ..." if len(jobs) > 5 else "") if jobs else "none"
    )


def pending(state: str) -> bool:
    return any(
        marker in line and not line.endswith(" 0")
        for line in state.splitlines()
        for marker in PENDING
    )


def settle(project: str, timeout: float = 30) -> str:
    """The state once no job is pending and it holds still for two seconds."""
    deadline = time.monotonic() + timeout
    previous = None
    while True:
        state = read(project)
        if state is None:
            raise RuntimeError("Twenty stores are not running; nothing to settle")
        if state == previous and not pending(state):
            return state
        if time.monotonic() > deadline:
            raise RuntimeError(f"Twenty did not settle in {timeout:.0f}s")
        previous = state
        time.sleep(2)


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] != "settle":
        print("usage: twenty_state.py settle <project> <file>", file=sys.stderr)
        return 64
    try:
        state = settle(sys.argv[2])
    except RuntimeError as error:
        # Without a baseline the next leaf gets a fresh Twenty: slower, not wrong.
        print(f"twenty-state: {error}; the next leaf resets Twenty", flush=True)
        return 0
    Path(sys.argv[3]).write_text(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
