"""Session-authenticated multipart upload and protected attachment downloads."""

from typing import cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.modules.materials.api import (
    MAX_UPLOAD_BYTES,
    MemberQuery,
    SetMaterialMember,
    SetMaterialMemberByEmail,
    MaterialAccess,
    MaterialMembers,
    MaterialPermissions,
    AddVersion,
    CreateMaterial,
    Material,
    Materials,
    MaterialQuery,
    MaterialService,
    MaterialVersion,
)
from leonaid.platform.http import ApiErrorResponse

router = APIRouter(
    prefix="/api/v1/materials",
    tags=["materials"],
    responses={
        code: {"model": ApiErrorResponse}
        for code in (401, 403, 404, 409, 413, 422, 503)
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


def service(request: Request) -> MaterialService:
    return cast(MaterialService, request.app.state.material_service)


async def content(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not 1 <= len(data) <= MAX_UPLOAD_BYTES:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "file"),
                    "type": "value_error",
                    "msg": "Datei muss zwischen einem Byte und 25 MiB groß sein.",
                }
            ]
        )
    return data


async def strict_form(request: Request, allowed: set[str]) -> None:
    form = await request.form()
    names = [key for key, _value in form.multi_items()]
    if len(names) != len(set(names)) or set(names) - allowed:
        raise RequestValidationError(
            [
                {
                    "loc": ("body",),
                    "type": "value_error",
                    "msg": "Unbekannte oder doppelte Formularfelder.",
                }
            ]
        )


@router.post("", operation_id="createMaterial", response_model=Material)
async def create_material(
    request: Request,
    response: Response,
    file: UploadFile = File(),
    title: str = Form(min_length=1, max_length=240),
    idempotencyKey: UUID = Form(),
    actionId: UUID | None = Form(default=None),
) -> Material:
    principal = await actor(request, response)
    await strict_form(request, {"file", "title", "idempotencyKey", "actionId"})
    try:
        command = CreateMaterial(
            idempotency_key=idempotencyKey,
            title=title,
            action_id=actionId,
            filename=file.filename or "",
            media_type=(file.content_type or "application/octet-stream")
            .split(";", 1)[0]
            .strip()
            .lower(),
        )
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error
    return await service(request).create_material(
        principal, command, await content(file)
    )


@router.post(
    "/{material_id}/versions",
    operation_id="addMaterialVersion",
    response_model=Material,
)
async def add_version(
    request: Request,
    response: Response,
    material_id: UUID,
    file: UploadFile = File(),
    idempotencyKey: UUID = Form(),
    expectedRevision: int = Form(ge=1),
) -> Material:
    principal = await actor(request, response)
    await strict_form(request, {"file", "idempotencyKey", "expectedRevision"})
    try:
        command = AddVersion(
            idempotency_key=idempotencyKey,
            expected_revision=expectedRevision,
            filename=file.filename or "",
            media_type=(file.content_type or "application/octet-stream")
            .split(";", 1)[0]
            .strip()
            .lower(),
        )
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error
    return await service(request).add_version(
        principal, material_id, command, await content(file)
    )


@router.get("", operation_id="listMaterials", response_model=Materials)
async def list_materials(
    request: Request,
    response: Response,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
    action_id: UUID | None = Query(default=None, alias="actionId"),
) -> Materials:
    return await service(request).list_materials(
        await actor(request, response),
        MaterialQuery(search=search, offset=offset, limit=limit, action_id=action_id),
    )


@router.get("/{material_id}", operation_id="getMaterial", response_model=Material)
async def get_material(
    request: Request, response: Response, material_id: UUID
) -> Material:
    return await service(request).get_material(
        await actor(request, response), material_id
    )


@router.get(
    "/{material_id}/versions/{version}",
    operation_id="getMaterialVersion",
    response_model=MaterialVersion,
)
async def get_version(
    request: Request, response: Response, material_id: UUID, version: int
) -> MaterialVersion:
    if version < 1:
        raise RequestValidationError(
            [
                {
                    "loc": ("path", "version"),
                    "type": "value_error",
                    "msg": "Positive Version erforderlich.",
                }
            ]
        )
    return await service(request).get_version(
        await actor(request, response), material_id, version
    )


@router.get(
    "/{material_id}/versions/{version}/download",
    operation_id="downloadMaterialVersion",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        }
    },
)
async def download(
    request: Request, response: Response, material_id: UUID, version: int
) -> Response:
    if version < 1:
        raise RequestValidationError(
            [
                {
                    "loc": ("path", "version"),
                    "type": "value_error",
                    "msg": "Positive Version erforderlich.",
                }
            ]
        )
    artifact = await service(request).download(
        await actor(request, response), material_id, version
    )
    return Response(
        content=artifact.content,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"attachment; filename=\"download\"; filename*=UTF-8''{quote(artifact.version.filename, safe='')}",
        },
    )


@router.put(
    "/{material_id}/members",
    operation_id="setMaterialMember",
    response_model=MaterialAccess,
)
async def set_material_member(
    request: Request, response: Response, material_id: UUID, body: SetMaterialMember
) -> MaterialAccess:
    return await service(request).set_material_member(
        await actor(request, response), material_id, body
    )


@router.put(
    "/{material_id}/members/by-email",
    operation_id="setMaterialMemberByEmail",
    response_model=MaterialAccess,
)
async def set_material_member_by_email(
    request: Request,
    response: Response,
    material_id: UUID,
    body: SetMaterialMemberByEmail,
) -> MaterialAccess:
    return await service(request).set_material_member_by_email(
        await actor(request, response), material_id, body
    )


@router.get(
    "/{material_id}/members",
    operation_id="listMaterialMembers",
    response_model=MaterialMembers,
)
async def list_members(
    request: Request,
    response: Response,
    material_id: UUID,
    search: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
) -> MaterialMembers:
    return await service(request).list_members(
        await actor(request, response),
        material_id,
        MemberQuery(search=search, offset=offset, limit=limit),
    )


@router.get(
    "/{material_id}/permissions",
    operation_id="getMaterialPermissions",
    response_model=MaterialPermissions,
)
async def get_permissions(
    request: Request, response: Response, material_id: UUID
) -> MaterialPermissions:
    return await service(request).get_permissions(
        await actor(request, response), material_id
    )
