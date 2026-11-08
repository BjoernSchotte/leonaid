"""Pytest plugin: run one deterministic shard of the collected tests.

`LEONAID_PYTEST_SHARD=<index>/<count>` (0-based) keeps every test whose
position in the collection order is `index` modulo `count`, so `count`
processes with indexes 0..count-1 run every test exactly once. Without the
variable the plugin changes nothing. Used by ./leonaid check and
tools/ci/unit.sh to spread the exhaustive survey disclosure solver proof over
several processes.

`LEONAID_PYTEST_WEIGHTS=<file>` ({node id: seconds}) balances the shards by
measured duration instead (``assign``); the shards still partition the
collection exactly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def shard() -> tuple[int, int] | None:
    value = os.environ.get("LEONAID_PYTEST_SHARD")
    if not value:
        return None
    index, count = (int(part) for part in value.split("/", 1))
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError(f"Invalid LEONAID_PYTEST_SHARD={value}")
    return index, count


def weights() -> dict[str, float]:
    """Optional measured seconds per node id (LEONAID_PYTEST_WEIGHTS file)."""
    path = os.environ.get("LEONAID_PYTEST_WEIGHTS")
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise pytest.UsageError(f"Unreadable LEONAID_PYTEST_WEIGHTS={path}: {error}")
    if not isinstance(data, dict) or not all(
        isinstance(value, (int, float)) and value >= 0 for value in data.values()
    ):
        raise pytest.UsageError(
            f"LEONAID_PYTEST_WEIGHTS={path}: expected {{nodeid: seconds}}"
        )
    return {str(key): float(value) for key, value in data.items()}


def assign(nodeids: list[str], count: int, weight: dict[str, float]) -> list[int]:
    """Shard of every collected position; the same in every shard process.

    Without weights: position modulo count. With weights: longest first onto
    the least-loaded shard (ties: collection order, lowest shard). A test
    without a weight counts as the smallest known weight (or 1), so a new
    test changes the balance, never the coverage: every position gets
    exactly one shard either way.
    """
    if not weight:
        return [position % count for position in range(len(nodeids))]
    default = min(weight.values(), default=1.0) or 1.0
    order = sorted(
        range(len(nodeids)), key=lambda p: (-weight.get(nodeids[p], default), p)
    )
    loads = [0.0] * count
    owner = [0] * len(nodeids)
    for position in order:
        shard_index = min(range(count), key=lambda i: (loads[i], i))
        owner[position] = shard_index
        loads[shard_index] += weight.get(nodeids[position], default)
    return owner


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    selected = shard()
    if selected is None:
        return
    index, count = selected
    owner = assign([item.nodeid for item in items], count, weights())
    kept = [item for position, item in enumerate(items) if owner[position] == index]
    dropped = [item for position, item in enumerate(items) if owner[position] != index]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
