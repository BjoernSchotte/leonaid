"""Typed task operations shared by HTTP and direct application callers."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import (
    field_validator,
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
)

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.http import TransportModel

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
]


class TaskModel(TransportModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, revalidate_instances="always"
    )

    @field_validator(
        "id",
        "idempotency_key",
        "action_id",
        "list_id",
        "epic_id",
        "owner_user_id",
        "assignee_user_id",
        "created_by",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def parse_identifier(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @field_validator(
        "due_at",
        "deferred_until",
        "created_at",
        "updated_at",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def parse_timestamp(cls, value: object) -> object:
        return datetime.fromisoformat(value) if isinstance(value, str) else value


class CreateList(TaskModel):
    idempotency_key: UUID
    title: Title
    action_id: UUID | None = None


class TaskList(TaskModel):
    id: UUID
    title: str
    action_id: UUID | None
    owner_user_id: UUID
    revision: int


class TaskFields(TaskModel):
    title: Title
    description: str = Field(default="", max_length=10000)
    epic_id: UUID | None = None
    assignee_user_id: UUID | None = None
    due_at: AwareDatetime | None = None
    deferred_until: AwareDatetime | None = None

    @field_validator("due_at", "deferred_until")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(timezone.utc) if value is not None else None


class CreateTask(TaskFields):
    idempotency_key: UUID


class UpdateTask(TaskFields):
    idempotency_key: UUID
    expected_revision: int = Field(ge=1)
    status: Literal["open", "done"]


class Task(TaskFields):
    id: UUID
    list_id: UUID
    status: Literal["open", "done"]
    revision: int
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class SearchPage(TaskModel):
    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)


class ListQuery(SearchPage):
    action_id: UUID | None = None


class TaskQuery(SearchPage):
    list_id: UUID | None = None
    for_me: bool = False
    status: Literal["open", "done"] | None = None
    include_deferred: bool = False


class TaskLists(TaskModel):
    items: list[TaskList]
    next_offset: int | None


class Tasks(TaskModel):
    items: list[Task]
    next_offset: int | None


class CreateEpic(TaskModel):
    idempotency_key: UUID
    title: Title


class UpdateEpic(CreateEpic):
    expected_revision: int = Field(ge=1)


class Epic(TaskModel):
    id: UUID
    list_id: UUID
    title: str
    revision: int


class Epics(TaskModel):
    items: list[Epic]
    next_offset: int | None


class TaskRepository(Protocol):
    async def create_epic(
        self, actor: IdentityPrincipal, list_id: UUID, command: CreateEpic
    ) -> Epic: ...
    async def update_epic(
        self, actor: IdentityPrincipal, epic_id: UUID, command: UpdateEpic
    ) -> Epic: ...
    async def list_epics(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> Epics: ...
    async def list_lists(
        self, actor: IdentityPrincipal, query: ListQuery
    ) -> TaskLists: ...
    async def list_tasks(self, actor: IdentityPrincipal, query: TaskQuery) -> Tasks: ...
    async def create_list(
        self, actor: IdentityPrincipal, command: CreateList
    ) -> TaskList: ...
    async def get_list(self, actor: IdentityPrincipal, list_id: UUID) -> TaskList: ...
    async def create_task(
        self, actor: IdentityPrincipal, list_id: UUID, command: CreateTask
    ) -> Task: ...
    async def update_task(
        self, actor: IdentityPrincipal, task_id: UUID, command: UpdateTask
    ) -> Task: ...
    async def get_task(self, actor: IdentityPrincipal, task_id: UUID) -> Task: ...


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def create_epic(
        self, actor: IdentityPrincipal, list_id: UUID, command: CreateEpic
    ) -> Epic:
        return await self._repository.create_epic(
            actor, list_id, CreateEpic.model_validate(command)
        )

    async def update_epic(
        self, actor: IdentityPrincipal, epic_id: UUID, command: UpdateEpic
    ) -> Epic:
        return await self._repository.update_epic(
            actor, epic_id, UpdateEpic.model_validate(command)
        )

    async def list_epics(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> Epics:
        return await self._repository.list_epics(
            actor, list_id, SearchPage.model_validate(query)
        )

    async def list_lists(self, actor: IdentityPrincipal, query: ListQuery) -> TaskLists:
        return await self._repository.list_lists(actor, ListQuery.model_validate(query))

    async def list_tasks(self, actor: IdentityPrincipal, query: TaskQuery) -> Tasks:
        return await self._repository.list_tasks(actor, TaskQuery.model_validate(query))

    async def create_list(
        self, actor: IdentityPrincipal, command: CreateList
    ) -> TaskList:
        return await self._repository.create_list(
            actor, CreateList.model_validate(command)
        )

    async def get_list(self, actor: IdentityPrincipal, list_id: UUID) -> TaskList:
        return await self._repository.get_list(actor, list_id)

    async def create_task(
        self, actor: IdentityPrincipal, list_id: UUID, command: CreateTask
    ) -> Task:
        return await self._repository.create_task(
            actor, list_id, CreateTask.model_validate(command)
        )

    async def update_task(
        self, actor: IdentityPrincipal, task_id: UUID, command: UpdateTask
    ) -> Task:
        return await self._repository.update_task(
            actor, task_id, UpdateTask.model_validate(command)
        )

    async def get_task(self, actor: IdentityPrincipal, task_id: UUID) -> Task:
        return await self._repository.get_task(actor, task_id)


__all__ = [
    "CreateEpic",
    "UpdateEpic",
    "Epic",
    "Epics",
    "SearchPage",
    "ListQuery",
    "TaskQuery",
    "TaskLists",
    "Tasks",
    "CreateList",
    "CreateTask",
    "UpdateTask",
    "Task",
    "TaskList",
    "TaskService",
]
