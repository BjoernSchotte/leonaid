"""ASGI configuration contract against PostgreSQL; synthetic identity fixture."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from leonaid.application.delivery import DeliveryService
from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    PermissionDenied,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.entrypoints.fastapi.routes import router


class FixtureIdentity:
    def __init__(self, actor: IdentityPrincipal) -> None:
        self.current: IdentityPrincipal | None = actor

    async def authenticate(self, token: str | None) -> IdentityPrincipal:
        if self.current is None:
            raise AuthenticationRequired("login_required", "Bitte anmelden.")
        return self.current


def http_app(actor: IdentityPrincipal) -> tuple[FastAPI, FixtureIdentity]:
    app = FastAPI()
    identity = FixtureIdentity(actor)
    app.state.identity_service = identity
    app.include_router(router)

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_id = "delivery-http-proof"
        return await call_next(request)

    @app.exception_handler(ApplicationError)
    async def application_error(
        request: Request, error: ApplicationError
    ) -> JSONResponse:
        status = (
            401
            if isinstance(error, AuthenticationRequired)
            else 403
            if isinstance(error, PermissionDenied)
            else 409
            if isinstance(error, Conflict)
            else 404
        )
        return JSONResponse({"code": error.code}, status_code=status)

    @app.exception_handler(DomainInvariantError)
    async def domain_error(
        request: Request, error: DomainInvariantError
    ) -> JSONResponse:
        return JSONResponse({"code": error.code}, status_code=422)

    return app, identity


async def prove_http_configuration(
    service: DeliveryService, action_id: UUID, user_id: UUID
) -> None:
    now = datetime.now(timezone.utc)
    user = UserAccount(user_id, "admin@example.invalid", "Test", AccountStatus.ACTIVE)
    actor = IdentityPrincipal(
        user,
        frozenset(),
        (
            ActionMembership(
                uuid4(), action_id, "Test", user.id, ActionRole.CHARITY_ADMIN, now
            ),
        ),
    )
    app, identity = http_app(actor)
    app.state.delivery_service = service

    path = f"/api/v1/actions/{action_id}/delivery-configuration"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)
        assert (
            response.status_code == 200
            and response.headers["cache-control"] == "private, no-store"
        )
        current = response.json()
        body = {
            "expectedRevision": current["revision"],
            "enabled": True,
            "timezone": "Europe/Berlin",
            "windows": [
                {"deliveryOn": "2037-12-06", "startsAt": "08:00", "endsAt": "10:00"}
            ],
        }
        response = await client.put(path, json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert UUID(saved["windows"][0]["id"])
        assert saved["revision"] == current["revision"] + 1
        assert (await client.put(path, json=body)).status_code == 409
        foreign = {
            **body,
            "expectedRevision": saved["revision"],
            "windows": [{**body["windows"][0], "id": str(uuid4())}],
        }
        assert (await client.put(path, json=foreign)).status_code == 422
        assert (
            await client.put(path, json={**body, "arbitrary": True})
        ).status_code == 422
        identity.current = IdentityPrincipal(
            user,
            frozenset(),
            (
                ActionMembership(
                    uuid4(), action_id, "Test", user.id, ActionRole.ACQUIRER, now
                ),
            ),
        )
        assert (await client.get(path)).status_code == 403
        assert (await client.put(path, json=body)).status_code == 403
        identity.current = None
        assert (await client.get(path)).status_code == 401
        assert (await client.put(path, json=body)).status_code == 401
    print(
        "KLF-020 ASGI PASS: real configuration repository, camelCase JSON, server IDs, no-store, revision/foreign-ID errors, authenticated role boundaries (synthetic identity)"
    )
