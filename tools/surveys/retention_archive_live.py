"""Crash a real retention publication after DB commit; recover without new candidates."""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import UUID

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.survey_checkpoint_publisher import configured_publisher
from leonaid.adapters.postgres.survey_recovery import RECORD_COLUMNS
from leonaid.adapters.postgres.survey_retention import sweep_retention
import leonaid.adapters.storage.survey_checkpoint_archive as archive
from leonaid.application.surveys.recovery import ErasureRecord, verify

PROOF = Path("/proof")


async def main():
    pool = await create_pool(os.environ["CORE_DATABASE_URL"])
    directory = Path(os.environ["LEONAID_SURVEY_ERASURE_ARCHIVE_DIR"])
    secret = os.environ["LEONAID_SESSION_ENCRYPTION_KEY"]
    state = json.loads((PROOF / "retention-state.json").read_text())
    ids = [UUID(state["ids"][name]) for name in ("archived", "trashed")]
    async with pool.acquire() as conn:
        identity = await conn.fetchval(
            "SELECT installation_id FROM survey_recovery_identity WHERE singleton"
        )
        if sys.argv[1] == "crash":
            assert await conn.fetchval("SELECT count(*) FROM survey_deletion") == 0
            # Wait for real configured eligibility, without backdating the policy
            # or changing lifecycle timestamps in this interruption probe.
            async with asyncio.timeout(10):
                while (
                    await conn.fetchval(
                        """SELECT count(*) FROM survey s,survey_settings p
                    WHERE p.singleton AND s.id=ANY($1::uuid[]) AND s.status='deleted'
                    AND s.deleted_at + make_interval(secs=>p.trash_retention_seconds)
                    <= clock_timestamp()""",
                        ids,
                    )
                    != 2
                ):
                    await asyncio.sleep(0.1)
            original = archive.atomic_write

            def terminate_after_durable_pending(path, document):
                original(path, document)
                if path.name == "pending.json":
                    os._exit(73)

            archive.atomic_write = terminate_after_durable_pending
            await sweep_retention(pool, checkpoint_publisher=configured_publisher(pool))
            raise AssertionError(
                "Retention did not reach its publication crash boundary"
            )

        assert sys.argv[1] == "recover"
        rows = await conn.fetch(
            f"SELECT {RECORD_COLUMNS} FROM survey_deletion ORDER BY survey_id"
        )
        records = tuple(ErasureRecord.model_validate(dict(row)) for row in rows)
        assert len(records) == 2 and {r.survey_id for r in records} == set(ids)
        original_events = {r.event_id for r in records}
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey WHERE id=ANY($1::uuid[])", ids
            )
            == 2
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_deletion WHERE completed_at IS NOT NULL"
            )
            == 0
        )
        current = verify(
            (directory / "current.json").read_bytes(),
            secret,
            installation_id=identity,
            required_through=datetime.min.replace(tzinfo=timezone.utc),
        )
        assert current.records == ()
        pending = verify(
            (directory / "pending.json").read_bytes(),
            secret,
            installation_id=identity,
            required_through=max(r.requested_at for r in records),
        )
        assert pending.records == records
        try:
            archive.FileCheckpointArchive(directory).fetch(
                secret, installation_id=identity, required_through=current.exported_at
            )
        except ValueError as error:
            assert str(error) == "Archive publication is incomplete"
        else:
            raise AssertionError("Incomplete retention archive allowed recovery")

        # The already committed intents are excluded from candidate selection.
        # A zero-change sweep must still finish their interrupted publication.
        assert (
            await sweep_retention(pool, checkpoint_publisher=configured_publisher(pool))
            == 0
        )
        recovered = archive.FileCheckpointArchive(directory).fetch(
            secret, installation_id=identity, required_through=pending.exported_at
        )
        assert (
            verify(
                recovered,
                secret,
                installation_id=identity,
                required_through=pending.exported_at,
            ).records
            == records
        )
        again = await conn.fetch(
            f"SELECT {RECORD_COLUMNS} FROM survey_deletion ORDER BY survey_id"
        )
        assert [dict(row) for row in again] == [dict(row) for row in rows]
        events = await conn.fetch(
            "SELECT id,status FROM outbox_event WHERE event_type='survey.delete.v1'"
        )
        assert len(events) == 2 and {r["id"] for r in events} == original_events
        assert all(r["status"] == "pending" for r in events)
        assert (
            await sweep_retention(pool, checkpoint_publisher=configured_publisher(pool))
            == 0
        )
        assert (directory / "current.json").read_bytes() == recovered
        (PROOF / "retention-archive-proof.json").write_text(
            json.dumps(
                {
                    "syntheticOnly": True,
                    "abruptExitAfterCommittedIntentAndDurablePending": True,
                    "committedRetentionIntents": 2,
                    "noPhysicalCleanupBeforeRecovery": True,
                    "oldCurrentCannotBypassPendingPublication": True,
                    "zeroCandidateSweepFinishesPublication": True,
                    "originalLedgerAndOutboxIdentitiesUnchanged": True,
                    "unchangedSweepDoesNotGrowArchive": True,
                },
                indent=2,
            )
            + "\n"
        )
        print(
            "PASS: interrupted retention archive recovered with zero new candidates and unchanged identities"
        )
    await pool.close()


asyncio.run(main())
