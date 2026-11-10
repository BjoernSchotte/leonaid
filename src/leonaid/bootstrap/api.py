"""API composition: installed modules, their routes, navigation and services."""

from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import APIRouter, FastAPI

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.application.order_mails import OrderMailLinkResolver
from leonaid.adapters.postgres.delivery_board import AsyncpgDeliveryBoardRepository
from leonaid.adapters.postgres.delivery_tours import AsyncpgDeliveryTourRepository
from leonaid.adapters.postgres.sponsor_search import SponsorSearchPrivacyContributor
from leonaid.adapters.postgres.order_cancellation import (
    AsyncpgOrderCancellationRepository,
)
from leonaid.application.delivery_board import DeliveryBoardService
from leonaid.application.delivery_tours import DeliveryTourService
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.application.order_cancellation import OrderCancellationService
from leonaid.application.push import PushService
from leonaid.adapters.postgres.push import (
    AsyncpgPushRateLimiter,
    AsyncpgPushRepository,
)
from leonaid.domain.push import PushEndpointPolicy
from leonaid.modules.surveys.adapters.postgres.survey_checkpoint_publisher import (
    AsyncpgErasureCheckpointPublisher,
)
from leonaid.modules.surveys.adapters.postgres.survey_exports import (
    AsyncpgSurveyExports,
)
from leonaid.modules.surveys.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.application.object_storage import ObjectStorage
from leonaid.application.privacy import PrivacySubjectContributor
from leonaid.modules.surveys.api import SurveyExportService, SurveyService
from leonaid.bootstrap.registry import (
    ModuleRegistration,
    NavigationContribution,
    collect_navigation,
    register_routes,
    split_enabled,
)
from leonaid.configuration import MapSettings, PushSettings, Settings
from leonaid.domain.delivery_tours import MapTiles
from leonaid.modules.surveys.jobs import SURVEY_EVENT_TYPES
from leonaid.modules.surveys.navigation import navigation as survey_navigation
from leonaid.adapters.postgres.outbox import complete_resolved_event
from leonaid.application.crm import CrmGateway
from leonaid.modules.inbox.api import InboxService
from leonaid.modules.inbox.api import navigation as inbox_navigation
from leonaid.modules.inbox.jobs import INBOX_EVENT_TYPES
from leonaid.modules.inbox.privacy import InboxPrivacyContributor
from leonaid.modules.inbox.repository import AsyncpgInboxRepository
from leonaid.modules.inbox.routes import router as inbox_router
from leonaid.modules.knowledge.api import KnowledgeService
from leonaid.modules.knowledge.api import navigation as knowledge_navigation
from leonaid.modules.knowledge.repository import AsyncpgKnowledgeRepository
from leonaid.modules.knowledge.routes import router as knowledge_router
from leonaid.modules.materials.api import MaterialService
from leonaid.modules.materials.api import navigation as material_navigation
from leonaid.modules.materials.repository import AsyncpgMaterialRepository
from leonaid.modules.materials.routes import router as materials_router
from leonaid.modules.surveys.routes import router as surveys_router
from leonaid.modules.tasks.api import TaskService
from leonaid.modules.tasks.delivery_follow_up import TaskDeliveryFollowUp
from leonaid.modules.tasks.api import navigation as task_navigation
from leonaid.modules.tasks.repository import AsyncpgTaskRepository
from leonaid.modules.tasks.routes import router as tasks_router

API_MODULES: tuple[ModuleRegistration, ...] = (
    ModuleRegistration(
        "surveys",
        router=surveys_router,
        navigation=survey_navigation,
        switchable=True,
    ),
    ModuleRegistration(
        "tasks",
        router=tasks_router,
        navigation=task_navigation,
        switchable=True,
    ),
    ModuleRegistration(
        "materials",
        router=materials_router,
        navigation=material_navigation,
        switchable=True,
    ),
    ModuleRegistration(
        "knowledge",
        router=knowledge_router,
        navigation=knowledge_navigation,
        switchable=True,
        requires=("tasks", "materials"),
    ),
    ModuleRegistration(
        "inbox",
        router=inbox_router,
        navigation=inbox_navigation,
        switchable=True,
        requires=("tasks", "materials"),
    ),
)


# Outbox event types per switchable module. Operations leave the jobs of
# switched-off modules out of queue timing, because they wait on purpose.
MODULE_EVENT_TYPES: dict[str, frozenset[str]] = {
    "surveys": SURVEY_EVENT_TYPES,
    "tasks": frozenset(),
    "materials": frozenset(),
    "knowledge": frozenset(),
    "inbox": INBOX_EVENT_TYPES,
}


def parked_event_types(disabled: frozenset[str]) -> frozenset[str]:
    _, off = split_enabled(API_MODULES, disabled)
    return frozenset(
        event_type for module in off for event_type in MODULE_EVENT_TYPES[module.id]
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
            links=settings.links,
            checkpoint_publisher=publisher,
        )
    )
    return surveys, SurveyExportService(AsyncpgSurveyExports(pool, storage)), publisher


def build_delivery_board_service(
    pool: asyncpg.Pool[Any], disabled: frozenset[str], flags: FeatureFlagService
) -> DeliveryBoardService:
    """Closing a window creates "Nachliefern" tasks only while tasks is on.

    A state command with ``missed`` answers 404 while ``delivery.tours`` is off.
    """
    tasks_enabled = any(
        module.id == "tasks" for module in enabled_api_modules(disabled)
    )
    follow_up = TaskDeliveryFollowUp() if tasks_enabled else None
    return DeliveryBoardService(
        AsyncpgDeliveryBoardRepository(
            pool,
            (lambda _connection: follow_up) if follow_up is not None else None,
        ),
        flags=flags,
        follow_up_tasks=tasks_enabled,
    )


def build_delivery_tour_service(
    pool: asyncpg.Pool[Any], flags: FeatureFlagService, maps: MapSettings
) -> DeliveryTourService:
    """Tours answer 404 while the flag ``delivery.tours`` is off."""
    return DeliveryTourService(
        AsyncpgDeliveryTourRepository(pool),
        flags,
        MapTiles(tile_url=maps.tile_url, attribution=maps.attribution),
    )


def build_push_service(
    pool: asyncpg.Pool[Any],
    flags: FeatureFlagService,
    disabled: frozenset[str],
    settings: PushSettings,
) -> PushService:
    """Push answers 404 while ``pwa.push`` is off; without a VAPID key it
    reports "not configured". Task pushes exist only while tasks is on."""
    signer = settings.signer()
    return PushService(
        AsyncpgPushRepository(pool),
        flags,
        public_key=signer.public_key if signer is not None else None,
        endpoints=PushEndpointPolicy(),
        limiter=AsyncpgPushRateLimiter(pool),
        tasks_enabled=any(
            module.id == "tasks" for module in enabled_api_modules(disabled)
        ),
    )


def build_order_cancellation_service(
    pool: asyncpg.Pool[Any],
    disabled: frozenset[str],
    *,
    mail_links: OrderMailLinkResolver | None = None,
) -> OrderCancellationService:
    """Cancelling closes the order's "Nachliefern" task while tasks is on."""
    tasks_enabled = any(
        module.id == "tasks" for module in enabled_api_modules(disabled)
    )
    follow_up = TaskDeliveryFollowUp() if tasks_enabled else None
    return OrderCancellationService(
        AsyncpgOrderCancellationRepository(
            pool,
            (lambda _connection: follow_up) if follow_up is not None else None,
        ),
        mail_links=mail_links,
    )


def build_task_service(pool: asyncpg.Pool[Any]) -> TaskService:
    return TaskService(AsyncpgTaskRepository(pool))


def build_material_service(
    pool: asyncpg.Pool[Any], storage: ObjectStorage
) -> MaterialService:
    return MaterialService(AsyncpgMaterialRepository(pool, storage))


def build_knowledge_service(
    pool: asyncpg.Pool[Any], storage: ObjectStorage
) -> KnowledgeService:
    """Task and material operations join the page transaction they run in."""
    return KnowledgeService(
        AsyncpgKnowledgeRepository(
            pool,
            lambda connection: TaskService(
                AsyncpgTaskRepository(pool, connection=connection)
            ),
            lambda connection: MaterialService(
                AsyncpgMaterialRepository(pool, storage, connection=connection)
            ),
        )
    )


def build_inbox_service(
    pool: asyncpg.Pool[Any], crm: CrmGateway | None = None
) -> InboxService:
    # Inbox only references material versions; it never reads object storage.
    return InboxService(
        AsyncpgInboxRepository(
            pool,
            lambda connection: TaskService(
                AsyncpgTaskRepository(pool, connection=connection)
            ),
            lambda connection: MaterialService(
                AsyncpgMaterialRepository(pool, connection=connection)
            ),
            complete_resolved_event,
        ),
        crm,
    )


def privacy_contributors() -> tuple[PrivacySubjectContributor, ...]:
    """Data outside the core erasure, also of switched-off modules."""
    return (InboxPrivacyContributor(), SponsorSearchPrivacyContributor())
