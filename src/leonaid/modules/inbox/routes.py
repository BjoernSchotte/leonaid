"""Authenticated HTTP adapter for internal Inbox case operations."""

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.modules.inbox.api import Case, CaseQuery, Cases, InboxService, UpdateCase
from leonaid.platform.http import ApiErrorResponse

router = APIRouter(
    prefix="/api/v1/inbox-cases",
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


@router.get("", operation_id="listInboxCases", response_model=Cases)
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


@router.get("/{case_id}", operation_id="getInboxCase", response_model=Case)
async def get_case(request: Request, response: Response, case_id: UUID) -> Case:
    return await service(request).get_case(await actor(request, response), case_id)


@router.put("/{case_id}", operation_id="updateInboxCase", response_model=Case)
async def update_case(
    request: Request, response: Response, case_id: UUID, body: UpdateCase
) -> Case:
    return await service(request).update_case(
        await actor(request, response), case_id, body
    )
