"""Exercise registration against real FastAPI routers, without running services."""

import pytest
from fastapi import APIRouter, FastAPI

from leonaid.bootstrap.registry import (
    ModuleRegistration,
    collect_background_tasks,
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


@pytest.mark.parametrize("consumer", ["inbox", "knowledge"])
@pytest.mark.parametrize("dependency", ["tasks", "materials"])
def test_composed_api_modules_require_their_dependencies(
    consumer: str, dependency: str
) -> None:
    from leonaid.bootstrap.api import MODULES

    modules = tuple(
        module for module in MODULES if module.id in {consumer, "tasks", "materials"}
    )
    validate_modules(modules)
    app = FastAPI()
    before = list(app.routes)
    with pytest.raises(ValueError, match=f"Missing module dependency: {dependency}"):
        register_routes(app, tuple(m for m in modules if m.id != dependency))
    assert app.routes == before


def test_background_tasks_reject_duplicate_or_empty_names() -> None:
    from leonaid.modules.surveys.jobs import survey_timeout_loop

    for name in ("surveys.deadlines", " "):
        with pytest.raises(ValueError, match="Empty or duplicate background task"):
            collect_background_tasks(
                (
                    ModuleRegistration(
                        "surveys", background_tasks={name: survey_timeout_loop}
                    ),
                    ModuleRegistration(
                        "other", background_tasks={name: survey_timeout_loop}
                    ),
                )
            )


def test_worker_registers_existing_survey_sweep_once() -> None:
    from leonaid.bootstrap.worker import background_tasks
    from leonaid.modules.surveys.jobs import survey_timeout_loop

    assert background_tasks() == {"surveys.deadlines": survey_timeout_loop}
