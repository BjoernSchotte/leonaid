"""Filesystem-backed maintenance boundary shared by every API write route."""

from __future__ import annotations

from pathlib import Path

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def writes_are_blocked(method: str, flag_path: Path) -> bool:
    """Return whether this concrete HTTP request crosses the write boundary."""

    return method.upper() in WRITE_METHODS and flag_path.is_file()
