"""Private shared-Core answer validation; the host retains all write authority."""

from typing import Any

import httpx

from leonaid.application.errors import DependencyUnavailable
from leonaid.application.surveys.analysis import AggregateBatch, QuestionAggregate
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.surveys.validation import PROFILE, json_size, validate_definition


async def validate_answers(
    definition: dict[str, Any], answers: Any, *, complete: bool
) -> dict[str, Any]:
    validate_definition(definition)
    known = {q["name"] for page in definition["pages"] for q in page["elements"]}
    if (
        not isinstance(answers, dict)
        or json_size(answers) > 262144
        or set(answers) - known
    ):
        raise DomainInvariantError("invalid_response", "Ungültiger Antwortstand.")
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            response = await client.post(
                "http://survey-validator:8080/validate",
                json={"profile": PROFILE, "definition": definition, "answers": answers},
            )
            response.raise_for_status()
            result = response.json()
        if (
            result.get("profile") != PROFILE
            or result.get("renderer") != "3.0.3"
            or type(result.get("partialValid")) is not bool
            or type(result.get("completeValid")) is not bool
            or not isinstance(result.get("answers"), dict)
            or set(result["answers"]) - known
            or json_size(result["answers"]) > 262144
        ):
            raise ValueError("invalid adapter contract")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        raise DependencyUnavailable(
            "survey_validation_unavailable",
            "Die Antworten können gerade nicht geprüft werden. Bitte erneut versuchen.",
        ) from error
    if not result["completeValid" if complete else "partialValid"]:
        raise DomainInvariantError(
            "invalid_response", "Bitte prüfen Sie Ihre Antworten."
        )
    return dict(result["answers"])


async def aggregate_batch(
    definition: dict[str, Any], responses: list[dict[str, Any]]
) -> list[QuestionAggregate]:
    """One bounded server batch; selection/snapshot persistence belongs to the host.

    This is not a browser-side analysis API. The host must select a single stored
    version and enforce authorization before calling it. Stored invalid values
    are counted separately, not rejected as if they were new response writes.
    """
    validate_definition(definition)
    known = [q["name"] for page in definition["pages"] for q in page["elements"]]
    body = {"profile": PROFILE, "definition": definition, "responses": responses}
    if len(responses) > 100 or json_size(body) > 550_000:
        raise DomainInvariantError("limit_exceeded", "Auswertungsblock zu groß.")
    if any(not isinstance(row, dict) or set(row) - set(known) for row in responses):
        raise DomainInvariantError("invalid_response", "Unbekannte Antwortfelder.")
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.post(
                "http://survey-validator:8080/aggregate", json=body
            )
            response.raise_for_status()
            result = AggregateBatch.model_validate(response.json())
        if [q.questionId for q in result.questions] != known or any(
            q.relevant + q.hidden != len(responses) for q in result.questions
        ):
            raise ValueError("invalid aggregate contract")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        raise DependencyUnavailable(
            "survey_analysis_unavailable",
            "Die Auswertung ist gerade nicht verfügbar. Bitte erneut versuchen.",
        ) from error
    return result.questions
