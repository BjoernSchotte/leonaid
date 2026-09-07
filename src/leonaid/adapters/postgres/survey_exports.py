"""Durable survey export pipeline with current authorization and private objects."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.identity import account_from_record
from leonaid.adapters.postgres.survey_analysis import read_snapshot
from leonaid.adapters.survey_tabular_exports import render_tabular
from leonaid.adapters.typst.survey_renderer import TypstSurveyRenderer
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.object_storage import (
    ObjectLocation,
    ObjectStorage,
    ObjectWrite,
)
from leonaid.application.surveys.analysis_snapshot import AnalysisSnapshot
from leonaid.application.surveys.export_rendering import (
    SurveyExportArtifact,
    SurveyExportSource,
    export_filename,
)
from leonaid.application.surveys.exports import CreateSurveyExport, SurveyExportJob
from leonaid.application.surveys.response_selection import IndividualResponse
from leonaid.domain.identity import (
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
)
from leonaid.domain.outbox import ClaimedOutboxEvent
from leonaid.domain.surveys import Capability, may_access_survey


class SurveyExportJobError(RuntimeError):
    code = "survey_export_failed"

    def __init__(self) -> None:
        super().__init__("survey_export_failed")


def not_found() -> ResourceNotFound:
    return ResourceNotFound("not_found", "Export nicht gefunden.")


async def current_principal(conn: Any, user_id: UUID) -> IdentityPrincipal:
    account = await conn.fetchrow("SELECT * FROM user_account WHERE id=$1", user_id)
    if account is None:
        raise not_found()
    roles = await conn.fetch(
        "SELECT role FROM user_global_role WHERE user_id=$1", user_id
    )
    memberships = await conn.fetch(
        """SELECT m.*, a.name AS action_name FROM action_membership m
           JOIN charity_action a ON a.id=m.action_id
           WHERE m.user_id=$1 AND m.active_from <= clock_timestamp()
             AND (m.active_until IS NULL OR m.active_until > clock_timestamp())""",
        user_id,
    )
    return IdentityPrincipal(
        account=account_from_record(account),
        global_roles=frozenset(GlobalRole(r["role"]) for r in roles),
        action_memberships=tuple(
            ActionMembership(
                id=r["id"],
                action_id=r["action_id"],
                action_name=r["action_name"],
                user_id=user_id,
                role=ActionRole(r["role"]),
                active_from=r["active_from"],
                active_until=r["active_until"],
                delegate_user_id=r["delegate_user_id"],
            )
            for r in memberships
        ),
    )


async def authorize(conn: Any, user_id: UUID, survey: Any, product: str) -> bool:
    if survey is None or survey["status"] == "deleted":
        raise not_found()
    principal = await current_principal(conn, user_id)
    grants = frozenset(
        Capability(r["capability"])
        for r in await conn.fetch(
            "SELECT capability FROM survey_grant WHERE survey_id=$1 AND user_id=$2",
            survey["id"],
            user_id,
        )
    )

    def allowed(capability: Capability) -> bool:
        return may_access_survey(
            principal,
            owner_user_id=survey["owner_user_id"],
            action_id=survey["action_id"],
            capability=capability,
            grants=grants,
        )

    if not allowed(
        Capability.EXPORT_RAW
        if product.startswith("responses_")
        else Capability.EXPORT_REPORTS
    ):
        raise not_found()
    return allowed(Capability.DESIGN)


JOB_SELECT = """SELECT j.*, e.status AS event_status, e.attempts, e.last_error_code
    FROM survey_export_job j JOIN outbox_event e ON e.id=j.event_id"""


def job_payload(row: Any) -> SurveyExportJob:
    status = row["status"]
    if status == "queued":
        status = {"processing": "processing", "dead_letter": "failed"}.get(
            row["event_status"], "retrying" if row["attempts"] else "queued"
        )
    return SurveyExportJob.model_validate(
        {
            "id": str(row["id"]),
            "surveyId": str(row["survey_id"]),
            "snapshotId": str(row["snapshot_id"]),
            "product": row["product"],
            "status": status,
            "createdAt": row["created_at"].isoformat(),
            "completedAt": row["completed_at"].isoformat()
            if row["completed_at"]
            else None,
            "filename": row["filename"],
            "sizeBytes": row["size_bytes"],
            "errorCode": "survey_export_failed"
            if status in {"retrying", "failed"}
            else None,
        }
    )


class AsyncpgSurveyExports:
    def __init__(self, pool: asyncpg.Pool[Any], storage: ObjectStorage) -> None:
        self.pool = pool
        self.storage = storage

    def _object_location(self, row: Any) -> ObjectLocation:
        return ObjectLocation(
            self.storage.bucket,
            f"surveys/{row['survey_id']}/exports/{row['id']}/{export_filename(row['product'], str(row['snapshot_id']))}",
        )

    async def _cancel(self, conn: Any, row: Any) -> None:
        # A previous process may have uploaded before its DB transaction died.
        # Inspect only storage metadata, without loading/rendering revoked data.
        # If storage is unavailable, retry rather than completing cancellation
        # with an untracked private object that retention cannot remove.
        stored = await self.storage.head(self._object_location(row))
        if stored is None:
            await conn.execute(
                "UPDATE survey_export_job SET status='cancelled' WHERE id=$1", row["id"]
            )
            return
        await conn.execute(
            """UPDATE survey_export_job SET status='cancelled',completed_at=clock_timestamp(),
               bucket=$2,object_key=$3,object_version=$4,sha256=$5,size_bytes=$6,
               filename=$7,media_type=$8,render_version=$9 WHERE id=$1""",
            row["id"],
            stored.location.bucket,
            stored.location.key,
            stored.location.version_id,
            stored.sha256,
            stored.size_bytes,
            export_filename(row["product"], str(row["snapshot_id"])),
            stored.media_type,
            stored.metadata.get("render-version"),
        )

    async def _survey(self, conn: Any, survey_id: UUID) -> Any:
        # Same lock order as survey authoring. Retention must remove stored objects
        # and jobs explicitly before deleting snapshots/surveys; FKs prevent orphans.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", str(survey_id)
        )
        return await conn.fetchrow(
            "SELECT * FROM survey WHERE id=$1 FOR UPDATE", survey_id
        )

    async def create(
        self, user_id: UUID, survey_id: UUID, body: CreateSurveyExport
    ) -> SurveyExportJob:
        async with self.pool.acquire() as conn, conn.transaction():
            survey = await self._survey(conn, survey_id)
            can_test = await authorize(conn, user_id, survey, body.product)
            await read_snapshot(
                conn, survey_id, UUID(body.snapshotId), can_test=can_test
            )
            request_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
            existing = await conn.fetchrow(
                JOB_SELECT
                + " WHERE j.survey_id=$1 AND j.requested_by=$2 AND j.operation_id=$3",
                survey_id,
                user_id,
                body.operationId,
            )
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict(
                        "idempotency_conflict",
                        "Diese Operation wurde mit anderen Daten verwendet.",
                    )
                return job_payload(existing)
            job_id, event_id = uuid4(), uuid4()
            await conn.execute(
                """INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload)
              VALUES($1,'survey_export',$2,'survey.export.render.v1',$3,'{}'::jsonb)""",
                event_id,
                job_id,
                f"survey-export:{job_id}",
            )
            await conn.execute(
                """INSERT INTO survey_export_job(id,survey_id,snapshot_id,requested_by,operation_id,request_hash,title,product,event_id)
              VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                job_id,
                survey_id,
                UUID(body.snapshotId),
                user_id,
                body.operationId,
                request_hash,
                survey["title"],
                body.product,
                event_id,
            )
            return job_payload(
                await conn.fetchrow(JOB_SELECT + " WHERE j.id=$1", job_id)
            )

    async def _authorized_job(
        self, conn: Any, user_id: UUID, survey_id: UUID, job_id: UUID
    ) -> Any:
        survey = await self._survey(conn, survey_id)
        row = await conn.fetchrow(
            JOB_SELECT + " WHERE j.id=$1 AND j.survey_id=$2 AND j.requested_by=$3",
            job_id,
            survey_id,
            user_id,
        )
        if row is None:
            raise not_found()
        can_test = await authorize(conn, user_id, survey, row["product"])
        await read_snapshot(conn, survey_id, row["snapshot_id"], can_test=can_test)
        return row

    async def get(
        self, user_id: UUID, survey_id: UUID, job_id: UUID
    ) -> SurveyExportJob:
        async with self.pool.acquire() as conn, conn.transaction():
            return job_payload(
                await self._authorized_job(conn, user_id, survey_id, job_id)
            )

    async def download(
        self, user_id: UUID, survey_id: UUID, job_id: UUID
    ) -> SurveyExportArtifact:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await self._authorized_job(conn, user_id, survey_id, job_id)
            if row["status"] != "available":
                raise Conflict(
                    "export_not_ready", "Die Exportdatei ist noch nicht verfügbar."
                )
            retrieved = await self.storage.get(
                ObjectLocation(row["bucket"], row["object_key"], row["object_version"])
            )
            if (
                retrieved.stored.sha256 != row["sha256"]
                or len(retrieved.content) != row["size_bytes"]
                or hashlib.sha256(retrieved.content).hexdigest() != row["sha256"]
            ):
                raise SurveyExportJobError()
            # Revoked roles/grants during the object read must not authorize delivery.
            await self._authorized_job(conn, user_id, survey_id, job_id)
            return SurveyExportArtifact(
                row["filename"],
                row["media_type"],
                row["render_version"],
                retrieved.content,
            )

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        # No provider errors, source answers, object paths or renderer diagnostics
        # reach the outbox's persisted error detail or structured logs.
        try:
            await self._render(event)
        except Exception:
            raise SurveyExportJobError() from None

    async def _render(self, event: ClaimedOutboxEvent) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            identity = await conn.fetchrow(
                "SELECT survey_id FROM survey_export_job WHERE id=$1 AND event_id=$2",
                event.aggregate_id,
                event.id,
            )
            if identity is None:
                return
            survey = await self._survey(conn, identity["survey_id"])
            row = await conn.fetchrow(
                "SELECT * FROM survey_export_job WHERE id=$1 FOR UPDATE",
                event.aggregate_id,
            )
            if row is None:
                # Permanent deletion may have won the survey lock after the
                # preliminary identity lookup. There is nothing left to render.
                return
            if row["status"] in {"available", "cancelled"}:
                return
            try:
                can_test = await authorize(
                    conn, row["requested_by"], survey, row["product"]
                )
                payload = await read_snapshot(
                    conn, row["survey_id"], row["snapshot_id"], can_test=can_test
                )
            except ResourceNotFound:
                await self._cancel(conn, row)
                return
            responses = None
            if row["product"].startswith("responses_"):
                raw = await conn.fetchval(
                    "SELECT private_responses FROM survey_analysis_snapshot WHERE id=$1",
                    row["snapshot_id"],
                )
                responses = tuple(
                    IndividualResponse.model_validate(r) for r in json.loads(raw)
                )
            source = SurveyExportSource(
                row["title"], AnalysisSnapshot.model_validate(payload), responses
            )
            artifact = (
                await asyncio.to_thread(TypstSurveyRenderer().render, source)
                if row["product"] == "analysis_pdf"
                else await asyncio.to_thread(render_tabular, row["product"], source)
            )
            await self.storage.ensure_private_versioned_bucket()
            stored = await self.storage.put_immutable(
                ObjectWrite(
                    self._object_location(row),
                    artifact.content,
                    artifact.media_type,
                    artifact.sha256,
                    {"render-version": artifact.render_version},
                )
            )
            retrieved = await self.storage.get(stored.location)
            if retrieved.content != artifact.content:
                raise SurveyExportJobError()
            # Save the reference even on cancellation so retention can remove it.
            status = "available"
            try:
                can_test = await authorize(
                    conn, row["requested_by"], survey, row["product"]
                )
                await read_snapshot(
                    conn, row["survey_id"], row["snapshot_id"], can_test=can_test
                )
            except ResourceNotFound:
                status = "cancelled"
            await conn.execute(
                """UPDATE survey_export_job SET status=$2,completed_at=clock_timestamp(),bucket=$3,
              object_key=$4,object_version=$5,sha256=$6,size_bytes=$7,filename=$8,media_type=$9,render_version=$10 WHERE id=$1""",
                row["id"],
                status,
                stored.location.bucket,
                stored.location.key,
                stored.location.version_id,
                stored.sha256,
                stored.size_bytes,
                artifact.filename,
                artifact.media_type,
                artifact.render_version,
            )
