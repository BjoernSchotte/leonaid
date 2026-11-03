"""API composition: installed modules, their routes, navigation and services."""

from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import APIRouter, FastAPI

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.modules.surveys.adapters.postgres.survey_checkpoint_publisher import (
    AsyncpgErasureCheckpointPublisher,
)
from leonaid.modules.surveys.adapters.postgres.survey_exports import (
    AsyncpgSurveyExports,
)
from leonaid.modules.surveys.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.application.object_storage import ObjectStorage
from leonaid.modules.surveys.api import SurveyExportService, SurveyService
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    NavigationContribution,
    collect_navigation,
    register_routes,
    split_enabled,
)
from leonaid.configuration import Settings
from leonaid.modules.surveys.navigation import navigation as survey_navigation
from leonaid.modules.surveys.routes import router as surveys_router

API_MODULES: tuple[ModuleRegistration, ...] = (
    ModuleRegistration(
        "surveys",
        router=surveys_router,
        navigation=survey_navigation,
        switchable=True,
    ),
)


def enabled_api_modules(disabled: frozenset[str]) -> tuple[ModuleRegistration, ...]:
    return split_enabled(API_MODULES, disabled)[0]


def register_api_modules(
    app: FastAPI, *, core: tuple[APIRouter, ...], disabled: frozenset[str]
) -> None:
    """Include the core router and every enabled module router, checked together.

    Routes of switched-off modules are not registered, so they answer 404.
    """
    register_routes(app, enabled_api_modules(disabled), core=core)


def module_navigation(disabled: frozenset[str]) -> NavigationContribution:
    return collect_navigation(enabled_api_modules(disabled))


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
    return surveys, SurveyExportService(AsyncpgSurveyExports(pool, storage)), publisher
