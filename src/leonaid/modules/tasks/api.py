"""Typed task operations shared by HTTP and direct application callers."""

from datetime import date, datetime, timezone
from typing import Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    field_validator,
    model_validator,
    EmailStr,
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
)

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.navigation import NavigationItem
from leonaid.platform.http import TransportModel
from leonaid.modules.tasks.planning import require_time_zone

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
        "user_id",
        "assignee_user_id",
        "target_epic_id",
        "before",
        "after",
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
        "due_from",
        "due_before",
        "created_at",
        "updated_at",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def parse_timestamp(cls, value: object) -> object:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    @field_validator("planned_on", "target_date", mode="before", check_fields=False)
    @classmethod
    def parse_date(cls, value: object) -> object:
        return date.fromisoformat(value) if isinstance(value, str) else value


class CreateList(TaskModel):
    idempotency_key: UUID
    title: Title
    action_id: UUID | None = None


class TaskList(TaskModel):
    can_edit: bool
    id: UUID
    title: str
    action_id: UUID | None
    owner_user_id: UUID
    revision: int
    order_revision: int


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


class TaskSummary(Task):
    list_title: str
    action_title: str | None
    assignee_name: str | None
    epic_title: str | None
    can_edit: bool


class SearchPage(TaskModel):
    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)


class PlanQuery(TaskModel):
    view: Literal["today", "planned", "someday"]
    time_zone: str = Field(min_length=1, max_length=100)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        return require_time_zone(value)


class ListQuery(SearchPage):
    action_id: UUID | None = None


class TaskQuery(SearchPage):
    list_id: UUID | None = None
    for_me: bool = False
    status: Literal["open", "done"] | None = None
    include_deferred: bool | None = None
    due_from: AwareDatetime | None = None
    due_before: AwareDatetime | None = None
    deferred_state: Literal["active", "deferred", "all"] | None = None
    sort: Literal["created", "due", "section", "manual"] = "created"

    @model_validator(mode="after")
    def validate_filters(self) -> Self:
        if (
            self.due_from is not None
            and self.due_before is not None
            and self.due_from >= self.due_before
        ):
            raise ValueError("dueFrom muss vor dueBefore liegen.")
        if self.sort in ("section", "manual") and self.list_id is None:
            raise ValueError("Abschnitts- und manuelle Sortierung benötigen listId.")
        if self.deferred_state is not None and self.include_deferred is not None:
            legacy = "all" if self.include_deferred else "active"
            if self.deferred_state != legacy:
                raise ValueError(
                    "includeDeferred und deferredState widersprechen sich."
                )
        return self

    @property
    def effective_deferred_state(self) -> Literal["active", "deferred", "all"]:
        if self.deferred_state is not None:
            return self.deferred_state
        return "all" if self.include_deferred else "active"


class TaskLists(TaskModel):
    items: list[TaskList]
    next_offset: int | None


class Tasks(TaskModel):
    items: list[TaskSummary]
    next_offset: int | None
    order_revision: int | None


class SetTaskPlan(TaskModel):
    idempotency_key: UUID
    expected_revision: int = Field(ge=0)
    state: Literal["scheduled", "someday", "unplanned"]
    planned_on: date | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if (self.state == "scheduled") != (self.planned_on is not None):
            raise ValueError("Nur eine geplante Aufgabe benötigt ein Datum.")
        return self


class PersonalPlan(TaskModel):
    task_id: UUID
    state: Literal["scheduled", "someday", "unplanned"]
    planned_on: date | None
    revision: int


class PlannedTask(TaskSummary):
    personal_plan: PersonalPlan | None
    plan_source: Literal["planned", "due"]


class TaskPlans(TaskModel):
    items: list[PlannedTask]
    next_offset: int | None
    order_revision: int


class MovePlacement(TaskModel):
    before: UUID | None = None
    after: UUID | None = None
    edge: Literal["start", "end"] | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if (
            sum(value is not None for value in (self.before, self.after, self.edge))
            != 1
        ):
            raise ValueError("Genau ein Ziel für die Position ist erforderlich.")
        return self


class MoveTask(TaskModel):
    idempotency_key: UUID
    context: Literal["list", "personal"]
    target_epic_id: UUID | None = None
    target_date: date | None = None
    placement: MovePlacement
    expected_task_revision: int | None = Field(default=None, ge=1)
    expected_plan_revision: int | None = Field(default=None, ge=0)
    expected_order_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if self.context == "list":
            if (
                self.expected_task_revision is None
                or self.expected_plan_revision is not None
            ):
                raise ValueError("Listenreihenfolge benötigt nur die Task-Revision.")
            if self.target_date is not None:
                raise ValueError("Listenreihenfolge verwendet kein Planungsdatum.")
        elif (
            self.expected_plan_revision is None
            or self.expected_task_revision is not None
        ):
            raise ValueError("Persönliche Reihenfolge benötigt nur die Planrevision.")
        elif self.target_epic_id is not None:
            raise ValueError("Persönliche Reihenfolge verwendet keinen Abschnitt.")
        return self


class TaskMove(TaskModel):
    task_id: UUID
    context: Literal["list", "personal"]
    order_revision: int
    task_revision: int | None
    plan_revision: int | None


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


class SetListMember(TaskModel):
    idempotency_key: UUID
    expected_revision: int = Field(ge=1)
    user_id: UUID
    access: Literal["viewer", "editor"] | None


class SetListMemberByEmail(TaskModel):
    idempotency_key: UUID
    expected_revision: int = Field(ge=1)
    email: EmailStr
    access: Literal["viewer", "editor"]


class ListMember(TaskModel):
    user_id: UUID
    display_name: str
    access: Literal["viewer", "editor"]
    active: bool


class ListMembers(TaskModel):
    items: list[ListMember]
    owner_user_id: UUID
    revision: int
    next_offset: int | None


class Assignee(TaskModel):
    user_id: UUID
    display_name: str


class Assignees(TaskModel):
    items: list[Assignee]
    next_offset: int | None


class ActionContext(TaskModel):
    action_id: UUID
    name: str
    can_create_lists: bool


class ActionContexts(TaskModel):
    items: list[ActionContext]
    next_offset: int | None


class TaskRepository(Protocol):
    async def list_action_contexts(
        self, actor: IdentityPrincipal, query: SearchPage
    ) -> ActionContexts: ...

    async def set_list_member_by_email(
        self, actor: IdentityPrincipal, list_id: UUID, command: SetListMemberByEmail
    ) -> TaskList: ...

    async def list_assignees(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> Assignees: ...

    async def set_list_member(
        self, actor: IdentityPrincipal, list_id: UUID, command: SetListMember
    ) -> TaskList: ...
    async def list_members(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> ListMembers: ...
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
    async def list_task_plans(
        self, actor: IdentityPrincipal, query: PlanQuery
    ) -> TaskPlans: ...
    async def get_task_plan(
        self, actor: IdentityPrincipal, task_id: UUID
    ) -> PersonalPlan: ...
    async def set_task_plan(
        self, actor: IdentityPrincipal, task_id: UUID, command: SetTaskPlan
    ) -> PersonalPlan: ...
    async def move_task(
        self, actor: IdentityPrincipal, task_id: UUID, command: MoveTask
    ) -> TaskMove: ...
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

    async def list_assignees(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> Assignees:
        return await self._repository.list_assignees(
            actor, list_id, SearchPage.model_validate(query)
        )

    async def list_action_contexts(
        self, actor: IdentityPrincipal, query: SearchPage
    ) -> ActionContexts:
        return await self._repository.list_action_contexts(
            actor, SearchPage.model_validate(query)
        )

    async def set_list_member_by_email(
        self, actor: IdentityPrincipal, list_id: UUID, command: SetListMemberByEmail
    ) -> TaskList:
        return await self._repository.set_list_member_by_email(
            actor, list_id, SetListMemberByEmail.model_validate(command)
        )

    async def set_list_member(
        self, actor: IdentityPrincipal, list_id: UUID, command: SetListMember
    ) -> TaskList:
        return await self._repository.set_list_member(
            actor, list_id, SetListMember.model_validate(command)
        )

    async def list_members(
        self, actor: IdentityPrincipal, list_id: UUID, query: SearchPage
    ) -> ListMembers:
        return await self._repository.list_members(
            actor, list_id, SearchPage.model_validate(query)
        )

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

    async def list_task_plans(
        self, actor: IdentityPrincipal, query: PlanQuery
    ) -> TaskPlans:
        return await self._repository.list_task_plans(
            actor, PlanQuery.model_validate(query)
        )

    async def get_task_plan(
        self, actor: IdentityPrincipal, task_id: UUID
    ) -> PersonalPlan:
        return await self._repository.get_task_plan(actor, task_id)

    async def set_task_plan(
        self, actor: IdentityPrincipal, task_id: UUID, command: SetTaskPlan
    ) -> PersonalPlan:
        return await self._repository.set_task_plan(
            actor, task_id, SetTaskPlan.model_validate(command)
        )

    async def move_task(
        self, actor: IdentityPrincipal, task_id: UUID, command: MoveTask
    ) -> TaskMove:
        return await self._repository.move_task(
            actor, task_id, MoveTask.model_validate(command)
        )

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


def navigation(actor: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    if not actor.account.can_authenticate:
        return ()
    return (
        NavigationItem("tasks", "Aufgaben", "/admin/tasks", "web"),
        NavigationItem("tasks", "Aufgaben", "/app/tasks", "pwa"),
    )


__all__ = [
    "ActionContext",
    "ActionContexts",
    "SetListMemberByEmail",
    "Assignee",
    "Assignees",
    "navigation",
    "SetListMember",
    "ListMember",
    "ListMembers",
    "CreateEpic",
    "UpdateEpic",
    "Epic",
    "Epics",
    "SearchPage",
    "ListQuery",
    "PlanQuery",
    "PersonalPlan",
    "PlannedTask",
    "SetTaskPlan",
    "TaskPlans",
    "MovePlacement",
    "MoveTask",
    "TaskMove",
    "TaskQuery",
    "TaskLists",
    "Tasks",
    "CreateList",
    "CreateTask",
    "UpdateTask",
    "Task",
    "TaskSummary",
    "TaskList",
    "TaskService",
]
