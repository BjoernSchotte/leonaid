"""Authenticated HTTP adapter for internal Inbox case operations."""

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.modules.inbox.api import (
    AddComment,
    Comment,
    CommentQuery,
    Comments,
    AssigneeQuery,
    Assignees,
    Case,
    CaseQuery,
    Cases,
    InboxService,
    UpdateCase,
    SubmitCase,
    Submission,
)
from leonaid.platform.http import ApiErrorResponse

router = APIRouter(
    prefix="/api/v1",
    tags=["inbox"],
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


def service(request: Request) -> InboxService:
    return cast(InboxService, request.app.state.inbox_service)


@router.get("/inbox-cases", operation_id="listInboxCases", response_model=Cases)
async def list_cases(
    request: Request,
    response: Response,
    search: str = Query(default="", max_length=200),
    action_id: UUID | None = Query(default=None, alias="actionId"),
    status: Literal["new", "in_progress", "closed"] | None = None,
    for_me: bool = Query(default=False, alias="forMe"),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> Cases:
    return await service(request).list_cases(
        await actor(request, response),
        CaseQuery(
            search=search,
            action_id=action_id,
            status=status,
            for_me=for_me,
            offset=offset,
            limit=limit,
        ),
    )


@router.get("/inbox-cases/{case_id}", operation_id="getInboxCase", response_model=Case)
async def get_case(request: Request, response: Response, case_id: UUID) -> Case:
    return await service(request).get_case(await actor(request, response), case_id)


@router.get(
    "/inbox-cases/{case_id}/assignees",
    operation_id="listInboxAssignees",
    response_model=Assignees,
)
async def list_assignees(
    request: Request,
    response: Response,
    case_id: UUID,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> Assignees:
    return await service(request).list_assignees(
        await actor(request, response),
        case_id,
        AssigneeQuery(search=search, offset=offset, limit=limit),
    )


@router.get(
    "/inbox-cases/{case_id}/comments",
    operation_id="listInboxComments",
    response_model=Comments,
)
async def list_comments(
    request: Request,
    response: Response,
    case_id: UUID,
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> Comments:
    return await service(request).list_comments(
        await actor(request, response),
        case_id,
        CommentQuery(offset=offset, limit=limit),
    )


@router.post(
    "/inbox-cases/{case_id}/comments",
    operation_id="addInboxComment",
    response_model=Comment,
    status_code=201,
)
async def add_comment(
    request: Request, response: Response, case_id: UUID, body: AddComment
) -> Comment:
    return await service(request).add_comment(
        await actor(request, response), case_id, body
    )


@router.put(
    "/inbox-cases/{case_id}", operation_id="updateInboxCase", response_model=Case
)
async def update_case(
    request: Request, response: Response, case_id: UUID, body: UpdateCase
) -> Case:
    return await service(request).update_case(
        await actor(request, response), case_id, body
    )


@router.post(
    "/public/inbox-cases/",
    response_model=Submission,
    status_code=201,
    include_in_schema=False,
)
@router.post(
    "/public/inbox-cases",
    operation_id="submitInboxCase",
    response_model=Submission,
    status_code=201,
)
async def submit_case(
    request: Request, response: Response, body: SubmitCase
) -> Submission:
    response.headers["Cache-Control"] = "no-store"
    return await service(request).submit(body)
