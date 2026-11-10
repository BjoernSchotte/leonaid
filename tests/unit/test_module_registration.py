from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from leonaid.application.identity import navigation_for
from leonaid.bootstrap.api import API_MODULES, module_navigation, parked_event_types
from leonaid.modules.surveys.jobs import SURVEY_EVENT_TYPES
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    RegistrationError,
    collect_background_loops,
    collect_handlers,
    collect_navigation,
    register_routes,
    split_enabled,
    validate_modules,
)
from leonaid.bootstrap.worker import (
    HandlerDependencies,
    background_loops,
    module_switch_problems,
    worker_modules,
)
from leonaid.configuration import (
    ConfigurationError,
    load_module_settings,
    parse_module_ids,
)
from leonaid.domain.identity import (
    AccountStatus,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.domain.outbox import ClaimedOutboxEvent
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.platform.background import BackgroundLoop, LoopReporter
from leonaid.platform.navigation import NavigationItem


class Handler:
    async def handle(self, event: ClaimedOutboxEvent) -> None:
        return None


async def idle(_report: LoopReporter) -> None:
    return None


def router(path: str, method: str = "GET") -> APIRouter:
    result = APIRouter()
    result.add_api_route(path, lambda: None, methods=[method])
    return result


def principal() -> IdentityPrincipal:
    return IdentityPrincipal(
        account=UserAccount(
            id=UUID("10000000-0000-4000-8000-000000000001"),
            email="klara@example.test",
            display_name="Klara",
            status=AccountStatus.ACTIVE,
        ),
        global_roles=frozenset(),
        action_memberships=(),
    )


@pytest.mark.parametrize("module_id", ["", "Tasks", "1tasks", "tasks_x", "tasks/"])
def test_invalid_module_ids_are_rejected(module_id: str) -> None:
    with pytest.raises(RegistrationError, match="Invalid module ID"):
        validate_modules((ModuleRegistration(module_id),))


def test_duplicate_module_ids_are_rejected() -> None:
    with pytest.raises(RegistrationError, match="Duplicate module ID: tasks"):
        validate_modules((ModuleRegistration("tasks"), ModuleRegistration("tasks")))


def test_missing_dependency_is_rejected() -> None:
    with pytest.raises(RegistrationError, match="requires unregistered module tasks"):
        validate_modules((ModuleRegistration("knowledge", requires=("tasks",)),))


def test_dependency_cycle_is_rejected() -> None:
    with pytest.raises(RegistrationError, match="cycle: a -> b -> a"):
        validate_modules(
            (
                ModuleRegistration("a", requires=("b",)),
                ModuleRegistration("b", requires=("a",)),
            )
        )


def test_self_dependency_is_rejected() -> None:
    with pytest.raises(RegistrationError, match="cycle: a -> a"):
        validate_modules((ModuleRegistration("a", requires=("a",)),))


def test_satisfied_dependencies_are_accepted_in_any_order() -> None:
    validate_modules(
        (
            ModuleRegistration("knowledge", requires=("tasks", "materials")),
            ModuleRegistration("materials"),
            ModuleRegistration("tasks"),
        )
    )


def test_routes_with_the_same_shape_collide_even_with_other_parameter_names() -> None:
    app = FastAPI()
    modules = (
        ModuleRegistration("a", router=router("/api/v1/items/{item_id}")),
        ModuleRegistration("b", router=router("/api/v1/items/{other}")),
    )

    with pytest.raises(RegistrationError, match="GET /api/v1/items/"):
        register_routes(app, modules)

    # Validation runs before the application is changed.
    assert "/api/v1/items/{item_id}" not in app.openapi()["paths"]


def test_module_route_colliding_with_core_route_is_rejected() -> None:
    with pytest.raises(RegistrationError, match="GET /api/v1/core"):
        register_routes(
            FastAPI(),
            (ModuleRegistration("a", router=router("/api/v1/core")),),
            core=(router("/api/v1/core"),),
        )


def test_module_route_colliding_with_application_route_is_rejected() -> None:
    app = FastAPI()
    with pytest.raises(RegistrationError, match="GET /openapi.json"):
        register_routes(app, (ModuleRegistration("a", router=router("/openapi.json")),))


def test_nested_routers_are_rejected() -> None:
    outer = APIRouter()
    outer.include_router(router("/api/v1/inner"))
    with pytest.raises(RegistrationError, match="must not include routers"):
        register_routes(FastAPI(), (ModuleRegistration("a", router=outer),))


def test_same_path_with_other_method_is_allowed() -> None:
    app = FastAPI()
    register_routes(
        app,
        (
            ModuleRegistration("a", router=router("/api/v1/items", "GET")),
            ModuleRegistration("b", router=router("/api/v1/items", "POST")),
        ),
    )

    assert set(app.openapi()["paths"]["/api/v1/items"]) == {"get", "post"}


def test_duplicate_handlers_name_both_owners() -> None:
    with pytest.raises(RegistrationError, match="mail.send.v1: a and b"):
        collect_handlers(
            (
                ModuleRegistration("a", handlers={"mail.send.v1": Handler()}),
                ModuleRegistration("b", handlers={"mail.send.v1": Handler()}),
            )
        )


def test_empty_handler_type_is_rejected() -> None:
    with pytest.raises(RegistrationError, match="Empty handler type"):
        collect_handlers((ModuleRegistration("a", handlers={" ": Handler()}),))


def test_duplicate_background_loops_are_rejected() -> None:
    loop = BackgroundLoop("sweep", stall_after_seconds=10, run=idle)
    with pytest.raises(RegistrationError, match="Duplicate background loop: sweep"):
        collect_background_loops(
            (
                ModuleRegistration("a", background_loops=(loop,)),
                ModuleRegistration("b", background_loops=(loop,)),
            )
        )


@pytest.mark.parametrize(("name", "stall"), [("", 10.0), ("sweep", 0.0)])
def test_invalid_background_loops_are_rejected(name: str, stall: float) -> None:
    with pytest.raises(ValueError):
        BackgroundLoop(name, stall_after_seconds=stall, run=idle)


def test_navigation_contributions_keep_module_order() -> None:
    def first(_principal: IdentityPrincipal) -> tuple[NavigationItem, ...]:
        return (NavigationItem("first", "Eins", "/admin/first", "web"),)

    def second(_principal: IdentityPrincipal) -> tuple[NavigationItem, ...]:
        return (NavigationItem("second", "Zwei", "/app/second", "pwa"),)

    navigation = collect_navigation(
        (
            ModuleRegistration("a", navigation=first),
            ModuleRegistration("b"),
            ModuleRegistration("c", navigation=second),
        )
    )

    assert [item.key for item in navigation(principal())] == ["first", "second"]


def test_modules_are_registered_with_routes_and_navigation() -> None:
    assert [module.id for module in API_MODULES] == [
        "surveys",
        "tasks",
        "materials",
        "knowledge",
        "inbox",
    ]
    items = navigation_for(principal(), module_navigation(frozenset())(principal()))

    assert [(item.key, item.href, item.surface) for item in items] == [
        ("overview-pwa", "/app/", "pwa"),
        ("surveys", "/admin/surveys", "web"),
        # The PWA links to the shared web survey editor.
        ("surveys", "/admin/surveys", "pwa"),
        ("tasks", "/admin/tasks", "web"),
        ("tasks", "/app/tasks", "pwa"),
        ("materials", "/admin/materials", "web"),
        ("materials", "/app/materials", "pwa"),
        ("knowledge", "/admin/knowledge", "web"),
        ("knowledge", "/app/knowledge", "pwa"),
        ("inbox", "/admin/inbox", "web"),
        ("inbox", "/app/inbox", "pwa"),
    ]


@pytest.mark.parametrize("status", [AccountStatus.SUSPENDED, AccountStatus.ARCHIVED])
def test_module_navigation_is_hidden_for_inactive_accounts(
    status: AccountStatus,
) -> None:
    inactive = IdentityPrincipal(
        account=UserAccount(
            id=UUID("10000000-0000-4000-8000-000000000009"),
            email="gesa@example.test",
            display_name="Gesa",
            status=status,
        ),
        global_roles=frozenset(),
        action_memberships=(),
    )
    assert module_navigation(frozenset())(inactive) == ()


def test_production_app_serves_the_survey_routes() -> None:
    survey_router = API_MODULES[0].router
    assert survey_router is not None
    paths = create_app().openapi()["paths"]

    for route in survey_router.routes:
        assert isinstance(route, APIRoute)
        if route.include_in_schema:
            assert route.path in paths


def test_worker_registers_every_existing_handler_once() -> None:
    modules = worker_modules("postgresql://unused", None)

    assert [module.id for module in modules] == [
        "surveys",
        "tasks",
        "materials",
        "knowledge",
        "inbox",
        "actions",
        "acquisition",
        "invoicing",
        "mail",
    ]
    assert collect_handlers(modules) == {}
    assert [
        loop.name for loop in background_loops("postgresql://unused", frozenset())
    ] == ["survey_sweep", "sponsor_search_sync"]


def test_worker_handler_set_is_unchanged() -> None:
    placeholder = cast(Any, object())
    handlers = collect_handlers(
        worker_modules(
            "postgresql://unused",
            HandlerDependencies(
                pool=placeholder,
                storage=placeholder,
                mail_transport=placeholder,
                payload_secret="0" * 64,
            ),
        )
    )

    assert sorted(handlers) == [
        "charity_action.progress.recorded.v1",
        "document.render.requested.v1",
        "inbox.contact_link.v1",
        "invoice.document.render.requested.v1",
        "invoice.mail.send.requested.v1",
        "mail.send.v1",
        "order.cancellation.mail.v1",
        "order.confirmation.mail.v1",
        "survey.delete.v1",
        "survey.export.render.v1",
        "survey.invitation.send.v1",
    ]


def test_switch_list_splits_enabled_and_switched_off_modules() -> None:
    modules = (
        ModuleRegistration("tasks", switchable=True),
        ModuleRegistration("knowledge", switchable=True, requires=("tasks",)),
        ModuleRegistration("mail"),
    )

    enabled, off = split_enabled(modules, frozenset({"knowledge"}))

    assert [module.id for module in enabled] == ["tasks", "mail"]
    assert [module.id for module in off] == ["knowledge"]


@pytest.mark.parametrize(
    ("disabled", "message"),
    [
        ({"taks"}, "Unknown module in switch list: taks"),
        ({"mail"}, "Module cannot be switched off: mail"),
        ({"tasks"}, "knowledge requires switched-off module tasks"),
    ],
)
def test_invalid_switch_lists_fail_loudly(disabled: set[str], message: str) -> None:
    modules = (
        ModuleRegistration("tasks", switchable=True),
        ModuleRegistration("knowledge", switchable=True, requires=("tasks",)),
        ModuleRegistration("mail"),
    )
    with pytest.raises(RegistrationError, match=message):
        split_enabled(modules, frozenset(disabled))


def test_api_and_worker_offer_the_same_switchable_modules() -> None:
    api = {module.id for module in API_MODULES if module.switchable}
    worker = {
        module.id
        for module in worker_modules("postgresql://unused", None)
        if module.switchable
    }
    assert api == worker == {"surveys", "tasks", "materials", "knowledge", "inbox"}


def test_switched_off_module_has_no_routes_navigation_or_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEONAID_DISABLED_MODULES", "surveys")
    off = frozenset({"surveys"})

    paths = create_app().openapi()["paths"]

    assert paths
    assert not any("/surveys" in path for path in paths)
    assert {item.key for item in module_navigation(off)(principal())} == {
        "tasks",
        "materials",
        "knowledge",
        "inbox",
    }
    assert any(path.startswith("/api/v1/task") for path in paths)
    # Core loops keep running; the module's own loop is gone.
    assert [loop.name for loop in background_loops("postgresql://unused", off)] == [
        "sponsor_search_sync"
    ]
    assert module_switch_problems(off) == []
    assert module_switch_problems(frozenset({"mail"})) == [
        "LEONAID_DISABLED_MODULES:Module cannot be switched off: mail"
    ]


def test_unknown_switch_stops_the_api_at_build_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEONAID_DISABLED_MODULES", "surveyz")
    with pytest.raises(RegistrationError, match="Unknown module"):
        create_app()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", frozenset()), (" surveys , ,tasks", frozenset({"surveys", "tasks"}))],
)
def test_module_switch_list_is_parsed(raw: str, expected: frozenset[str]) -> None:
    assert parse_module_ids(raw) == expected


def test_malformed_module_switch_list_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="invalid module ID"):
        parse_module_ids("Surveys")
    monkeypatch.setenv("LEONAID_DISABLED_MODULES", "Surveys")
    with pytest.raises(ConfigurationError, match="LEONAID_DISABLED_MODULES"):
        load_module_settings()


def test_parked_event_types_match_the_survey_handlers() -> None:
    placeholder = cast(Any, object())
    surveys = worker_modules(
        "postgresql://unused",
        HandlerDependencies(
            pool=placeholder,
            storage=placeholder,
            mail_transport=placeholder,
            payload_secret="0" * 64,
        ),
    )[0]

    assert set(surveys.handlers) == SURVEY_EVENT_TYPES
    assert parked_event_types(frozenset({"surveys"})) == SURVEY_EVENT_TYPES
    assert parked_event_types(frozenset()) == frozenset()
