"""Domain errors with stable, transport-independent codes."""

from __future__ import annotations


class DomainInvariantError(ValueError):
    """A value cannot exist in the LeonAid domain."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
