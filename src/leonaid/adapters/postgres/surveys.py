"""Transactional survey definitions and response snapshots."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.surveys import (
    Capability,
    SurveyStatus,
    require_transition,
    effective_response_status,
    may_access_survey,
)
from leonaid.domain.surveys.validation import (
    PROFILE,
    validate_answers,
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
        "status": row["status"],
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
    def __init__(self, pool: asyncpg.Pool[Any]):
        self.pool = pool

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
            if operation == "create":
                if not actor.account.can_authenticate:
                    raise PermissionDenied("forbidden", "Kein Zugriff.")
                validate_definition(body["definition"])
                await conn.execute(
                    "INSERT INTO survey(id,title,owner_user_id,inactivity_timeout_seconds) VALUES($1,$2,$3,$4) ON CONFLICT(id) DO NOTHING",
                    survey_id,
                    body["title"],
                    actor.account.id,
                    body.get("inactivityTimeoutSeconds"),
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
            if (
                operation == "publish"
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
            if operation == "summary":
                return survey_payload(survey)
            if operation in {"transition", "duplicate"}:
                return await self._lifecycle(conn, actor, survey, operation, body)
            if survey["status"] in {"ended", "archived", "deleted"}:
                raise Conflict("closed", "Umfrage ist geschlossen.")
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
            if operation == "start":
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
            version = await conn.fetchrow(
                "SELECT * FROM survey_version WHERE id=$1", row["version_id"]
            )
            if operation in {"start", "restore"}:
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
            clean = validate_answers(
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
