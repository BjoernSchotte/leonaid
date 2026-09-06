"""Private shared-Core answer validation; the host retains all write authority."""

from typing import Any

import httpx

from leonaid.application.errors import DependencyUnavailable
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
