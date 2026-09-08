"""Confirm committed erasure intents independently before acknowledgement or cleanup."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import asyncpg

from leonaid.adapters.postgres.survey_recovery import export_checkpoint_in_transaction
from leonaid.adapters.storage.survey_checkpoint_archive import FileCheckpointArchive
from leonaid.application.errors import DependencyUnavailable


class AsyncpgErasureCheckpointPublisher:
    def __init__(
        self, pool: asyncpg.Pool[Any], directory: Path | None, secret: str
    ) -> None:
        self.pool = pool
        self.directory = directory
        self.secret = secret

    async def publish(self) -> None:
        try:
            if self.directory is None or not self.directory.is_absolute():
                raise ValueError("Archive is not configured")
            # Serialize DB snapshot + archive publication, not just DB reads. This
            # prevents an older concurrent snapshot from publishing after a newer one.
            async with self.pool.acquire() as conn, conn.transaction():
                checkpoint = await export_checkpoint_in_transaction(conn)
                await asyncio.to_thread(
                    FileCheckpointArchive(self.directory).publish,
                    checkpoint,
                    self.secret,
                    only_if_changed=True,
                )
        except Exception:
            # Preserve the already-committed DB intent for an exact request retry.
            # Never expose mount paths, checkpoint contents or secret/provider errors.
            raise DependencyUnavailable(
                "survey_erasure_archive_unavailable",
                "Der Löschauftrag konnte noch nicht unabhängig gesichert werden. Bitte erneut versuchen.",
            ) from None


def configured_publisher(pool: asyncpg.Pool[Any]) -> AsyncpgErasureCheckpointPublisher:
    directory = os.environ.get("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR")
    return AsyncpgErasureCheckpointPublisher(
        pool,
        Path(directory) if directory else None,
        os.environ.get("LEONAID_SESSION_ENCRYPTION_KEY", ""),
    )
