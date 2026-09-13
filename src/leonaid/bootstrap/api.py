"""Explicit API module composition."""

from __future__ import annotations

from typing import Any
import asyncpg
from fastapi import FastAPI
from leonaid.configuration import Settings
from leonaid.application.object_storage import ObjectStorage
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.modules.surveys.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.modules.surveys.adapters.postgres.survey_exports import (
    AsyncpgSurveyExports,
)
from leonaid.modules.surveys.adapters.postgres.survey_checkpoint_publisher import (
    AsyncpgErasureCheckpointPublisher,
)
from leonaid.modules.surveys.api import SurveyService, SurveyExportService

from leonaid.bootstrap.registry import ModuleRegistration, register_routes
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.surveys.api import navigation as survey_navigation
from leonaid.modules.surveys.routes import router as surveys_router
from leonaid.platform.navigation import NavigationItem

from leonaid.modules.tasks.api import TaskService, navigation as task_navigation
from leonaid.modules.tasks.repository import AsyncpgTaskRepository
from leonaid.modules.tasks.routes import router as tasks_router

MODULES = (
    ModuleRegistration("tasks", router=tasks_router, navigation=task_navigation),
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


def build_survey_services(
    pool: asyncpg.Pool[Any], settings: Settings, storage: ObjectStorage
) -> tuple[SurveyService, SurveyExportService, AsyncpgErasureCheckpointPublisher]:
    publisher = AsyncpgErasureCheckpointPublisher(
        pool,
        settings.survey_erasure_archive_dir,
        settings.mail_payload_secret.get_secret_value(),
    )
    surveys = SurveyService(
        AsyncpgSurveyRepository(
            pool,
            invitation_mail=SecureMailPayload(
                settings.mail_payload_secret.get_secret_value()
            ),
            public_base_url=str(settings.public_base_url),
            checkpoint_publisher=publisher,
        )
    )
    exports = SurveyExportService(AsyncpgSurveyExports(pool, storage))
    return surveys, exports, publisher


def build_task_service(pool: asyncpg.Pool[Any]) -> TaskService:
    return TaskService(AsyncpgTaskRepository(pool))
