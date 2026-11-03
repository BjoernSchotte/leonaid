"""Worker contributions of the surveys module: outbox handlers and the sweep."""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.modules.surveys.adapters.mail.survey_smtp import (
    SurveyInvitationSmtpHandler,
)
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.adapters.postgres.pool import create_pool
from leonaid.modules.surveys.adapters.postgres.survey_checkpoint_publisher import (
    configured_publisher,
)
from leonaid.modules.surveys.adapters.postgres.survey_deletion import (
    AsyncpgSurveyDeletion,
)
from leonaid.modules.surveys.adapters.postgres.survey_exports import (
    AsyncpgSurveyExports,
)
from leonaid.modules.surveys.adapters.postgres.survey_retention import sweep_retention
from leonaid.modules.surveys.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.application.object_storage import ObjectStorage
from leonaid.application.outbox import OutboxEventHandler
from leonaid.platform.background import BackgroundLoop, LoopReporter

SURVEY_SWEEP_LOOP = "survey_sweep"
# Event types the survey handlers own; known without building any handler.
SURVEY_EVENT_TYPES = frozenset(
    {"survey.delete.v1", "survey.export.render.v1", "survey.invitation.send.v1"}
)
# Rendering is repeatable. In #7's benchmark the slowest export of 5,000
# synthetic responses took about 12 s; 240 s stays below the default lease.
SURVEY_HANDLER_TIMEOUTS = {"survey.export.render.v1": 240.0}


def survey_handlers(
    pool: asyncpg.Pool[Any],
    storage: ObjectStorage,
    mail_transport: SmtpTransport,
    mail_payload_secret: str,
) -> dict[str, OutboxEventHandler]:
    return {
        "survey.delete.v1": AsyncpgSurveyDeletion(
            pool, storage, configured_publisher(pool)
        ),
        "survey.export.render.v1": AsyncpgSurveyExports(pool, storage),
        "survey.invitation.send.v1": SurveyInvitationSmtpHandler(
            pool,
            transport=mail_transport,
            secure_payload=SecureMailPayload(mail_payload_secret),
        ),
    }


def survey_sweep(database_url: str) -> BackgroundLoop:
    """Independent five-second sweep; catch up in bounded batches after outages."""

    async def run(report: LoopReporter) -> None:
        while True:
            pool = None
            try:
                pool = await create_pool(database_url, maximum_size=2)
                repository = AsyncpgSurveyRepository(pool)
                publisher = configured_publisher(pool)
                while True:
                    closed = await repository.close_due_surveys()
                    count = await repository.classify_overdue()
                    retained = await sweep_retention(
                        pool, checkpoint_publisher=publisher
                    )
                    report.succeeded()
                    await asyncio.sleep(
                        0.25 if count == 1000 or closed == 100 or retained == 100 else 5
                    )
            except Exception as error:
                # Logged by type and location only, never with private row data.
                await asyncio.sleep(report.failed(error))
            finally:
                if pool is not None:
                    await pool.close()

    return BackgroundLoop(SURVEY_SWEEP_LOOP, stall_after_seconds=60, run=run)
