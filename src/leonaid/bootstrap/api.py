"""Explicit API module composition."""

from fastapi import FastAPI

from leonaid.bootstrap.registry import ModuleRegistration, register_routes
from leonaid.modules.surveys.routes import router as surveys_router


def register_api_modules(app: FastAPI) -> None:
    register_routes(app, (ModuleRegistration("surveys", router=surveys_router),))
