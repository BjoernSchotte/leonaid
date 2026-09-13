"""Explicit API module composition."""

from fastapi import FastAPI

from leonaid.bootstrap.registry import ModuleRegistration, register_routes
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.surveys.api import navigation as survey_navigation
from leonaid.modules.surveys.routes import router as surveys_router
from leonaid.platform.navigation import NavigationItem

MODULES = (
    ModuleRegistration("surveys", router=surveys_router, navigation=survey_navigation),
)


def register_api_modules(app: FastAPI) -> None:
    register_routes(app, MODULES)


def module_navigation(actor: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    return tuple(
        item
        for module in MODULES
        if module.navigation is not None
        for item in module.navigation(actor)
    )
