"""Validate explicit contributions before attaching them to a process."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI
from starlette.routing import Route

from leonaid.application.outbox import OutboxEventHandler
from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.navigation import NavigationItem


@dataclass(frozen=True)
class ModuleRegistration:
    id: str
    router: APIRouter | None = None
    handlers: Mapping[str, OutboxEventHandler] = field(default_factory=dict)
    requires: tuple[str, ...] = ()
    navigation: Callable[[IdentityPrincipal], tuple[NavigationItem, ...]] | None = None
    background_tasks: Mapping[str, Callable[[], Awaitable[None]]] = field(
        default_factory=dict
    )


def validate_modules(modules: Sequence[ModuleRegistration]) -> None:
    ids = [module.id for module in modules]
    if any(not re.fullmatch(r"[a-z][a-z0-9-]*", name) for name in ids):
        raise ValueError("Invalid module ID")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate module ID")
    dependencies = {module.id: module.requires for module in modules}
    visited: set[str] = set()

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name not in dependencies:
            raise ValueError(f"Missing module dependency: {name}")
        if name in stack:
            raise ValueError(f"Module dependency cycle: {' -> '.join((*stack, name))}")
        if name in visited:
            return
        for dependency in dependencies[name]:
            visit(dependency, (*stack, name))
        visited.add(name)

    for name in ids:
        visit(name, ())


def register_routes(app: FastAPI, modules: Sequence[ModuleRegistration]) -> None:
    validate_modules(modules)
    occupied: set[tuple[str, str]] = set()
    routes = list(app.routes)
    for module in modules:
        if module.router is not None:
            routes.extend(module.router.routes)
    # Check all contributions before mutating the application.
    for route in routes:
        if not isinstance(route, Route):
            continue
        # Parameter names do not distinguish routes with identical match shapes.
        shape = re.sub(r"\{[^}:]+", "{parameter", route.path)
        for method in route.methods or ():
            key = (method, shape)
            if key in occupied:
                raise ValueError(f"Duplicate module route: {method} {shape}")
            occupied.add(key)
    for module in modules:
        if module.router is not None:
            app.include_router(module.router)


def collect_handlers(
    modules: Sequence[ModuleRegistration],
) -> dict[str, OutboxEventHandler]:
    validate_modules(modules)
    handlers: dict[str, OutboxEventHandler] = {}
    for module in modules:
        for event_type, handler in module.handlers.items():
            if not event_type.strip():
                raise ValueError("Empty module handler type")
            if event_type in handlers:
                raise ValueError(f"Duplicate module handler: {event_type}")
            handlers[event_type] = handler
    return handlers


def collect_background_tasks(
    modules: Sequence[ModuleRegistration],
) -> dict[str, Callable[[], Awaitable[None]]]:
    validate_modules(modules)
    tasks: dict[str, Callable[[], Awaitable[None]]] = {}
    for module in modules:
        for name, task in module.background_tasks.items():
            if not name.strip() or name in tasks:
                raise ValueError(f"Empty or duplicate background task: {name}")
            tasks[name] = task
    return tasks
