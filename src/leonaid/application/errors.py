"""Application-level errors independent from HTTP."""

from __future__ import annotations

from collections.abc import Mapping


class ApplicationError(RuntimeError):
    """A safe error that may be translated by an entrypoint."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        # JSON-safe facts a client needs to resolve the error (no personal data).
        self.details = dict(details) if details is not None else None


class AuthenticationRequired(ApplicationError):
    """No currently valid server-side identity is available."""


class PermissionDenied(ApplicationError):
    """The authenticated identity is not allowed to perform the operation."""


class ResourceNotFound(ApplicationError):
    """A requested domain resource does not exist."""


class Conflict(ApplicationError):
    """A requested mutation conflicts with current persisted state."""


class DependencyUnavailable(ApplicationError):
    """A required external dependency is not configured or available."""


class RateLimited(ApplicationError):
    """A public or authenticated operation exceeded its safe request budget."""
