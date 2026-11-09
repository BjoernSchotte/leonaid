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
only if the settled state at the end of a leaf is still its baseline and no
Twenty request is in flight (busy), and then clears the rate limits.
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
PSQL = 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"'
# Client backends other than this query that are not idle: a Twenty request
# in flight that may write after the check (an open write is in the snapshot).
BUSY = (
    "select count(*) from pg_stat_activity where backend_type = 'client backend'"
    " and pid <> pg_backend_pid() and state is distinct from 'idle'"
)
# Twenty's API rate limits (ThrottlerService), namespaced in the cache. Not
# part of the state: every read uses them. Cleared for a kept Twenty, so a
# leaf never starts on a bucket the leaf before drained.
CLEAR_RATE_LIMITS = """
local keys = redis.call('KEYS', '*token-bucket:*')
for _, key in ipairs(keys) do redis.call('DEL', key) end
return #keys
"""


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
    snapshot = run(postgres, "sh", "-c", PSQL, "sh", "select pg_current_snapshot()")
    listing = run(queue, "valkey-cli", "EVAL", QUEUE_LISTING, "0")
    return f"snapshot {snapshot}\n{listing}\n"


def run(name: str, *command: str) -> str:
    return subprocess.run(
        ["docker", "exec", name, *command],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def busy(project: str) -> int:
    """Twenty database requests in flight (BUSY)."""
    postgres = container(project, "twenty-postgres")
    if postgres is None:
        raise RuntimeError("twenty-postgres is not running")
    return int(run(postgres, "sh", "-c", PSQL, "sh", BUSY))


def clear_rate_limits(project: str) -> None:
    queue = container(project, "twenty-redis")
    if queue is None:
        raise RuntimeError("twenty-redis is not running")
    run(queue, "valkey-cli", "EVAL", CLEAR_RATE_LIMITS, "0")


def change(before: str, after: str) -> str:
    """A short log text: transactions and BullMQ keys since the baseline."""

    def split(state: str) -> tuple[int, set[str]]:
        first, *listing = state.splitlines()
        # "snapshot xmin:xmax:xip,..."; xmax is the next transaction ID.
        return int(first.split()[1].split(":")[1]), set(listing)

    xid_before, keys_before = split(before)
    xid_after, keys_after = split(after)
    jobs = sorted({line.split()[0] for line in keys_after ^ keys_before}, key=str)
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
