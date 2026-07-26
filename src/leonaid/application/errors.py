"""Application-level errors independent from HTTP."""

from __future__ import annotations


class ApplicationError(RuntimeError):
    """A safe error that may be translated by an entrypoint."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthenticationRequired(ApplicationError):
    """No currently valid server-side identity is available."""


class PermissionDenied(ApplicationError):
    """The authenticated identity is not allowed to perform the operation."""


class ResourceNotFound(ApplicationError):
    """A requested domain resource does not exist."""
