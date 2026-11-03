"""Static module registration, validated before it is attached to a process.

Registration is explicit: ``bootstrap.api`` and ``bootstrap.worker`` list the
installed modules. Nothing is discovered or loaded at runtime. Validation runs
at startup and rejects invalid or duplicate IDs, missing or cyclic module
dependencies, colliding routes, duplicate outbox handlers and duplicate
background loops, so a wiring mistake stops the process instead of silently
shadowing another contribution.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI
from starlette.routing import Route

from leonaid.application.outbox import OutboxEventHandler
from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.background import BackgroundLoop
from leonaid.platform.navigation import NavigationItem

MODULE_ID = re.compile(r"[a-z][a-z0-9-]*\Z")
PATH_PARAMETER = re.compile(r"\{[^}:]+")

NavigationContribution = Callable[[IdentityPrincipal], tuple[NavigationItem, ...]]


class RegistrationError(ValueError):
    """A module contribution conflicts with another one or is malformed."""


@dataclass(frozen=True)
class ModuleRegistration:
    id: str
    router: APIRouter | None = None
    navigation: NavigationContribution | None = None
    handlers: Mapping[str, OutboxEventHandler] = field(default_factory=dict)
    # Upper runtime bound in seconds for handlers that are safe to repeat.
    handler_timeouts: Mapping[str, float] = field(default_factory=dict)
    background_loops: Sequence[BackgroundLoop] = ()
    requires: tuple[str, ...] = ()
    # Business modules can be switched off per installation; core areas such
    # as mail or invoicing cannot.
    switchable: bool = False


def split_enabled(
    modules: Sequence[ModuleRegistration], disabled: frozenset[str]
) -> tuple[tuple[ModuleRegistration, ...], tuple[ModuleRegistration, ...]]:
    """Return (enabled, switched off) after checking the switch list.

    Unknown or non-switchable IDs fail, so a typo cannot silently leave a
    module on. An enabled module must not require a switched-off one.
    """
    validate_modules(modules)
    known = {module.id: module for module in modules}
    for name in sorted(disabled):
        if name not in known:
            raise RegistrationError(f"Unknown module in switch list: {name}")
        if not known[name].switchable:
            raise RegistrationError(f"Module cannot be switched off: {name}")
    enabled = tuple(module for module in modules if module.id not in disabled)
    for module in enabled:
        blocked = sorted(set(module.requires) & disabled)
        if blocked:
            raise RegistrationError(
                f"Module {module.id} requires switched-off module {blocked[0]}"
            )
    return enabled, tuple(module for module in modules if module.id in disabled)


def validate_modules(modules: Sequence[ModuleRegistration]) -> None:
    ids = [module.id for module in modules]
    invalid = [name for name in ids if not MODULE_ID.fullmatch(name)]
    if invalid:
        raise RegistrationError(f"Invalid module ID: {invalid[0]!r}")
    duplicates = sorted({name for name in ids if ids.count(name) > 1})
    if duplicates:
        raise RegistrationError(f"Duplicate module ID: {duplicates[0]}")
    dependencies = {module.id: module.requires for module in modules}
    finished: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in path:
            raise RegistrationError(
                f"Module dependency cycle: {' -> '.join((*path, name))}"
            )
        if name in finished:
            return
        for dependency in dependencies[name]:
            if dependency not in dependencies:
                raise RegistrationError(
                    f"Module {name} requires unregistered module {dependency}"
                )
            visit(dependency, (*path, name))
        finished.add(name)

    for name in ids:
        visit(name, ())


def route_shape(path: str) -> str:
    """Parameter names do not distinguish routes with the same match shape."""
    return PATH_PARAMETER.sub("{parameter", path)


def route_keys(router: APIRouter) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for route in router.routes:
        if not isinstance(route, Route):
            # Included sub-routers are not exposed through a public API.
            raise RegistrationError("Registered routers must not include routers")
        keys.extend(
            (method, route_shape(route.path)) for method in sorted(route.methods or ())
        )
    return keys


def register_routes(
    app: FastAPI,
    modules: Sequence[ModuleRegistration],
    *,
    core: Sequence[APIRouter] = (),
) -> None:
    """Include core and module routers after checking all of them for collisions."""
    validate_modules(modules)
    routers = [*core, *(m.router for m in modules if m.router is not None)]
    occupied: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, Route):
            occupied.update(
                (method, route_shape(route.path)) for method in route.methods or ()
            )
    # Check every contribution before the application is changed.
    for router in routers:
        for key in route_keys(router):
            if key in occupied:
                raise RegistrationError(f"Duplicate route: {key[0]} {key[1]}")
            occupied.add(key)
    for router in routers:
        app.include_router(router)


def collect_navigation(
    modules: Sequence[ModuleRegistration],
) -> NavigationContribution:
    validate_modules(modules)
    contributions = tuple(
        module.navigation for module in modules if module.navigation is not None
    )

    def navigation(principal: IdentityPrincipal) -> tuple[NavigationItem, ...]:
        return tuple(
            item for contribution in contributions for item in contribution(principal)
        )

    return navigation


def collect_handlers(
    modules: Sequence[ModuleRegistration],
) -> dict[str, OutboxEventHandler]:
    validate_modules(modules)
    handlers: dict[str, OutboxEventHandler] = {}
    owners: dict[str, str] = {}
    for module in modules:
        for event_type, handler in module.handlers.items():
            if not event_type.strip():
                raise RegistrationError(f"Empty handler type in module {module.id}")
            if event_type in handlers:
                raise RegistrationError(
                    f"Duplicate handler {event_type}: "
                    f"{owners[event_type]} and {module.id}"
                )
            handlers[event_type] = handler
            owners[event_type] = module.id
    return handlers


def collect_background_loops(
    modules: Sequence[ModuleRegistration],
) -> tuple[BackgroundLoop, ...]:
    validate_modules(modules)
    loops: list[BackgroundLoop] = []
    names: set[str] = set()
    for module in modules:
        for loop in module.background_loops:
            if loop.name in names:
                raise RegistrationError(f"Duplicate background loop: {loop.name}")
            names.add(loop.name)
            loops.append(loop)
    return tuple(loops)


def collect_handler_timeouts(
    modules: Sequence[ModuleRegistration],
) -> dict[str, float]:
    """Timeouts may only name handlers that the same module registers."""
    validate_modules(modules)
    timeouts: dict[str, float] = {}
    for module in modules:
        for event_type, seconds in module.handler_timeouts.items():
            if event_type not in module.handlers:
                raise RegistrationError(
                    f"Module {module.id} sets a timeout for foreign or unknown "
                    f"handler {event_type}"
                )
            if not seconds > 0:
                raise RegistrationError(
                    f"Handler timeout must be positive: {event_type}"
                )
            timeouts[event_type] = seconds
    return timeouts
