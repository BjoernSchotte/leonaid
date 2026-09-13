"""Typed knowledge operations shared by transport adapters and direct callers."""

from typing import Annotated, Any, Protocol
from uuid import UUID

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.http import TransportModel
from leonaid.modules.knowledge.document import validate_document
from leonaid.modules.tasks.api import CreateTask, Task

Document = Annotated[dict[str, Any], BeforeValidator(validate_document)]
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
]


class PageModel(TransportModel):
    model_config = ConfigDict(
        strict=True, revalidate_instances="always", validate_default=True
    )

    @field_validator(
        "id",
        "idempotency_key",
        "action_id",
        "owner_user_id",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def parse_identifier(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value


class CreatePage(PageModel):
    idempotency_key: UUID
    title: Title
    action_id: UUID | None = None
    content: Document = Field(
        default_factory=lambda: {"type": "doc", "content": [{"type": "paragraph"}]}
    )


class UpdatePage(PageModel):
    idempotency_key: UUID
    expected_revision: int = Field(ge=1)
    title: Title
    content: Document


class CreateTaskFromPage(CreateTask):
    list_id: UUID
    expected_revision: int = Field(ge=1)


class PageQuery(PageModel):
    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)
    action_id: UUID | None = None


class PageSummary(PageModel):
    id: UUID
    action_id: UUID | None
    owner_user_id: UUID
    revision: int = Field(ge=1)
    title: str


class Page(PageSummary):
    content: Document


class TaskFromPage(PageModel):
    page: Page
    task: Task


class Pages(PageModel):
    items: list[PageSummary]
    next_offset: int | None


class KnowledgeRepository(Protocol):
    async def create_task_from_page(
        self, actor: IdentityPrincipal, page_id: UUID, command: CreateTaskFromPage
    ) -> TaskFromPage: ...

    async def create_page(
        self, actor: IdentityPrincipal, command: CreatePage
    ) -> Page: ...
    async def update_page(
        self, actor: IdentityPrincipal, page_id: UUID, command: UpdatePage
    ) -> Page: ...
    async def get_page(self, actor: IdentityPrincipal, page_id: UUID) -> Page: ...
    async def list_pages(self, actor: IdentityPrincipal, query: PageQuery) -> Pages: ...


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    async def create_task_from_page(
        self, actor: IdentityPrincipal, page_id: UUID, command: CreateTaskFromPage
    ) -> TaskFromPage:
        return await self._repository.create_task_from_page(
            actor, page_id, CreateTaskFromPage.model_validate(command)
        )

    async def create_page(self, actor: IdentityPrincipal, command: CreatePage) -> Page:
        return await self._repository.create_page(
            actor, CreatePage.model_validate(command)
        )

    async def update_page(
        self, actor: IdentityPrincipal, page_id: UUID, command: UpdatePage
    ) -> Page:
        return await self._repository.update_page(
            actor, page_id, UpdatePage.model_validate(command)
        )

    async def get_page(self, actor: IdentityPrincipal, page_id: UUID) -> Page:
        return await self._repository.get_page(actor, page_id)

    async def list_pages(self, actor: IdentityPrincipal, query: PageQuery) -> Pages:
        return await self._repository.list_pages(actor, PageQuery.model_validate(query))


__all__ = [
    "CreateTaskFromPage",
    "TaskFromPage",
    "CreatePage",
    "UpdatePage",
    "PageQuery",
    "Page",
    "PageSummary",
    "Pages",
    "KnowledgeService",
]
