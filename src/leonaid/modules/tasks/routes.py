"""Session-authenticated HTTP adapter for the shared task operations."""

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.modules.tasks.api import (
    Assignees,
    SetListMember,
    ListMembers,
    CreateEpic,
    UpdateEpic,
    Epic,
    Epics,
    SearchPage,
    CreateList,
    CreateTask,
    UpdateTask,
    Task,
    TaskList,
    Tasks,
    TaskLists,
    TaskQuery,
    ListQuery,
    TaskService,
)
from leonaid.platform.http import ApiErrorResponse

router = APIRouter(
    prefix="/api/v1",
    tags=["tasks"],
    responses={
        code: {"model": ApiErrorResponse}
        for code in (401, 403, 404, 409, 422, 429, 503)
    },
)


async def actor(request: Request, response: Response) -> IdentityPrincipal:
    response.headers["Cache-Control"] = "no-store"
    return cast(
        IdentityPrincipal,
        await request.app.state.identity_service.authenticate(
            request.cookies.get(SESSION_COOKIE_NAME)
        ),
    )


def service(request: Request) -> TaskService:
    return cast(TaskService, request.app.state.task_service)


@router.post("/task-lists", operation_id="createTaskList", response_model=TaskList)
async def create_list(
    request: Request, response: Response, body: CreateList
) -> TaskList:
    return await service(request).create_list(await actor(request, response), body)


@router.get("/task-lists", operation_id="listTaskLists", response_model=TaskLists)
async def list_lists(
    request: Request,
    response: Response,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
    action_id: UUID | None = Query(default=None, alias="actionId"),
) -> TaskLists:
    return await service(request).list_lists(
        await actor(request, response),
        ListQuery(search=search, offset=offset, limit=limit, action_id=action_id),
    )


@router.get(
    "/task-lists/{list_id}", operation_id="getTaskList", response_model=TaskList
)
async def get_list(request: Request, response: Response, list_id: UUID) -> TaskList:
    return await service(request).get_list(await actor(request, response), list_id)


@router.post(
    "/task-lists/{list_id}/tasks", operation_id="createTask", response_model=Task
)
async def create_task(
    request: Request, response: Response, list_id: UUID, body: CreateTask
) -> Task:
    return await service(request).create_task(
        await actor(request, response), list_id, body
    )


@router.get("/tasks", operation_id="listTasks", response_model=Tasks)
async def list_tasks(
    request: Request,
    response: Response,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
    list_id: UUID | None = Query(default=None, alias="listId"),
    for_me: bool = Query(default=False, alias="forMe"),
    status: Literal["open", "done"] | None = None,
    include_deferred: bool = Query(default=False, alias="includeDeferred"),
) -> Tasks:
    return await service(request).list_tasks(
        await actor(request, response),
        TaskQuery(
            search=search,
            offset=offset,
            limit=limit,
            list_id=list_id,
            for_me=for_me,
            status=status,
            include_deferred=include_deferred,
        ),
    )


@router.get("/tasks/{task_id}", operation_id="getTask", response_model=Task)
async def get_task(request: Request, response: Response, task_id: UUID) -> Task:
    return await service(request).get_task(await actor(request, response), task_id)


@router.put("/tasks/{task_id}", operation_id="updateTask", response_model=Task)
async def update_task(
    request: Request, response: Response, task_id: UUID, body: UpdateTask
) -> Task:
    return await service(request).update_task(
        await actor(request, response), task_id, body
    )


@router.post(
    "/task-lists/{list_id}/epics", operation_id="createTaskEpic", response_model=Epic
)
async def create_epic(
    request: Request, response: Response, list_id: UUID, body: CreateEpic
) -> Epic:
    return await service(request).create_epic(
        await actor(request, response), list_id, body
    )


@router.put("/task-epics/{epic_id}", operation_id="updateTaskEpic", response_model=Epic)
async def update_epic(
    request: Request, response: Response, epic_id: UUID, body: UpdateEpic
) -> Epic:
    return await service(request).update_epic(
        await actor(request, response), epic_id, body
    )


@router.get(
    "/task-lists/{list_id}/epics", operation_id="listTaskEpics", response_model=Epics
)
async def list_epics(
    request: Request,
    response: Response,
    list_id: UUID,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> Epics:
    return await service(request).list_epics(
        await actor(request, response),
        list_id,
        SearchPage(search=search, offset=offset, limit=limit),
    )


@router.put(
    "/task-lists/{list_id}/members",
    operation_id="setTaskListMember",
    response_model=TaskList,
)
async def set_list_member(
    request: Request, response: Response, list_id: UUID, body: SetListMember
) -> TaskList:
    return await service(request).set_list_member(
        await actor(request, response), list_id, body
    )


@router.get(
    "/task-lists/{list_id}/members",
    operation_id="listTaskListMembers",
    response_model=ListMembers,
)
async def list_members(
    request: Request,
    response: Response,
    list_id: UUID,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> ListMembers:
    return await service(request).list_members(
        await actor(request, response),
        list_id,
        SearchPage(search=search, offset=offset, limit=limit),
    )


@router.get(
    "/task-lists/{list_id}/assignees",
    operation_id="listTaskAssignees",
    response_model=Assignees,
)
async def list_assignees(
    request: Request,
    response: Response,
    list_id: UUID,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> Assignees:
    return await service(request).list_assignees(
        await actor(request, response),
        list_id,
        SearchPage(search=search, offset=offset, limit=limit),
    )
