"""Transactional survey definitions and response snapshots."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.surveyjs_validation import validate_answers
from leonaid.adapters.mail.secure_payload import SecureMailPayload
from leonaid.adapters.postgres.survey_analysis import create_snapshot, read_snapshot
from leonaid.adapters.postgres.survey_deletion import deletion_payload, request_deletion
from leonaid.application.surveys.analysis_snapshot import AnalysisFilter
from leonaid.application.surveys.exports import SurveyExportSelection
from leonaid.adapters.postgres.survey_responses import (
    read_responses,
    selection_metadata,
)

from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.policies import may_manage_action
from leonaid.domain.surveys import (
    Capability,
    SurveyStatus,
    require_transition,
    effective_response_status,
    may_access_survey,
)
from leonaid.domain.surveys.validation import (
    PROFILE,
    validate_definition,
)


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def snapshot(row: Any) -> dict[str, Any]:
    status = effective_response_status(
        row["status"],
        created_at=row["created_at"],
        last_answer_changed_at=row["last_answer_changed_at"],
        timeout_seconds=row["inactivity_timeout_seconds"],
        now=datetime.now(timezone.utc),
    )
    return {
        "participationId": str(row["id"]),
        "versionId": str(row["version_id"]),
        "revision": row["revision"],
        "status": status,
        "answers": json.loads(row["answers"]),
        "currentPage": row["current_page"],
        "lastAnswerChangedAt": row["last_answer_changed_at"].isoformat()
        if row["last_answer_changed_at"]
        else None,
        "completedAt": row["completed_at"].isoformat() if row["completed_at"] else None,
        "diagnostics": [],
    }


def survey_payload(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "actionId": str(row["action_id"]) if row["action_id"] else None,
        "ownerUserId": str(row["owner_user_id"]),
        "status": row["status"],
        "accessMode": row["access_mode"],
        "revision": row["revision"],
        "publishedVersionId": str(row["published_version_id"])
        if row["published_version_id"]
        else None,
        "inactivityTimeoutSeconds": row["inactivity_timeout_seconds"],
        "endsAt": row["ends_at"].isoformat() if row["ends_at"] else None,
        "deletedAt": row["deleted_at"].isoformat() if row["deleted_at"] else None,
    }


def version_payload(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "surveyId": str(row["survey_id"]),
        "number": row["number"],
        "definition": json.loads(row["definition"]),
        "rendererVersion": row["renderer_version"],
        "capabilityProfile": row["capability_profile"],
        "publishedAt": row["published_at"].isoformat(),
    }


class AsyncpgSurveyRepository:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        *,
        invitation_mail: SecureMailPayload | None = None,
        public_base_url: str = "",
    ):
        self.pool = pool
        self.invitation_mail = invitation_mail
        self.public_base_url = public_base_url.rstrip("/")

    @staticmethod
    def _capabilities(
        actor: IdentityPrincipal, row: Any, grants: frozenset[Capability]
    ) -> list[str]:
        return [
            str(cap)
            for cap in Capability
            if may_access_survey(
                actor,
                owner_user_id=row["owner_user_id"],
                action_id=row["action_id"],
                capability=cap,
                grants=grants,
            )
        ]

    async def list_surveys(
        self, actor: IdentityPrincipal, status: str | None, search: str, offset: int
    ) -> dict[str, Any]:
        if not actor.account.can_authenticate:
            raise PermissionDenied("forbidden", "Kein Zugriff.")
        actions = list({m.action_id for m in actor.action_memberships})
        managed = [action for action in actions if may_manage_action(actor, action)]
        where = """WHERE ($1::boolean OR s.action_id=ANY($2::uuid[]) OR
            ((s.action_id IS NULL OR s.action_id=ANY($3::uuid[])) AND
            (s.owner_user_id=$4 OR EXISTS(SELECT 1 FROM survey_grant g WHERE g.survey_id=s.id AND g.user_id=$4))))
            AND ($5::text IS NULL OR s.status=$5) AND strpos(lower(s.title),lower($6))>0"""
        values = (
            actor.is_system_admin,
            managed,
            actions,
            actor.account.id,
            status,
            search,
        )
        async with (
            self.pool.acquire() as conn,
            conn.transaction(isolation="repeatable_read", readonly=True),
        ):
            total = await conn.fetchval(
                "SELECT count(*) FROM survey s " + where, *values
            )
            rows = await conn.fetch(
                "SELECT s.*, ARRAY(SELECT capability FROM survey_grant g WHERE g.survey_id=s.id AND g.user_id=$4) AS actor_grants FROM survey s "
                + where
                + " ORDER BY s.created_at DESC,s.id LIMIT 50 OFFSET $7",
                *values,
                offset,
            )
            items = []
            for row in rows:
                capabilities = self._capabilities(
                    actor, row, frozenset(Capability(c) for c in row["actor_grants"])
                )
                if not capabilities:
                    raise PermissionDenied(
                        "forbidden", "Zugriff konnte nicht bestätigt werden."
                    )
                items.append({**survey_payload(row), "capabilities": capabilities})
            action_rows = await conn.fetch(
                "SELECT id,name FROM charity_action WHERE $1::boolean OR id=ANY($2::uuid[]) ORDER BY name,id",
                actor.is_system_admin,
                managed,
            )
            return {
                "items": items,
                "total": total,
                "actions": [
                    {"id": str(r["id"]), "name": r["name"]} for r in action_rows
                ],
            }

    async def classify_overdue(self, limit: int = 1000) -> int:
        """Bounded repeatable sweep; locked writes are retried on the next sweep."""
        async with self.pool.acquire() as conn:
            result = await conn.fetch(
                """WITH due AS (
                    SELECT id FROM survey_participation
                    WHERE status='in_progress' AND
                        COALESCE(last_answer_changed_at,created_at)
                        + make_interval(secs => inactivity_timeout_seconds)
                        <= statement_timestamp()
                    ORDER BY id LIMIT $1 FOR UPDATE SKIP LOCKED
                ) UPDATE survey_participation p SET status='partial'
                  FROM due WHERE p.id=due.id RETURNING p.id""",
                limit,
            )
            return len(result)

    async def close_due_surveys(self, limit: int = 100) -> int:
        """Use the same survey-first lock ordering as respondent and author writes."""
        async with self.pool.acquire() as conn:
            return cast(
                int,
                await conn.fetchval(
                    """WITH due AS (
                    SELECT id FROM survey WHERE status='active'
                    AND ends_at<=statement_timestamp()
                    ORDER BY ends_at,id LIMIT $1 FOR UPDATE SKIP LOCKED
                ), closed AS (
                    UPDATE survey s SET status='ended',revision=revision+1,
                        updated_at=statement_timestamp()
                    FROM due WHERE s.id=due.id RETURNING s.id
                ), partial AS (
                    UPDATE survey_participation p SET status='partial'
                    FROM closed WHERE p.survey_id=closed.id AND p.status='in_progress'
                    RETURNING p.id
                ) SELECT count(*) FROM closed""",
                    limit,
                ),
            )

    async def settings(
        self, actor: IdentityPrincipal, body: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not actor.account.can_authenticate or not actor.is_system_admin:
            raise PermissionDenied(
                "forbidden", "Kein Zugriff auf die Grundeinstellung."
            )
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM survey_settings WHERE singleton FOR UPDATE"
            )
            if body is not None:
                replay = await conn.fetchrow(
                    "SELECT * FROM survey_settings_operation WHERE actor_id=$1 AND operation_id=$2",
                    actor.account.id,
                    body["operationId"],
                )
                if replay:
                    if replay["request_hash"] != digest(encoded(body)):
                        raise Conflict(
                            "idempotency_conflict",
                            "Operation mit anderen Daten wiederholt.",
                        )
                    return cast(dict[str, Any], json.loads(replay["response"]))
                if row["revision"] != body["expectedRevision"]:
                    raise Conflict(
                        "revision_conflict", "Die Grundeinstellung wurde geändert."
                    )
                row = await conn.fetchrow(
                    """UPDATE survey_settings SET inactivity_timeout_seconds=$1,
                    ended_retention_seconds=CASE WHEN $2 THEN $3 ELSE ended_retention_seconds END,
                    trash_retention_seconds=CASE WHEN $4 THEN $5 ELSE trash_retention_seconds END,
                    retention_configured_by=CASE WHEN $2 OR $4 THEN $6 ELSE retention_configured_by END,
                    revision=revision+1 WHERE singleton RETURNING *""",
                    body["inactivityTimeoutSeconds"],
                    "endedRetentionSeconds" in body,
                    body.get("endedRetentionSeconds"),
                    "trashRetentionSeconds" in body,
                    body.get("trashRetentionSeconds"),
                    actor.account.id,
                )
            result = {
                "inactivityTimeoutSeconds": row["inactivity_timeout_seconds"],
                "endedRetentionSeconds": row["ended_retention_seconds"],
                "trashRetentionSeconds": row["trash_retention_seconds"],
                "revision": row["revision"],
            }
            if body is not None:
                await conn.execute(
                    "INSERT INTO survey_settings_operation(actor_id,operation_id,request_hash,response) VALUES($1,$2,$3,$4::jsonb)",
                    actor.account.id,
                    body["operationId"],
                    digest(encoded(body)),
                    encoded(result),
                )
            return result

    async def _survey(self, conn: Any, survey_id: UUID) -> Any:
        row = await conn.fetchrow(
            "SELECT * FROM survey WHERE id=$1 FOR UPDATE", survey_id
        )
        if not row:
            raise ResourceNotFound("not_found", "Umfrage nicht gefunden.")
        return row

    async def _replay(
        self, conn: Any, survey_id: UUID, scope: str, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = await conn.fetchrow(
            "SELECT * FROM survey_operation WHERE survey_id=$1 AND scope=$2 AND operation_id=$3",
            survey_id,
            scope,
            body["operationId"],
        )
        if row:
            if row["request_hash"] != digest(encoded(body)):
                raise Conflict(
                    "idempotency_conflict",
                    "Diese Operation wurde mit anderen Daten verwendet.",
                )
            return cast(dict[str, Any], json.loads(row["response"]))
        return None

    async def _record(
        self,
        conn: Any,
        survey_id: UUID,
        scope: str,
        body: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        await conn.execute(
            "INSERT INTO survey_operation(survey_id,scope,operation_id,request_hash,response) VALUES($1,$2,$3,$4,$5::jsonb)",
            survey_id,
            scope,
            body["operationId"],
            digest(encoded(body)),
            encoded(result),
        )
        return result

    async def author(
        self,
        actor: IdentityPrincipal,
        survey_id: UUID,
        operation: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn, conn.transaction():
            # Includes creation, where no survey row exists yet. All subsequent writes lock its row.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", str(survey_id)
            )
            deletion = await conn.fetchrow(
                "SELECT * FROM survey_deletion WHERE survey_id=$1", survey_id
            )
            if deletion is not None:
                if (
                    operation != "delete-permanently"
                    or deletion["requested_by"] != actor.account.id
                    or not actor.account.can_authenticate
                ):
                    raise ResourceNotFound("not_found", "Umfrage nicht gefunden.")
                if (
                    deletion["operation_hash"]
                    != hashlib.sha256(body["operationId"].encode()).hexdigest()
                    or deletion["expected_revision"] != body["expectedRevision"]
                ):
                    raise Conflict(
                        "idempotency_conflict",
                        "Die endgültige Löschung wurde bereits beauftragt.",
                    )
                return deletion_payload(deletion)
            if operation == "create":
                if not actor.account.can_authenticate:
                    raise PermissionDenied("forbidden", "Kein Zugriff.")
                validate_definition(body["definition"])
                action_id = UUID(body["actionId"]) if body.get("actionId") else None
                if action_id is not None and (
                    not may_manage_action(actor, action_id)
                    or not await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM charity_action WHERE id=$1)",
                        action_id,
                    )
                ):
                    raise ResourceNotFound("not_found", "Aktion nicht gefunden.")
                await conn.execute(
                    "INSERT INTO survey(id,title,owner_user_id,inactivity_timeout_seconds,action_id) VALUES($1,$2,$3,$4,$5) ON CONFLICT(id) DO NOTHING",
                    survey_id,
                    body["title"],
                    actor.account.id,
                    body.get("inactivityTimeoutSeconds"),
                    action_id,
                )
            survey = await self._survey(conn, survey_id)
            grants = frozenset(
                Capability(r["capability"])
                for r in await conn.fetch(
                    "SELECT capability FROM survey_grant WHERE survey_id=$1 AND user_id=$2",
                    survey_id,
                    actor.account.id,
                )
            )
            capability = Capability.DESIGN
            if operation == "delete-permanently":
                capability = Capability.DELETE
            if operation.startswith("analysis-"):
                capability = Capability.VIEW_AGGREGATES
            if operation.startswith("response-"):
                capability = Capability.READ_RESPONSES
            if operation.startswith("export-selection-"):
                capabilities = self._capabilities(actor, survey, grants)
                capability = (
                    Capability.EXPORT_RAW
                    if "export_raw" in capabilities
                    else Capability.EXPORT_REPORTS
                )
            if operation.startswith("invitation"):
                capability = Capability.MANAGE_INVITATIONS
            if operation == "summary":
                capabilities = self._capabilities(actor, survey, grants)
                if not capabilities:
                    raise ResourceNotFound("not_found", "Umfrage nicht gefunden.")
                return {**survey_payload(survey), "capabilities": capabilities}
            if (
                operation in {"publish", "schedule", "access"}
                or operation == "transition"
                and body["action"] == "end"
            ):
                capability = Capability.PUBLISH
            elif operation == "transition":
                capability = (
                    Capability.DELETE
                    if body["action"] in {"trash", "restore"}
                    else Capability.ARCHIVE
                )
            if not may_access_survey(
                actor,
                owner_user_id=survey["owner_user_id"],
                action_id=survey["action_id"],
                capability=capability,
                grants=grants,
            ):
                raise ResourceNotFound("not_found", "Umfrage nicht gefunden.")
            if operation == "delete-permanently":
                if survey["status"] != "deleted":
                    raise Conflict(
                        "survey_transition_invalid",
                        "Die Umfrage muss zuerst im Papierkorb liegen.",
                    )
                if survey["revision"] != body["expectedRevision"]:
                    raise Conflict(
                        "revision_conflict",
                        "Die Umfrage wurde zwischenzeitlich geändert.",
                    )
                return await request_deletion(
                    conn, survey, actor.account.id, body["operationId"]
                )
            if operation.startswith("invitation"):
                return await self._invitation(conn, actor, survey, operation, body)
            if operation.startswith(("analysis-", "response-", "export-selection-")):
                if survey["status"] == "deleted":
                    raise Conflict("closed", "Die Umfrage wurde gelöscht.")
                can_test = "design" in self._capabilities(actor, survey, grants)
                if operation in {
                    "analysis-versions",
                    "response-versions",
                    "export-selection-versions",
                }:
                    versions = await conn.fetch(
                        "SELECT id,number,published_at FROM survey_version WHERE survey_id=$1 ORDER BY number DESC",
                        survey_id,
                    )
                    return {
                        "items": [
                            {
                                "id": str(row["id"]),
                                "number": row["number"],
                                "publishedAt": row["published_at"].isoformat(),
                            }
                            for row in versions
                        ]
                    }
                if operation == "analysis-get":
                    return await read_snapshot(
                        conn, survey_id, UUID(body["snapshotId"]), can_test=can_test
                    )
                if operation.startswith("response-") and operation != "response-create":
                    return await read_responses(
                        conn,
                        survey_id,
                        UUID(body["snapshotId"]),
                        operation,
                        body,
                        can_test=can_test,
                    )
                filters = AnalysisFilter.model_validate(body["filter"])
                if filters.isTest and not can_test:
                    raise ResourceNotFound("not_found", "Auswertung nicht gefunden.")
                scope = f"author:{actor.account.id}:{operation}"
                replay = await self._replay(conn, survey_id, scope, body)
                if replay is not None:
                    return replay
                result = await create_snapshot(conn, survey, filters)
                if operation == "response-create":
                    result = selection_metadata(result)
                elif operation == "export-selection-create":
                    result = SurveyExportSelection.model_validate(
                        {key: result[key] for key in SurveyExportSelection.model_fields}
                    ).model_dump()
                return await self._record(conn, survey_id, scope, body, result)
            if operation == "access":
                scope = f"author:{actor.account.id}:access"
                replay = await self._replay(conn, survey_id, scope, body)
                if replay is not None:
                    return replay
                if survey["status"] != "draft":
                    raise Conflict(
                        "closed",
                        "Der Zugangsmodus kann nur vor der Veröffentlichung geändert werden.",
                    )
                if survey["revision"] != body["expectedRevision"]:
                    raise Conflict("revision_conflict", "Die Umfrage wurde geändert.")
                updated = await conn.fetchrow(
                    "UPDATE survey SET access_mode=$2,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
                    survey_id,
                    body["accessMode"],
                )
                return await self._record(
                    conn, survey_id, scope, body, survey_payload(updated)
                )
            if operation == "settings":
                if survey["status"] == "deleted":
                    raise Conflict("closed", "Umfrage ist gelöscht.")
                scope = f"author:{actor.account.id}:settings"
                replay = await self._replay(conn, survey_id, scope, body)
                if replay is not None:
                    return replay
                if survey["revision"] != body["expectedRevision"]:
                    raise Conflict("revision_conflict", "Die Umfrage wurde geändert.")
                updated = await conn.fetchrow(
                    "UPDATE survey SET inactivity_timeout_seconds=$2,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
                    survey_id,
                    body["inactivityTimeoutSeconds"],
                )
                return await self._record(
                    conn, survey_id, scope, body, survey_payload(updated)
                )
            if operation == "schedule":
                scope = f"author:{actor.account.id}:schedule"
                replay = await self._replay(conn, survey_id, scope, body)
                if replay is not None:
                    return replay
                now = datetime.now(timezone.utc)
                if survey["status"] not in {"draft", "active"} or (
                    survey["status"] == "active"
                    and survey["ends_at"]
                    and survey["ends_at"] <= now
                ):
                    raise Conflict("closed", "Diese Umfrage ist bereits geschlossen.")
                if survey["revision"] != body["expectedRevision"]:
                    raise Conflict("revision_conflict", "Die Umfrage wurde geändert.")
                deadline = (
                    datetime.fromisoformat(body["endsAt"]) if body["endsAt"] else None
                )
                if deadline is not None and deadline <= now:
                    raise DomainInvariantError(
                        "invalid_end_time",
                        "Das geplante Ende muss in der Zukunft liegen.",
                    )
                updated = await conn.fetchrow(
                    "UPDATE survey SET ends_at=$2,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *",
                    survey_id,
                    deadline,
                )
                return await self._record(
                    conn, survey_id, scope, body, survey_payload(updated)
                )
            if operation in {"transition", "duplicate"}:
                return await self._lifecycle(conn, actor, survey, operation, body)
            if survey["status"] in {"ended", "archived", "deleted"}:
                raise Conflict("closed", "Umfrage ist geschlossen.")
            if survey["ends_at"] and survey["ends_at"] <= datetime.now(timezone.utc):
                if survey["status"] == "active" or operation == "publish":
                    raise Conflict("closed", "Das geplante Ende ist bereits erreicht.")
            if operation in {"draft", "validate"}:
                draft = await conn.fetchrow(
                    "SELECT * FROM survey_draft WHERE survey_id=$1", survey_id
                )
                if operation == "validate":
                    if draft["revision"] != body["expectedRevision"]:
                        raise Conflict(
                            "revision_conflict",
                            "Der Entwurf wurde zwischenzeitlich geändert.",
                        )
                    validate_definition(json.loads(draft["definition"]))
                return {
                    "surveyId": str(survey_id),
                    "revision": draft["revision"],
                    "definition": json.loads(draft["definition"]),
                }
            scope = f"author:{actor.account.id}:{operation}"
            replay = await self._replay(conn, survey_id, scope, body)
            if replay is not None:
                return replay
            if operation == "create":
                if await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM survey_draft WHERE survey_id=$1)",
                    survey_id,
                ):
                    raise Conflict("revision_conflict", "Umfrage existiert bereits.")
                await conn.execute(
                    "INSERT INTO survey_draft(survey_id,definition) VALUES($1,$2::jsonb)",
                    survey_id,
                    encoded(body["definition"]),
                )
                result = {
                    "surveyId": str(survey_id),
                    "revision": 1,
                    "definition": body["definition"],
                }
            else:
                draft = await conn.fetchrow(
                    "SELECT * FROM survey_draft WHERE survey_id=$1 FOR UPDATE",
                    survey_id,
                )
                if draft["revision"] != body["expectedRevision"]:
                    raise Conflict(
                        "revision_conflict",
                        "Der Entwurf wurde zwischenzeitlich geändert.",
                    )
                if operation == "save":
                    # Publication performs profile validation. Drafts retain unsupported JSON for editing.
                    await conn.execute(
                        "UPDATE survey_draft SET definition=$2::jsonb, revision=revision+1, updated_at=now() WHERE survey_id=$1",
                        survey_id,
                        encoded(body["definition"]),
                    )
                    result = {
                        "surveyId": str(survey_id),
                        "revision": draft["revision"] + 1,
                        "definition": body["definition"],
                    }
                else:
                    definition = json.loads(draft["definition"])
                    validate_definition(definition)
                    version_id = uuid4()
                    number = await conn.fetchval(
                        "SELECT COALESCE(max(number),0)+1 FROM survey_version WHERE survey_id=$1",
                        survey_id,
                    )
                    version = await conn.fetchrow(
                        "INSERT INTO survey_version(id,survey_id,number,definition,schema_hash,renderer_version,capability_profile) VALUES($1,$2,$3,$4::jsonb,$5,'3.0.3',$6) RETURNING *",
                        version_id,
                        survey_id,
                        number,
                        encoded(definition),
                        digest(encoded(definition)),
                        PROFILE,
                    )
                    await conn.execute(
                        "UPDATE survey SET published_version_id=$2,status='active',revision=revision+1,updated_at=now() WHERE id=$1",
                        survey_id,
                        version_id,
                    )
                    await conn.execute(
                        "UPDATE survey_draft SET revision=revision+1 WHERE survey_id=$1",
                        survey_id,
                    )
                    result = version_payload(version)
            return await self._record(conn, survey_id, scope, body, result)

    async def _lifecycle(
        self,
        conn: Any,
        actor: IdentityPrincipal,
        survey: Any,
        operation: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        survey_id = survey["id"]
        scope = f"author:{actor.account.id}:{operation}"
        replay = await self._replay(conn, survey_id, scope, body)
        if replay is not None:
            return replay
        if survey["revision"] != body["expectedRevision"]:
            raise Conflict(
                "revision_conflict", "Die Umfrage wurde zwischenzeitlich geändert."
            )
        if operation == "transition":
            action = body["action"]
            if action == "restore":
                if survey["status"] != "deleted":
                    raise Conflict(
                        "survey_transition_invalid",
                        "Diese Umfrage ist nicht wiederherstellbar.",
                    )
                target = (
                    SurveyStatus.ENDED
                    if survey["published_version_id"]
                    else SurveyStatus.DRAFT
                )
            else:
                target = {
                    "end": SurveyStatus.ENDED,
                    "unarchive": SurveyStatus.ENDED,
                    "archive": SurveyStatus.ARCHIVED,
                    "trash": SurveyStatus.DELETED,
                }[action]
                if action == "unarchive" and survey["status"] != "archived":
                    raise Conflict(
                        "survey_transition_invalid",
                        "Nur archivierte Umfragen können aus dem Archiv geholt werden.",
                    )
                if action == "end" and survey["status"] != "active":
                    raise Conflict(
                        "survey_transition_invalid",
                        "Nur aktive Umfragen können beendet werden.",
                    )
            require_transition(
                SurveyStatus(survey["status"]),
                target,
                has_published_version=survey["published_version_id"] is not None,
            )
            row = await conn.fetchrow(
                """UPDATE survey SET status=$2, revision=revision+1, updated_at=clock_timestamp(),
                deleted_at=CASE WHEN $2='deleted' THEN clock_timestamp() ELSE NULL END,
                ends_at=CASE WHEN status='active' THEN clock_timestamp() ELSE ends_at END
                WHERE id=$1 RETURNING *""",
                survey_id,
                str(target),
            )
            if survey["status"] == "active":
                await conn.execute(
                    "UPDATE survey_participation SET status='partial' WHERE survey_id=$1 AND status='in_progress'",
                    survey_id,
                )
            result = survey_payload(row)
        else:
            if survey["status"] == "deleted":
                raise Conflict("closed", "Gelöschte Umfragen zuerst wiederherstellen.")
            target_id = UUID(body["targetSurveyId"])
            if target_id == survey_id:
                raise Conflict(
                    "revision_conflict", "Die Kopie benötigt eine eigene ID."
                )
            # Copy an immutable publication if present; never copy collected data or grants.
            definition = (
                await conn.fetchval(
                    "SELECT definition FROM survey_version WHERE id=$1",
                    survey["published_version_id"],
                )
                if survey["published_version_id"]
                else await conn.fetchval(
                    "SELECT definition FROM survey_draft WHERE survey_id=$1", survey_id
                )
            )
            row = await conn.fetchrow(
                """INSERT INTO survey(id,title,owner_user_id,inactivity_timeout_seconds)
                VALUES($1,$2,$3,$4) ON CONFLICT(id) DO NOTHING RETURNING *""",
                target_id,
                body["title"],
                actor.account.id,
                survey["inactivity_timeout_seconds"],
            )
            if row is None:
                raise Conflict("revision_conflict", "Die Ziel-ID ist bereits vergeben.")
            await conn.execute(
                "INSERT INTO survey_draft(survey_id,definition) VALUES($1,$2::jsonb)",
                target_id,
                definition,
            )
            result = survey_payload(row)
        return await self._record(conn, survey_id, scope, body, result)

    @staticmethod
    def _invitation_payload(row: Any) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        state = (
            "revoked"
            if row["revoked_at"]
            else "expired"
            if row["expires_at"] <= now
            else "redeemed"
            if row["redeemed_at"]
            else "sent"
            if row["sent_at"]
            else "cancelled"
            if row["mail_payload"] is None
            else "failed"
            if row.get("delivery_state") == "dead_letter"
            else "retrying"
            if row.get("delivery_error")
            else "queued"
        )
        return {
            "id": str(row["id"]),
            "recipientEmail": row["recipient_email"],
            "recipientName": row["recipient_name"],
            "status": state,
            "expiresAt": row["expires_at"].isoformat(),
            "createdAt": row["created_at"].isoformat(),
        }

    async def _invitation(
        self,
        conn: Any,
        actor: IdentityPrincipal,
        survey: Any,
        operation: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        sid = survey["id"]
        if survey["status"] == "deleted":
            raise Conflict("closed", "Die Umfrage wurde gelöscht.")
        if operation == "invitation-list":
            rows = await conn.fetch(
                """SELECT i.*, e.status AS delivery_state, e.last_error_code AS delivery_error
                FROM survey_invitation i LEFT JOIN outbox_event e
                ON e.idempotency_key='survey-invitation:' || i.id::text
                WHERE i.survey_id=$1 ORDER BY i.created_at DESC,i.id LIMIT 100 OFFSET $2""",
                sid,
                body["offset"],
            )
            return {
                "items": [self._invitation_payload(row) for row in rows],
                "total": await conn.fetchval(
                    "SELECT count(*) FROM survey_invitation WHERE survey_id=$1", sid
                ),
            }
        scope = f"author:{actor.account.id}:{operation}"
        replay = await self._replay(conn, sid, scope, body)
        if replay is not None:
            return replay
        if survey["revision"] != body["expectedRevision"]:
            raise Conflict("revision_conflict", "Die Umfrage wurde geändert.")
        if operation == "invitation-revoke":
            row = await conn.fetchrow(
                "UPDATE survey_invitation SET revoked_at=COALESCE(revoked_at,now()),mail_payload=NULL WHERE id=$1 AND survey_id=$2 RETURNING *",
                UUID(body["invitationId"]),
                sid,
            )
            if row is None:
                raise ResourceNotFound("not_found", "Einladung nicht gefunden.")
        else:
            if (
                survey["status"] != "active"
                or survey["access_mode"] != "invitation"
                or (
                    survey["ends_at"]
                    and survey["ends_at"] <= datetime.now(timezone.utc)
                )
            ):
                raise Conflict(
                    "closed",
                    "Einladungen sind nur für aktive Umfragen mit Einladungszugang möglich.",
                )
            if self.invitation_mail is None or not self.public_base_url:
                raise Conflict(
                    "temporarily_unavailable", "Einladungsversand ist nicht verfügbar."
                )
            iid, token = uuid4(), secrets.token_urlsafe(48)
            expires = datetime.now(timezone.utc) + timedelta(days=body["expiresInDays"])
            mail = self.invitation_mail.protect(
                recipient=body["recipientEmail"],
                subject="Ihre Rückmeldung: " + " ".join(survey["title"].split()),
                text=f"Sie sind zur Umfrage {survey['title']} eingeladen.\n\nIhre Antworten können dieser Einladung zugeordnet werden.\n\n{self.public_base_url}/surveys/{sid}#invitation={token}\n\nGültig bis {expires.isoformat()}. Bitte geben Sie diesen persönlichen Link nicht weiter.",
            )
            row = await conn.fetchrow(
                "INSERT INTO survey_invitation(id,survey_id,recipient_email,recipient_name,token_digest,expires_at,mail_payload) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *",
                iid,
                sid,
                body["recipientEmail"],
                body["recipientName"],
                digest(token),
                expires,
                mail["secureMail"],
            )
            await conn.execute(
                "INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload) VALUES($1,'survey_invitation',$2,'survey.invitation.send.v1',$3,'{}'::jsonb)",
                uuid4(),
                iid,
                f"survey-invitation:{iid}",
            )
        return await self._record(conn, sid, scope, body, self._invitation_payload(row))

    async def participate(
        self,
        survey_id: UUID,
        participation_id: UUID | None,
        operation: str,
        body: dict[str, Any],
        secret: str,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn, conn.transaction():
            survey = await self._survey(conn, survey_id)
            now = datetime.now(timezone.utc)
            if (
                survey["status"] != "active"
                or survey["ends_at"]
                and survey["ends_at"] <= now
            ):
                raise Conflict("closed", "Diese Umfrage nimmt keine Antworten mehr an.")
            if (
                operation in {"definition", "start"}
                and survey["access_mode"] != "anonymous"
            ):
                raise PermissionDenied("forbidden", "Einladung erforderlich.")
            if operation == "definition":
                return version_payload(
                    await conn.fetchrow(
                        "SELECT * FROM survey_version WHERE id=$1",
                        survey["published_version_id"],
                    )
                )
            if not 32 <= len(secret) <= 256:
                raise PermissionDenied("forbidden", "Teilnahmezugang fehlt.")
            secret_hash = digest(secret)
            if operation == "redeem":
                if survey["access_mode"] != "invitation":
                    raise PermissionDenied(
                        "forbidden", "Diese Umfrage verwendet keine Einladungen."
                    )
                invitation = await conn.fetchrow(
                    "SELECT * FROM survey_invitation WHERE survey_id=$1 AND token_digest=$2 FOR UPDATE",
                    survey_id,
                    secret_hash,
                )
                if (
                    not invitation
                    or invitation["revoked_at"]
                    or invitation["expires_at"] <= now
                ):
                    raise ResourceNotFound(
                        "not_found", "Einladung nicht gefunden oder nicht mehr gültig."
                    )
                if invitation["participation_id"]:
                    row = await conn.fetchrow(
                        "SELECT * FROM survey_participation WHERE id=$1 FOR UPDATE",
                        invitation["participation_id"],
                    )
                else:
                    timeout = survey[
                        "inactivity_timeout_seconds"
                    ] or await conn.fetchval(
                        "SELECT inactivity_timeout_seconds FROM survey_settings WHERE singleton"
                    )
                    row = await conn.fetchrow(
                        "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,inactivity_timeout_seconds,expires_at) VALUES($1,$2,$3,$4,$5,$6) RETURNING *",
                        uuid4(),
                        survey_id,
                        survey["published_version_id"],
                        secret_hash,
                        timeout,
                        invitation["expires_at"],
                    )
                    await conn.execute(
                        "UPDATE survey_invitation SET participation_id=$2,redeemed_at=now() WHERE id=$1",
                        invitation["id"],
                        row["id"],
                    )
            elif operation == "start":
                scope = f"start:{secret_hash}"
                replay = await self._replay(conn, survey_id, scope, body)
                if replay is not None:
                    return replay
                timeout = survey["inactivity_timeout_seconds"] or await conn.fetchval(
                    "SELECT inactivity_timeout_seconds FROM survey_settings WHERE singleton"
                )
                row = await conn.fetchrow(
                    "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,inactivity_timeout_seconds) VALUES($1,$2,$3,$4,$5) RETURNING *",
                    uuid4(),
                    survey_id,
                    survey["published_version_id"],
                    secret_hash,
                    timeout,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM survey_participation WHERE id=$1 AND survey_id=$2 FOR UPDATE",
                    participation_id,
                    survey_id,
                )
                if (
                    not row
                    or not hmac.compare_digest(row["resume_digest"], secret_hash)
                    or row["revoked_at"]
                    or row["expires_at"]
                    and row["expires_at"] <= now
                ):
                    raise ResourceNotFound("not_found", "Teilnahme nicht gefunden.")
            if row["revoked_at"] or (row["expires_at"] and row["expires_at"] <= now):
                raise ResourceNotFound("not_found", "Teilnahme nicht gefunden.")
            denied_invitation = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM survey_invitation WHERE participation_id=$1 AND (revoked_at IS NOT NULL OR expires_at<=$2))",
                row["id"],
                now,
            )
            if denied_invitation:
                raise ResourceNotFound("not_found", "Teilnahme nicht gefunden.")
            version = await conn.fetchrow(
                "SELECT * FROM survey_version WHERE id=$1", row["version_id"]
            )
            if operation in {"start", "restore", "redeem"}:
                result = {
                    "id": str(row["id"]),
                    "version": version_payload(version),
                    "response": snapshot(row),
                    "inactivityTimeoutSeconds": row["inactivity_timeout_seconds"],
                }
                return (
                    await self._record(conn, survey_id, scope, body, result)
                    if operation == "start"
                    else result
                )
            scope = f"participation:{row['id']}:{operation}"
            replay = await self._replay(conn, survey_id, scope, body)
            if replay is not None:
                return replay
            if row["status"] == "completed":
                raise Conflict("closed", "Die Teilnahme ist bereits abgeschlossen.")
            if row["revision"] != body["expectedRevision"]:
                raise Conflict(
                    "revision_conflict", "Ein neuerer Antwortstand ist vorhanden."
                )
            definition = json.loads(version["definition"])
            answers = (
                body["answers"] if operation == "save" else json.loads(row["answers"])
            )
            clean = await validate_answers(
                definition, answers, complete=operation == "complete"
            )
            page = body.get("currentPage", row["current_page"])
            if page is not None and page not in {
                p["name"] for p in definition["pages"]
            }:
                raise Conflict("invalid_response", "Unbekannte Fragebogenseite.")
            changed = clean != json.loads(row["answers"])
            row = await conn.fetchrow(
                """UPDATE survey_participation SET answers=$2::jsonb,current_page=$3,revision=revision+1,
                last_answer_changed_at=CASE WHEN $4 THEN clock_timestamp() ELSE last_answer_changed_at END,
                status=CASE WHEN $5 THEN 'completed' WHEN $4 THEN 'in_progress' ELSE status END,
                completed_at=CASE WHEN $5 THEN clock_timestamp() ELSE NULL END WHERE id=$1 RETURNING *""",
                row["id"],
                encoded(clean),
                page,
                changed,
                operation == "complete",
            )
            return await self._record(conn, survey_id, scope, body, snapshot(row))
