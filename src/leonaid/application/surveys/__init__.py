"""Survey use cases expose a persistence port, independent of HTTP."""

from typing import Any, Protocol
from uuid import UUID

from leonaid.domain.identity import IdentityPrincipal


class SurveyRepository(Protocol):
    async def settings(
        self, actor: IdentityPrincipal, body: dict[str, Any] | None
    ) -> dict[str, Any]: ...

    async def author(
        self,
        actor: IdentityPrincipal,
        survey_id: UUID,
        operation: str,
        body: dict[str, Any],
    ) -> dict[str, Any]: ...
    async def participate(
        self,
        survey_id: UUID,
        participation_id: UUID | None,
        operation: str,
        body: dict[str, Any],
        secret: str,
    ) -> dict[str, Any]: ...


class SurveyService:
    def __init__(self, repository: SurveyRepository):
        self.repository = repository

    async def settings(
        self, actor: IdentityPrincipal, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        return await self.repository.settings(actor, body)

    async def author(
        self,
        actor: IdentityPrincipal,
        survey_id: UUID,
        operation: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.repository.author(actor, survey_id, operation, body)

    async def participate(
        self,
        survey_id: UUID,
        participation_id: UUID | None,
        operation: str,
        body: dict[str, Any],
        secret: str,
    ) -> dict[str, Any]:
        return await self.repository.participate(
            survey_id, participation_id, operation, body, secret
        )
