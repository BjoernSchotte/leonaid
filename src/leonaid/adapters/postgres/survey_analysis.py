"""Freeze authorized, version-explicit response selections and their aggregates."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from leonaid.adapters.surveyjs_validation import aggregate_batch
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.surveys.analysis import QuestionAggregate
from leonaid.application.surveys.analysis_snapshot import (
    AnalysisFilter,
    AnalysisSnapshot,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.surveys.validation import json_size


async def aggregate_selection(
    definition: dict[str, Any], responses: list[dict[str, Any]]
) -> list[QuestionAggregate]:
    """Combine bounded batches from counts/sums, never from averaged percentages."""
    batches: list[list[dict[str, Any]]] = []
    batch: list[dict[str, Any]] = []
    size = json_size(
        {"profile": "initial-v1", "definition": definition, "responses": []}
    )
    used = size
    for answers in responses:
        added = json_size(answers) + 1
        if batch and (len(batch) == 100 or used + added > 550_000):
            batches.append(batch)
            batch, used = [], size
        batch.append(answers)
        used += added
    if batch or not batches:
        batches.append(batch)
    result: list[QuestionAggregate] | None = None
    for part in batches:
        values = await aggregate_batch(definition, part)
        if result is None:
            result = values
            continue
        for total, addition in zip(result, values, strict=True):
            for field in ("relevant", "answered", "unanswered", "hidden", "invalid"):
                setattr(total, field, getattr(total, field) + getattr(addition, field))
            if addition.sum is not None:
                total.sum = (total.sum or 0) + addition.sum
                assert addition.minimum is not None and addition.maximum is not None
                total.minimum = min(
                    total.minimum if total.minimum is not None else addition.minimum,
                    addition.minimum,
                )
                total.maximum = max(
                    total.maximum if total.maximum is not None else addition.maximum,
                    addition.maximum,
                )
            for bucket, other in zip(total.counts, addition.counts, strict=True):
                bucket.count += other.count
            for row, other_row in zip(
                total.matrixRows, addition.matrixRows, strict=True
            ):
                row.answered += other_row.answered
                row.unanswered += other_row.unanswered
                row.invalid += other_row.invalid
                for bucket, other in zip(row.counts, other_row.counts, strict=True):
                    bucket.count += other.count
    assert result is not None
    sources = [q for page in definition["pages"] for q in page["elements"]]
    for question, source in zip(result, sources, strict=True):
        question.mean = (
            question.sum / question.answered
            if question.sum is not None and question.answered
            else None
        )
        for bucket in question.counts:
            bucket.percentage = (
                bucket.count / question.answered * 100 if question.answered else None
            )
        for row in question.matrixRows:
            for bucket in row.counts:
                bucket.percentage = (
                    bucket.count / row.answered * 100 if row.answered else None
                )
        if (
            source["type"] == "rating"
            and source.get("rateMin") == 0
            and source.get("rateMax") == 10
            and source.get("rateStep", 1) == 1
        ):
            promoters = sum(
                item.count for item in question.counts if float(item.value) >= 9
            )
            detractors = sum(
                item.count for item in question.counts if float(item.value) <= 6
            )
            question.nps = (
                (promoters - detractors) / question.answered * 100
                if question.answered
                else None
            )
    return [QuestionAggregate.model_validate(q.model_dump()) for q in result]


async def read_snapshot(
    conn: Any, survey_id: UUID, snapshot_id: UUID, *, can_test: bool
) -> dict[str, Any]:
    payload = await conn.fetchval(
        "SELECT payload FROM survey_analysis_snapshot WHERE survey_id=$1 AND id=$2",
        survey_id,
        snapshot_id,
    )
    if payload is None:
        raise ResourceNotFound("not_found", "Auswertung nicht gefunden.")
    result = AnalysisSnapshot.model_validate_json(payload)
    if result.filter.isTest and not can_test:
        raise ResourceNotFound("not_found", "Auswertung nicht gefunden.")
    return result.model_dump()


async def create_snapshot(
    conn: Any, survey: Any, filters: AnalysisFilter
) -> dict[str, Any]:
    """Caller holds the survey lock, so response/lifecycle writes cannot change selection."""
    version = await conn.fetchrow(
        "SELECT * FROM survey_version WHERE survey_id=$1 AND id=$2",
        survey["id"],
        UUID(filters.versionId),
    )
    if version is None:
        raise ResourceNotFound("not_found", "Version nicht gefunden.")
    if (
        version["capability_profile"] != "initial-v1"
        or version["renderer_version"] != "3.0.3"
    ):
        raise Conflict(
            "unsupported_capability", "Diese Version kann nicht ausgewertet werden."
        )
    captured_at = await conn.fetchval("SELECT clock_timestamp()")
    closed = survey["status"] in {"ended", "archived"} or bool(
        survey["ends_at"] and survey["ends_at"] <= captured_at
    )
    args = (
        survey["id"],
        version["id"],
        filters.isTest,
        datetime.fromisoformat(filters.createdFrom) if filters.createdFrom else None,
        datetime.fromisoformat(filters.createdBefore)
        if filters.createdBefore
        else None,
        captured_at,
        closed,
    )
    scoped = """WITH scoped AS (
        SELECT p.*, CASE WHEN status='completed' THEN 'completed'
          WHEN status='partial' OR $7::boolean OR
            COALESCE(last_answer_changed_at,created_at) + inactivity_timeout_seconds * interval '1 second' <= $6
          THEN 'partial' ELSE 'in_progress' END AS effective_status
        FROM survey_participation p WHERE survey_id=$1 AND version_id=$2 AND is_test=$3
          AND ($4::timestamptz IS NULL OR created_at >= $4)
          AND ($5::timestamptz IS NULL OR created_at < $5)
    ) """
    counts = await conn.fetch(
        scoped
        + "SELECT effective_status,count(*) AS n,COALESCE(sum(octet_length(answers::text)),0) AS bytes FROM scoped GROUP BY effective_status",
        *args,
    )
    status_counts = {status: 0 for status in ("in_progress", "partial", "completed")}
    selected_count, selected_bytes = 0, 0
    for row in counts:
        status_counts[row["effective_status"]] = row["n"]
        if row["effective_status"] in filters.statuses:
            selected_count += row["n"]
            selected_bytes += row["bytes"]
    if selected_count > 5000 or selected_bytes > 32 * 1024 * 1024:
        raise DomainInvariantError(
            "limit_exceeded", "Bitte grenzen Sie die Auswertung zeitlich ein."
        )
    rows = await conn.fetch(
        scoped
        + "SELECT id,revision,answers,current_page,created_at,completed_at,effective_status FROM scoped WHERE effective_status=ANY($8::text[]) ORDER BY created_at,id",
        *args,
        filters.statuses,
    )
    definition = json.loads(version["definition"])
    private = [
        {
            "participationId": str(row["id"]),
            "revision": row["revision"],
            "status": row["effective_status"],
            "answers": json.loads(row["answers"]),
            "currentPage": row["current_page"],
            "createdAt": row["created_at"].isoformat(),
            "completedAt": row["completed_at"].isoformat()
            if row["completed_at"]
            else None,
        }
        for row in rows
    ]
    questions = await aggregate_selection(
        definition, [row["answers"] for row in private]
    )
    pages: dict[str | None, dict[str, Any]] = {
        page["name"]: {
            "pageId": page["name"],
            "title": page.get("title", page["name"]),
            "count": 0,
        }
        for page in definition["pages"]
    }
    pages[None] = {"pageId": None, "title": "Keine bekannte Seite", "count": 0}
    for row in rows:
        page = row["current_page"] if row["current_page"] in pages else None
        pages[page]["count"] += 1
    snapshot_id = uuid4()
    result = AnalysisSnapshot.model_validate(
        {
            "id": str(snapshot_id),
            "surveyId": str(survey["id"]),
            "createdAt": captured_at.isoformat(),
            "filter": filters.model_dump(),
            "versionNumber": version["number"],
            "rendererVersion": version["renderer_version"],
            "capabilityProfile": version["capability_profile"],
            "participationCount": selected_count,
            "statusCounts": status_counts,
            "lastPageCounts": list(pages.values()),
            "questions": [question.model_dump() for question in questions],
        }
    )
    await conn.execute(
        "INSERT INTO survey_analysis_snapshot(id,survey_id,version_id,payload,private_responses,created_at) VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6)",
        snapshot_id,
        survey["id"],
        version["id"],
        result.model_dump_json(),
        json.dumps(private, allow_nan=False),
        captured_at,
    )
    return result.model_dump()
