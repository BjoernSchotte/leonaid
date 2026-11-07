"""System-admin HTTP adapter for campaign hosts (specs/multi-domain §7.1).

Reads need a session of a system admin; every change additionally needs
the fresh sign-in step-up, like the other installation-wide settings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, cast
from uuid import UUID

import time
from datetime import timezone

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import Field

from leonaid.application.identity import IdentityQueryService
from leonaid.application.policies import require_action_manager
from leonaid.application.site_hosts import (
    AddSiteHost,
    BindEdition,
    ChangeEditionSegment,
    MoveRootToEdition,
    RemovalPreview,
    RemoveSiteHost,
    SetPrimaryEdition,
    SetRedirectHost,
    SiteBindingView,
    SiteHostCommand,
    SiteHostOverview,
    SiteHostService,
    SiteHostView,
    UnbindEdition,
)
from leonaid.adapters.postgres.site_directory import AsyncpgSiteDirectory
from leonaid.adapters.site_host_checks import public_resolvers_reachable
from leonaid.adapters.postgres.site_host_verification import (
    AsyncpgSiteHostVerification,
)
from leonaid.application.errors import PermissionDenied, ResourceNotFound
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.site_hosts import check_answer, normalize_hostname
from leonaid.domain.sessions import SESSION_COOKIE_NAME
from leonaid.entrypoints.fastapi.schemas import (
    AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
    ERROR_RESPONSES,
)
from leonaid.platform.http import TransportModel

HOST_CHECK_PREFIX = "/.well-known/leonaid-host-check/"

router = APIRouter(
    prefix="/api/v1/admin/site-hosts",
    tags=["site-hosts"],
    responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES,
)

EditionAvailabilityValue = Literal["published", "archive", "inactive"]
SiteHostStatusValue = Literal["pending", "verified", "active", "disabled"]


class SiteBindingResponse(TransportModel):
    id: UUID
    action_id: UUID
    action_name: str
    archive_slug: str
    segment: str
    at_root: bool
    is_primary: bool
    availability: EditionAvailabilityValue
    edition_url: str
    campaign_page: bool
    valid_from: datetime
    valid_to: datetime | None
    ended_reason: Literal["segment_changed", "unbound", "host_removed"] | None
    revision: int
    target_url: str | None


class SiteHostResponse(TransportModel):
    id: UUID
    hostname: str
    display_hostname: str
    status: SiteHostStatusValue
    kind: Literal["campaign", "redirect"]
    redirect_to_host_id: UUID | None
    redirect_to_hostname: str | None
    # Served by Core on port 80 of the host itself (§7.4).
    verification_path: str
    verified_at: datetime | None
    last_checked_at: datetime | None
    last_check_result: str | None
    failed_checks: int
    revision: int
    created_at: datetime
    bindings: list[SiteBindingResponse]
    history: list[SiteBindingResponse]


class BindableActionResponse(TransportModel):
    id: UUID
    name: str
    archive_slug: str
    status: str
    availability: EditionAvailabilityValue
    campaign_page: bool


class SiteHostListResponse(TransportModel):
    admin_host: str
    public_host: str | None
    public_host_aliases: list[str]
    hosts: list[SiteHostResponse]
    actions: list[BindableActionResponse]


class SiteHostRemovalItemResponse(TransportModel):
    binding_id: UUID
    action_id: UUID
    action_name: str
    current_url: str
    new_url: str | None


class SiteHostRemovalPreviewResponse(TransportModel):
    host_id: UUID
    revision: int
    items: list[SiteHostRemovalItemResponse]
    redirect_hosts: list[str]


class AddSiteHostRequest(TransportModel):
    command_id: UUID
    hostname: str = Field(min_length=1, max_length=300)


class SiteHostRevisionRequest(TransportModel):
    command_id: UUID
    revision: int = Field(ge=1, strict=True)


class SetSiteHostRedirectRequest(SiteHostRevisionRequest):
    target_host_id: UUID | None


class BindSiteEditionRequest(SiteHostRevisionRequest):
    action_id: UUID
    segment: str | None = Field(default=None, min_length=1, max_length=63)
    at_root: bool = Field(default=False, strict=True)


class ChangeSiteEditionSegmentRequest(SiteHostRevisionRequest):
    segment: str = Field(min_length=1, max_length=63)


class MoveSiteRootRequest(SiteHostRevisionRequest):
    action_id: UUID
    segment: str | None = Field(default=None, min_length=1, max_length=63)


class UnbindSiteEditionRequest(SiteHostRevisionRequest):
    confirm_root_removal: bool = Field(default=False, strict=True)


def binding_response(view: SiteBindingView) -> SiteBindingResponse:
    return SiteBindingResponse(
        id=view.id,
        action_id=view.action_id,
        action_name=view.action_name,
        archive_slug=view.archive_slug,
        segment=view.segment,
        at_root=view.at_root,
        is_primary=view.is_primary,
        availability=view.availability.value,
        edition_url=view.edition_url,
        campaign_page=view.campaign_page,
        valid_from=view.valid_from,
        valid_to=view.valid_to,
        ended_reason=cast(
            Literal["segment_changed", "unbound", "host_removed"] | None,
            view.ended_reason,
        ),
        revision=view.revision,
        target_url=view.target_url,
    )


def host_response(view: SiteHostView) -> SiteHostResponse:
    return SiteHostResponse(
        id=view.id,
        hostname=view.hostname,
        display_hostname=view.display_hostname,
        status=view.status.value,
        kind=view.kind,
        redirect_to_host_id=view.redirect_to_host_id,
        redirect_to_hostname=view.redirect_to_hostname,
        verification_path=HOST_CHECK_PREFIX + view.verification_token,
        verified_at=view.verified_at,
        last_checked_at=view.last_checked_at,
        last_check_result=view.last_check_result,
        failed_checks=view.failed_checks,
        revision=view.revision,
        created_at=view.created_at,
        bindings=[binding_response(item) for item in view.bindings],
        history=[binding_response(item) for item in view.history],
    )


def overview_response(overview: SiteHostOverview) -> SiteHostListResponse:
    return SiteHostListResponse(
        admin_host=overview.configured.admin,
        public_host=overview.configured.public,
        public_host_aliases=list(overview.configured.aliases),
        hosts=[host_response(host) for host in overview.hosts],
        actions=[
            BindableActionResponse(
                id=action.id,
                name=action.name,
                archive_slug=action.archive_slug,
                status=action.status,
                availability=action.availability.value,
                campaign_page=action.campaign_page,
            )
            for action in overview.actions
        ],
    )


def preview_response(preview: RemovalPreview) -> SiteHostRemovalPreviewResponse:
    return SiteHostRemovalPreviewResponse(
        host_id=preview.host_id,
        revision=preview.revision,
        items=[
            SiteHostRemovalItemResponse(
                binding_id=item.binding_id,
                action_id=item.action_id,
                action_name=item.action_name,
                current_url=item.current_url,
                new_url=item.new_url,
            )
            for item in preview.items
        ],
        redirect_hosts=list(preview.redirect_hosts),
    )


def _service(request: Request) -> SiteHostService:
    return cast(SiteHostService, request.app.state.site_host_service)


def _identity(request: Request) -> IdentityQueryService:
    return cast(IdentityQueryService, request.app.state.identity_service)


async def _reader(request: Request, response: Response) -> IdentityPrincipal:
    response.headers["Cache-Control"] = "no-store"
    return await _identity(request).authenticate(
        request.cookies.get(SESSION_COOKIE_NAME)
    )


async def _execute(
    request: Request, response: Response, command: SiteHostCommand
) -> SiteHostResponse:
    response.headers["Cache-Control"] = "no-store"
    actor = await _identity(request).authenticate_fresh(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    view = await _service(request).execute(
        actor, command, request_id=cast(str, request.state.request_id)
    )
    return host_response(view)


@router.get("", operation_id="listSiteHosts", response_model=SiteHostListResponse)
async def list_site_hosts(request: Request, response: Response) -> SiteHostListResponse:
    actor = await _reader(request, response)
    return overview_response(await _service(request).overview(actor))


@router.post("", operation_id="addSiteHost", response_model=SiteHostResponse)
async def add_site_host(
    request: Request, response: Response, body: AddSiteHostRequest
) -> SiteHostResponse:
    return await _execute(
        request, response, AddSiteHost(body.command_id, body.hostname)
    )


@router.put(
    "/{host_id}/redirect",
    operation_id="setSiteHostRedirect",
    response_model=SiteHostResponse,
)
async def set_site_host_redirect(
    host_id: UUID,
    request: Request,
    response: Response,
    body: SetSiteHostRedirectRequest,
) -> SiteHostResponse:
    return await _execute(
        request,
        response,
        SetRedirectHost(body.command_id, host_id, body.revision, body.target_host_id),
    )


@router.post(
    "/{host_id}/bindings",
    operation_id="bindSiteEdition",
    response_model=SiteHostResponse,
)
async def bind_site_edition(
    host_id: UUID,
    request: Request,
    response: Response,
    body: BindSiteEditionRequest,
) -> SiteHostResponse:
    return await _execute(
        request,
        response,
        BindEdition(
            body.command_id,
            host_id,
            body.revision,
            body.action_id,
            body.segment,
            body.at_root,
        ),
    )


@router.put(
    "/{host_id}/bindings/{binding_id}/segment",
    operation_id="changeSiteEditionSegment",
    response_model=SiteHostResponse,
)
async def change_site_edition_segment(
    host_id: UUID,
    binding_id: UUID,
    request: Request,
    response: Response,
    body: ChangeSiteEditionSegmentRequest,
) -> SiteHostResponse:
    return await _execute(
        request,
        response,
        ChangeEditionSegment(
            body.command_id, host_id, body.revision, binding_id, body.segment
        ),
    )


@router.put(
    "/{host_id}/bindings/{binding_id}/primary",
    operation_id="setPrimarySiteEdition",
    response_model=SiteHostResponse,
)
async def set_primary_site_edition(
    host_id: UUID,
    binding_id: UUID,
    request: Request,
    response: Response,
    body: SiteHostRevisionRequest,
) -> SiteHostResponse:
    return await _execute(
        request,
        response,
        SetPrimaryEdition(body.command_id, host_id, body.revision, binding_id),
    )


@router.delete(
    "/{host_id}/bindings/{binding_id}",
    operation_id="unbindSiteEdition",
    response_model=SiteHostResponse,
)
async def unbind_site_edition(
    host_id: UUID,
    binding_id: UUID,
    request: Request,
    response: Response,
    body: UnbindSiteEditionRequest,
) -> SiteHostResponse:
    return await _execute(
        request,
        response,
        UnbindEdition(
            body.command_id,
            host_id,
            body.revision,
            binding_id,
            body.confirm_root_removal,
        ),
    )


@router.put(
    "/{host_id}/root", operation_id="moveSiteRoot", response_model=SiteHostResponse
)
async def move_site_root(
    host_id: UUID,
    request: Request,
    response: Response,
    body: MoveSiteRootRequest,
) -> SiteHostResponse:
    return await _execute(
        request,
        response,
        MoveRootToEdition(
            body.command_id, host_id, body.revision, body.action_id, body.segment
        ),
    )


@router.get(
    "/{host_id}/removal-preview",
    operation_id="previewSiteHostRemoval",
    response_model=SiteHostRemovalPreviewResponse,
)
async def preview_site_host_removal(
    host_id: UUID, request: Request, response: Response
) -> SiteHostRemovalPreviewResponse:
    actor = await _reader(request, response)
    return preview_response(await _service(request).removal_preview(actor, host_id))


@router.delete(
    "/{host_id}", operation_id="removeSiteHost", response_model=SiteHostResponse
)
async def remove_site_host(
    host_id: UUID,
    request: Request,
    response: Response,
    body: SiteHostRevisionRequest,
) -> SiteHostResponse:
    return await _execute(
        request,
        response,
        RemoveSiteHost(body.command_id, host_id, body.revision),
    )


@router.post(
    "/{host_id}/check", operation_id="checkSiteHost", response_model=SiteHostResponse
)
async def check_site_host(
    host_id: UUID, request: Request, response: Response
) -> SiteHostResponse:
    """Prüfen (§7.4): the host check runs now; the answer has its result."""
    response.headers["Cache-Control"] = "no-store"
    # It changes the host's status, like every other write on hosts.
    actor = await _identity(request).authenticate_fresh(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    view = await _service(request).check(
        actor, host_id, request_id=cast(str, request.state.request_id)
    )
    return host_response(view)


# Infrastructure endpoints, not part of the product API.
infrastructure_router = APIRouter(include_in_schema=False)


def _verification(request: Request) -> AsyncpgSiteHostVerification:
    return cast(AsyncpgSiteHostVerification, request.app.state.site_host_verification)


def _request_hostname(request: Request) -> str | None:
    host = request.headers.get("host", "").strip().lower()
    if host.startswith("["):
        return None
    host = host.rsplit(":", 1)[0] if ":" in host else host
    try:
        return normalize_hostname(host)
    except DomainInvariantError:
        return None


@infrastructure_router.get(HOST_CHECK_PREFIX + "{token}")
async def host_check_answer(
    token: str,
    request: Request,
    nonce: str = Query(default="", max_length=64),
) -> Response:
    """Answered on port 80 of every name; proves the name reaches us (§7.4).

    The answer is an HMAC over host, token and the checker's nonce, keyed
    with the installation secret. Lookups come from an in-process snapshot.
    """
    hostname = _request_hostname(request)
    if (
        hostname is None
        or not 32 <= len(token) <= 128
        or not 16 <= len(nonce) <= 64
        or not all(character in "0123456789abcdef" for character in nonce)
        or not await _verification(request).answers(hostname, token)
    ):
        raise ResourceNotFound("site_host_check_unknown", "Unbekannte Host-Prüfung.")
    return PlainTextResponse(
        check_answer(
            cast(str, request.app.state.site_host_check_secret),
            hostname,
            token,
            nonce,
        ),
        headers={"Cache-Control": "no-store"},
    )


@infrastructure_router.get("/health/site-host-dns")
async def site_host_dns(request: Request) -> Response:
    """Outbound DNS to the public resolvers of the host check (pilot doctor).

    Cached 60 s: the path is public (/api/health/*) and must not turn the
    API into a DNS amplifier.
    """
    now = time.monotonic()
    cached = getattr(request.app.state, "site_host_dns_cache", None)
    if cached is None or now - cached[0] > 60:
        settings = request.app.state.host_check_settings
        reachable = await public_resolvers_reachable(
            settings.public_resolvers, settings.edge_name or "example.org"
        )
        cached = (now, reachable)
        request.app.state.site_host_dns_cache = cached
    reachable = cached[1]
    status = (
        "off"
        if not reachable
        else "ready"
        if all(reachable.values())
        else "unavailable"
    )
    return JSONResponse(
        {
            "status": status,
            "resolvers": [
                {"address": address, "reachable": ok}
                for address, ok in reachable.items()
            ],
        },
        status_code=503 if status == "unavailable" else 200,
        headers={"Cache-Control": "no-store"},
    )


@infrastructure_router.get("/internal/tls/ask")
async def tls_ask(request: Request, domain: str = Query(max_length=300)) -> Response:
    """Caddy's on-demand TLS permission (§9.1); 2xx means: issue.

    Only Caddy's own ask request reaches this path: the edge answers 404 for
    /internal/* on every host, and a request the edge proxied carries
    forwarding headers, which are refused here as well.
    """
    if any(
        name in request.headers
        for name in ("x-forwarded-for", "x-forwarded-host", "forwarded")
    ):
        raise PermissionDenied("tls_ask_internal_only", "Nur intern.")
    try:
        hostname = normalize_hostname(domain)
    except DomainInvariantError:
        raise PermissionDenied("tls_ask_refused", "Kein Zertifikat.") from None
    # Configured hosts have their own site blocks; never on demand.
    if _service(request).configured.refusal(hostname) is not None:
        raise PermissionDenied("tls_ask_refused", "Kein Zertifikat.")
    if not await _verification(request).approve_tls(
        hostname, datetime.now(timezone.utc)
    ):
        raise PermissionDenied("tls_ask_refused", "Kein Zertifikat.")
    return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})


# ---------- an action's public addresses, for its managers (§7.1) ----------

action_router = APIRouter(
    tags=["actions"], responses=AUTHENTICATED_CONFLICT_ERROR_RESPONSES
)


class ActionEditionResponse(TransportModel):
    hostname: str
    host_status: SiteHostStatusValue
    segment: str
    at_root: bool
    is_primary: bool
    edition_url: str


class ActionPublicUrlsResponse(TransportModel):
    # None: the action is not publicly reachable (§6.6).
    canonical_url: str | None
    editions: list[ActionEditionResponse]


@action_router.get(
    "/api/v1/actions/{action_id}/public-urls",
    operation_id="getActionPublicUrls",
    response_model=ActionPublicUrlsResponse,
)
async def get_action_public_urls(
    action_id: UUID, request: Request, response: Response
) -> ActionPublicUrlsResponse:
    """Read only; domains are managed by the system admin (D5)."""
    actor = await _reader(request, response)
    require_action_manager(actor, action_id)
    urls = await cast(
        AsyncpgSiteDirectory, request.app.state.site_directory
    ).action_urls(action_id)
    return ActionPublicUrlsResponse(
        canonical_url=urls.canonical_url,
        editions=[
            ActionEditionResponse(
                hostname=item.hostname,
                host_status=cast(SiteHostStatusValue, item.host_status),
                segment=item.segment,
                at_root=item.at_root,
                is_primary=item.is_primary,
                edition_url=item.edition_url,
            )
            for item in urls.editions
        ],
    )


# ---------- public reads of campaign hosts (§7.3) ----------

public_router = APIRouter(tags=["public-sites"])


class PublicSiteEditionResponse(TransportModel):
    segment: str
    at_root: bool
    is_primary: bool
    archive_slug: str
    availability: Literal["published", "archive"]
    title: str
    starts_on: date
    ends_on: date
    # Permanent URL of the edition: https://<host>/<segment>/.
    edition_url: str
    # The action's canonical URL; may be on another host (a mirror).
    canonical_url: str | None


class PublicSiteHistoryResponse(TransportModel):
    segment: str
    archive_slug: str
    target_url: str
    status: Literal[302, 308]


class PublicSiteRootResponse(TransportModel):
    segment: str
    mode: Literal["serve", "redirect"]


class PublicSiteResponse(TransportModel):
    hostname: str
    kind: Literal["campaign", "redirect"]
    redirect_to: str | None
    root: PublicSiteRootResponse | None
    editions: list[PublicSiteEditionResponse]
    history: list[PublicSiteHistoryResponse]


def _directory(request: Request) -> AsyncpgSiteDirectory:
    return cast(AsyncpgSiteDirectory, request.app.state.site_directory)


@public_router.get(
    "/api/v1/public/sites/{hostname}",
    operation_id="getPublicSite",
    response_model=PublicSiteResponse,
    responses=ERROR_RESPONSES,
)
async def get_public_site(
    hostname: str, request: Request, response: Response
) -> PublicSiteResponse:
    """What an active campaign host serves (§7.2); 404 for every other name."""
    try:
        normalized = normalize_hostname(hostname)
    except DomainInvariantError:
        raise ResourceNotFound("site_host_not_found", "Host nicht gefunden.") from None
    site = await _directory(request).site(normalized)
    if site is None:
        raise ResourceNotFound("site_host_not_found", "Host nicht gefunden.")
    response.headers["Cache-Control"] = "public, max-age=30"
    return PublicSiteResponse(
        hostname=site.hostname,
        kind=cast(Literal["campaign", "redirect"], site.kind),
        redirect_to=site.redirect_to,
        root=(
            PublicSiteRootResponse(segment=site.root.segment, mode=site.root.mode)
            if site.root
            else None
        ),
        editions=[
            PublicSiteEditionResponse(
                segment=item.segment,
                at_root=item.at_root,
                is_primary=item.is_primary,
                archive_slug=item.archive_slug,
                availability=cast(
                    Literal["published", "archive"], item.availability.value
                ),
                title=item.title,
                starts_on=item.starts_on,
                ends_on=item.ends_on,
                edition_url=item.edition_url,
                canonical_url=item.canonical_url,
            )
            for item in site.editions
        ],
        history=[
            PublicSiteHistoryResponse(
                segment=item.segment,
                archive_slug=item.archive_slug,
                target_url=item.target_url,
                status=cast(Literal[302, 308], item.status),
            )
            for item in site.history
        ],
    )
