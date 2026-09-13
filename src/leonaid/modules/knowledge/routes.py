"""Session-authenticated HTTP adapter for knowledge operations."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.modules.knowledge.api import (
    MemberQuery,
    SetPageMember,
    SetPageMemberByEmail,
    PageAccess,
    PageMembers,
    CreatePage,
    CreateTaskFromPage,
    TaskFromPage,
    UpdatePage,
    Page,
    Pages,
    PageQuery,
    KnowledgeService,
)
from leonaid.platform.http import ApiErrorResponse

router = APIRouter(
    prefix="/api/v1/knowledge-pages",
    tags=["knowledge"],
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


def service(request: Request) -> KnowledgeService:
    return cast(KnowledgeService, request.app.state.knowledge_service)


@router.post("", operation_id="createKnowledgePage", response_model=Page)
async def create_page(request: Request, response: Response, body: CreatePage) -> Page:
    return await service(request).create_page(await actor(request, response), body)


@router.get("", operation_id="listKnowledgePages", response_model=Pages)
async def list_pages(
    request: Request,
    response: Response,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
    action_id: UUID | None = Query(default=None, alias="actionId"),
) -> Pages:
    return await service(request).list_pages(
        await actor(request, response),
        PageQuery(search=search, offset=offset, limit=limit, action_id=action_id),
    )


@router.get("/{page_id}", operation_id="getKnowledgePage", response_model=Page)
async def get_page(request: Request, response: Response, page_id: UUID) -> Page:
    return await service(request).get_page(await actor(request, response), page_id)


@router.put("/{page_id}", operation_id="updateKnowledgePage", response_model=Page)
async def update_page(
    request: Request, response: Response, page_id: UUID, body: UpdatePage
) -> Page:
    return await service(request).update_page(
        await actor(request, response), page_id, body
    )


@router.post(
    "/{page_id}/tasks",
    operation_id="createTaskFromKnowledgePage",
    response_model=TaskFromPage,
)
async def create_task_from_page(
    request: Request, response: Response, page_id: UUID, body: CreateTaskFromPage
) -> TaskFromPage:
    return await service(request).create_task_from_page(
        await actor(request, response), page_id, body
    )


@router.put(
    "/{page_id}/members",
    operation_id="setKnowledgePageMember",
    response_model=PageAccess,
)
async def set_page_member(
    request: Request, response: Response, page_id: UUID, body: SetPageMember
) -> PageAccess:
    return await service(request).set_page_member(
        await actor(request, response), page_id, body
    )


@router.put(
    "/{page_id}/members/by-email",
    operation_id="setKnowledgePageMemberByEmail",
    response_model=PageAccess,
)
async def set_page_member_by_email(
    request: Request, response: Response, page_id: UUID, body: SetPageMemberByEmail
) -> PageAccess:
    return await service(request).set_page_member_by_email(
        await actor(request, response), page_id, body
    )


@router.get(
    "/{page_id}/members",
    operation_id="listKnowledgePageMembers",
    response_model=PageMembers,
)
async def list_members(
    request: Request,
    response: Response,
    page_id: UUID,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> PageMembers:
    return await service(request).list_members(
        await actor(request, response),
        page_id,
        MemberQuery(search=search, offset=offset, limit=limit),
    )
