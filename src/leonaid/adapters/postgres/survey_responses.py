"""Read frozen raw projections only after the caller authorizes read_responses."""

import json
from typing import Any
from uuid import UUID

from leonaid.adapters.postgres.survey_analysis import read_snapshot
from leonaid.application.errors import ResourceNotFound
from leonaid.application.surveys.response_selection import (
    FreeTextItems,
    IndividualResponse,
    ResponseItem,
    ResponseItems,
    ResponseSelection,
)


def selection_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    return ResponseSelection.model_validate(
        {
            "id": snapshot["id"],
            "surveyId": snapshot["surveyId"],
            "createdAt": snapshot["createdAt"],
            "versionNumber": snapshot["versionNumber"],
            "filter": snapshot["filter"],
            "total": snapshot["participationCount"],
            "questions": [
                {"id": q["questionId"], "title": q["title"], "kind": q["kind"]}
                for q in snapshot["questions"]
            ],
        }
    ).model_dump()


async def read_responses(
    conn: Any,
    survey_id: UUID,
    snapshot_id: UUID,
    operation: str,
    body: dict[str, Any],
    *,
    can_test: bool,
) -> dict[str, Any]:
    snapshot = await read_snapshot(conn, survey_id, snapshot_id, can_test=can_test)
    if operation == "response-selection":
        return selection_metadata(snapshot)
    source = """FROM survey_analysis_snapshot s
      CROSS JOIN LATERAL jsonb_array_elements(s.private_responses)
        WITH ORDINALITY AS r(value,position)
      WHERE s.survey_id=$1 AND s.id=$2"""
    if operation == "response-individual":
        value = await conn.fetchval(
            "SELECT r.value " + source + " AND r.value->>'participationId'=$3",
            survey_id,
            snapshot_id,
            body["participationId"],
        )
        if value is None:
            raise ResourceNotFound("not_found", "Antwort nicht gefunden.")
        return IndividualResponse.model_validate_json(value).model_dump()
    offset = body["offset"]
    if operation == "response-free-text":
        question_id = body["questionId"]
        if not any(
            q["questionId"] == question_id and q["kind"] in {"text", "comment"}
            for q in snapshot["questions"]
        ):
            raise ResourceNotFound("not_found", "Freitextfrage nicht gefunden.")
        filtered = source + " AND jsonb_typeof(r.value->'answers'->$3)='string'"
        total = await conn.fetchval(
            "SELECT count(*) " + filtered, survey_id, snapshot_id, question_id
        )
        rows = await conn.fetch(
            "SELECT r.value->>'participationId' AS id, r.value->>'status' AS status, r.value->'answers'->>$3 AS text "
            + filtered
            + " ORDER BY r.position OFFSET $4 LIMIT 50",
            survey_id,
            snapshot_id,
            question_id,
            offset,
        )
        return FreeTextItems.model_validate(
            {
                "snapshotId": str(snapshot_id),
                "questionId": question_id,
                "total": total,
                "offset": offset,
                "items": [
                    {
                        "participationId": row["id"],
                        "status": row["status"],
                        "text": row["text"],
                    }
                    for row in rows
                ],
            }
        ).model_dump()
    rows = await conn.fetch(
        "SELECT r.value - 'answers' AS summary "
        + source
        + " ORDER BY r.position OFFSET $3 LIMIT 50",
        survey_id,
        snapshot_id,
        offset,
    )
    return ResponseItems(
        snapshotId=str(snapshot_id),
        total=snapshot["participationCount"],
        offset=offset,
        items=[ResponseItem.model_validate(json.loads(row["summary"])) for row in rows],
    ).model_dump()
