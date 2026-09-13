"""Typed task operations shared by HTTP and direct application callers."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import (
    field_validator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

from leonaid.domain.identity import IdentityPrincipal

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
]


class TaskModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, revalidate_instances="always"
    )


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


class TaskRepository(Protocol):
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


__all__ = ["CreateList", "CreateTask", "UpdateTask", "Task", "TaskList", "TaskService"]
