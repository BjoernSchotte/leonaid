"""Read frozen raw projections only after the caller authorizes read_responses."""

import json
from typing import Any
from uuid import UUID

from leonaid.modules.surveys.adapters.postgres.survey_analysis import read_snapshot
from leonaid.application.errors import ResourceNotFound
from leonaid.modules.surveys.application.response_selection import (
    FreeTextItems,
    IndividualResponse,
    ResponseItem,
    ResponseItems,
    ResponseSelection,
)


CHOICE_KINDS = {"radiogroup", "dropdown", "checkbox", "rating", "matrix"}


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def choice_labels(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Defined options per choice question, from the frozen version."""
    result: dict[str, dict[str, Any]] = {}
    for q in selection_metadata(snapshot)["questions"]:
        if q["kind"] not in CHOICE_KINDS:
            continue
        result[q["id"]] = {
            "matrix": q["kind"] == "matrix",
            "choices": {_key(c["value"]): c["label"] for c in q["choices"]},
            "rows": {r["value"]: r["label"] for r in q["rows"]},
        }
    return result


def choice_answers(
    answers: dict[str, Any], labels: dict[str, dict[str, Any]]
) -> dict[str, list[str]]:
    """Labels of the chosen options. Anything that is not a defined option
    (an "other" text, a comment, a stray value) is dropped, so no free text
    can pass."""
    result: dict[str, list[str]] = {}
    for question_id, spec in labels.items():
        value = answers.get(question_id)
        if value is None:
            continue
        chosen: list[str] = []
        if spec["matrix"]:
            if isinstance(value, dict):
                for row_id, row_label in spec["rows"].items():
                    label = spec["choices"].get(_key(value.get(row_id)))
                    if row_id in value and label is not None:
                        chosen.append(f"{row_label}: {label}")
        else:
            for item in value if isinstance(value, list) else [value]:
                label = spec["choices"].get(_key(item))
                if label is not None:
                    chosen.append(label)
        if chosen:
            result[question_id] = chosen
    return result


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
                {
                    "id": q["questionId"],
                    "title": q["title"],
                    "kind": q["kind"],
                    "choices": [
                        {"value": c["value"], "label": c["label"]}
                        for c in (
                            q["matrixRows"][0]["counts"]
                            if q["matrixRows"]
                            else q["counts"]
                        )
                    ],
                    "rows": [
                        {"value": r["rowId"], "label": r["label"]}
                        for r in q["matrixRows"]
                    ],
                }
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
    if operation == "response-aggregates":
        # The stored aggregates only (payload); disclose() applies k on the way out.
        return snapshot
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
    # Summaries: answers are removed in SQL. With a large limit one request
    # expands the frozen array once instead of once per 50 rows.
    choice = body.get("fields") == "choice"
    rows = await conn.fetch(
        "SELECT r.value - 'answers' AS summary"
        + (", r.value->'answers' AS answers " if choice else " ")
        + source
        + " ORDER BY r.position OFFSET $3 LIMIT $4",
        survey_id,
        snapshot_id,
        offset,
        body.get("limit", 50),
    )
    labels = choice_labels(snapshot) if choice else None
    items = []
    for row in rows:
        item = json.loads(row["summary"])
        if labels is not None:
            item["choiceAnswers"] = choice_answers(json.loads(row["answers"]), labels)
        items.append(ResponseItem.model_validate(item))
    return ResponseItems(
        snapshotId=str(snapshot_id),
        total=snapshot["participationCount"],
        offset=offset,
        items=items,
    ).model_dump()
