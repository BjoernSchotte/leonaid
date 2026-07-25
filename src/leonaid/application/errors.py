"""Application-level errors independent from HTTP."""

from __future__ import annotations


class ApplicationError(RuntimeError):
    """A safe error that may be translated by an entrypoint."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
