"""API composition: installed modules, their routes, navigation and services."""

from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import APIRouter, FastAPI

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.postgres.survey_checkpoint_publisher import (
    AsyncpgErasureCheckpointPublisher,
)
from leonaid.adapters.postgres.survey_exports import AsyncpgSurveyExports
from leonaid.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.application.object_storage import ObjectStorage
from leonaid.application.surveys import SurveyService
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    NavigationContribution,
    collect_navigation,
    register_routes,
)
from leonaid.configuration import Settings
from leonaid.modules.surveys.navigation import navigation as survey_navigation
from leonaid.modules.surveys.routes import router as surveys_router

API_MODULES: tuple[ModuleRegistration, ...] = (
    ModuleRegistration("surveys", router=surveys_router, navigation=survey_navigation),
)


def register_api_modules(app: FastAPI, *, core: tuple[APIRouter, ...]) -> None:
    """Include the core router and every module router, checked together."""
    register_routes(app, API_MODULES, core=core)


def module_navigation() -> NavigationContribution:
    return collect_navigation(API_MODULES)


def build_survey_services(
    pool: asyncpg.Pool[Any], settings: Settings, storage: ObjectStorage
) -> tuple[SurveyService, AsyncpgSurveyExports, AsyncpgErasureCheckpointPublisher]:
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
    return surveys, AsyncpgSurveyExports(pool, storage), publisher
