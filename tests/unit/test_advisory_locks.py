"""Every integer advisory lock of Core has its own key.

PostgreSQL knows one key space per database for ``pg_advisory_lock(bigint)``.
Two features that pick the same number exclude each other silently: the
delivery-day mail sweep once shared its key with the sponsor search sync and
would have skipped its runs while a sync ran.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "leonaid"
# ``SOME_LOCK = 527061`` at module level.
NAMED = re.compile(
    r"^([A-Z][A-Z0-9_]*LOCK[A-Z0-9_]*)\s*(?::\s*int\s*)?=\s*(\d+)\s*$", re.M
)
# ``pg_advisory_xact_lock(527052)`` with the key written into the SQL.
LITERAL = re.compile(r"pg_(?:try_)?advisory_(?:xact_)?lock(?:_shared)?\((\d+)\)")


def lock_keys() -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    named: dict[int, set[str]] = defaultdict(set)
    literal: dict[int, set[str]] = defaultdict(set)
    for path in sorted(SOURCE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        where = str(path.relative_to(SOURCE))
        for name, key in NAMED.findall(text):
            named[int(key)].add(f"{where}:{name}")
        for key in LITERAL.findall(text):
            literal[int(key)].add(where)
    return named, literal


def test_every_named_advisory_lock_has_its_own_key() -> None:
    named, literal = lock_keys()

    # The scan sees the locks it is meant to guard.
    names = {item.rsplit(":", 1)[1] for owners in named.values() for item in owners}
    assert {
        "DELIVERY_DAY_SWEEP_LOCK",
        "SPONSOR_SEARCH_SYNC_LOCK",
        "SITE_HOST_LOCK",
        "TLS_APPROVAL_LOCK",
        "SITE_HOST_RECHECK_LOCK",
    } <= names
    shared = {key: sorted(owners) for key, owners in named.items() if len(owners) > 1}
    assert shared == {}
    # A key written into SQL belongs to one feature too (the campaign alias
    # lock is taken in several statements of that feature).
    reused = {key: sorted(literal[key]) for key in named if key in literal}
    assert reused == {}


def test_the_scan_finds_a_shared_key() -> None:
    text = "FIRST_LOCK = 7\nSECOND_SYNC_LOCK: int = 7\nOTHER = 7\n"

    assert NAMED.findall(text) == [("FIRST_LOCK", "7"), ("SECOND_SYNC_LOCK", "7")]
    assert LITERAL.findall("SELECT pg_try_advisory_xact_lock(527052)") == ["527052"]
    assert LITERAL.findall("SELECT pg_advisory_lock_shared(1)") == ["1"]
