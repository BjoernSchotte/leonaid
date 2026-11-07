"""Pytest plugin: run one deterministic shard of the collected tests.

`LEONAID_PYTEST_SHARD=<index>/<count>` (0-based) keeps every test whose
position in the collection order is `index` modulo `count`, so `count`
processes with indexes 0..count-1 run every test exactly once. Without the
variable the plugin changes nothing. Used by ./leonaid check to spread the
exhaustive survey disclosure solver proof over several processes.
"""

from __future__ import annotations

import os

import pytest


def shard() -> tuple[int, int] | None:
    value = os.environ.get("LEONAID_PYTEST_SHARD")
    if not value:
        return None
    index, count = (int(part) for part in value.split("/", 1))
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError(f"Invalid LEONAID_PYTEST_SHARD={value}")
    return index, count


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    selected = shard()
    if selected is None:
        return
    index, count = selected
    kept = [item for position, item in enumerate(items) if position % count == index]
    dropped = [item for position, item in enumerate(items) if position % count != index]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
