"""Survey job contributions and the existing bounded deadline/retention sweep."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import asyncpg

from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.modules.surveys.adapters.mail.survey_smtp import (
    SurveyInvitationSmtpHandler,
)
from leonaid.adapters.mail.transport import SmtpTransport
from leonaid.adapters.postgres.pool import create_pool
from leonaid.modules.surveys.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.modules.surveys.adapters.postgres.survey_retention import sweep_retention
from leonaid.modules.surveys.adapters.postgres.survey_checkpoint_publisher import (
    configured_publisher,
)
from leonaid.modules.surveys.adapters.postgres.survey_deletion import (
    AsyncpgSurveyDeletion,
)
from leonaid.modules.surveys.adapters.postgres.survey_exports import (
    AsyncpgSurveyExports,
)
from leonaid.application.outbox import OutboxEventHandler
from leonaid.application.object_storage import ObjectStorage


def handlers(
    pool: asyncpg.Pool[Any],
    storage: ObjectStorage,
    transport: SmtpTransport,
    mail_secret: str,
) -> dict[str, OutboxEventHandler]:
    return {
        "survey.delete.v1": AsyncpgSurveyDeletion(
            pool, storage, configured_publisher(pool)
        ),
        "survey.export.render.v1": AsyncpgSurveyExports(pool, storage),
        "survey.invitation.send.v1": SurveyInvitationSmtpHandler(
            pool,
            transport=transport,
            secure_payload=SecureMailPayload(mail_secret),
        ),
    }


async def survey_timeout_loop() -> None:
    """Independent five-second sweep; catch up in bounded batches after outages."""
    while True:
        pool = None
        try:
            pool = await create_pool(os.environ["CORE_DATABASE_URL"], maximum_size=2)
            repository = AsyncpgSurveyRepository(pool)
            publisher = configured_publisher(pool)
            while True:
                closed = await repository.close_due_surveys()
                count = await repository.classify_overdue()
                retained = await sweep_retention(pool, checkpoint_publisher=publisher)
                await asyncio.sleep(
                    0.25 if count == 1000 or closed == 100 or retained == 100 else 5
                )
        except Exception:
            # Migration/startup/database outages are retried without logging private rows.
            await asyncio.sleep(2)
        finally:
            if pool is not None:
                await pool.close()
