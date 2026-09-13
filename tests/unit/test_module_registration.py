"""Exercise registration against real FastAPI routers, without running services."""

import pytest
from fastapi import APIRouter, FastAPI

from leonaid.bootstrap.registry import (
    ModuleRegistration,
    collect_handlers,
    register_routes,
    validate_modules,
)
from leonaid.entrypoints.fastapi.platform import create_app


@pytest.mark.parametrize(
    "modules",
    [
        (ModuleRegistration("tasks"), ModuleRegistration("tasks")),
        (ModuleRegistration("tasks", requires=("missing",)),),
        (
            ModuleRegistration("tasks", requires=("knowledge",)),
            ModuleRegistration("knowledge", requires=("tasks",)),
        ),
        (ModuleRegistration(""),),
    ],
)
def test_invalid_module_graph_fails(modules: tuple[ModuleRegistration, ...]) -> None:
    with pytest.raises(ValueError):
        validate_modules(modules)


async def endpoint() -> dict[str, str]:
    return {"status": "ok"}


def test_colliding_routes_rejected_before_mutating_app() -> None:
    app = FastAPI()
    app.get("/items/{id}")(endpoint)
    contribution = APIRouter()
    contribution.get("/items/{item_id}")(endpoint)
    before = list(app.routes)
    with pytest.raises(ValueError, match="Duplicate module route"):
        register_routes(app, (ModuleRegistration("tasks", router=contribution),))
    assert app.routes == before


def test_same_path_with_different_method_is_valid() -> None:
    app = FastAPI()
    app.get("/items")(endpoint)
    contribution = APIRouter()
    contribution.post("/items")(endpoint)
    register_routes(app, (ModuleRegistration("tasks", router=contribution),))
    assert set(app.openapi()["paths"]["/items"]) == {"get", "post"}


@pytest.mark.asyncio
async def test_duplicate_handler_rejected() -> None:
    import asyncpg
    from leonaid.adapters.postgres.activity_projection import (
        ActionProgressActivityHandler,
    )

    # A real lazy pool: registration neither acquires a connection nor runs a job.
    pool = asyncpg.create_pool(min_size=0, max_size=1)
    handler = ActionProgressActivityHandler(pool)
    with pytest.raises(ValueError, match="Duplicate module handler"):
        collect_handlers(
            (
                ModuleRegistration("mail", handlers={"mail.send.v1": handler}),
                ModuleRegistration("other", handlers={"mail.send.v1": handler}),
            )
        )
    assert collect_handlers(
        (ModuleRegistration("mail", handlers={"mail.send.v1": handler}),)
    ) == {"mail.send.v1": handler}


def test_application_has_registered_survey_routes_once() -> None:
    app = create_app()
    schema = app.openapi()
    assert "get" in schema["paths"]["/api/v1/surveys"]
    paths = [getattr(route, "path", None) for route in app.routes]
    assert paths.count("/api/v1/surveys") == 1
