"""Real private SurveyJS aggregate adapter with independent golden assertions."""

import asyncio
import json
import math
import sys
from pathlib import Path

from leonaid.adapters.surveyjs_validation import aggregate_batch
from leonaid.application.errors import DependencyUnavailable
from leonaid.domain.errors import DomainInvariantError


async def main() -> None:
    fixture = json.loads(
        Path("tests/fixtures/surveys/analysis-golden.json").read_text()
    )
    definition, responses = fixture["definition"], fixture["responses"]
    if sys.argv[1] == "unavailable":
        try:
            await aggregate_batch(definition, responses)
        except DependencyUnavailable as error:
            assert error.code == "survey_analysis_unavailable"
        else:
            raise AssertionError(
                "Unavailable engine returned a false successful analysis"
            )
        print("PASS: stopped aggregate engine fails explicitly without a result")
        return
    result = await aggregate_batch(definition, responses)
    q = {item.questionId: item for item in result}
    assert len(q) == 9
    assert [(item.count, item.percentage) for item in q["multi"].counts] == [
        (2, 100),
        (1, 50),
    ]
    assert math.isclose(q["nps"].nps, 100 / 3)
    assert math.isclose(q["nps"].mean, 19 / 3)
    assert (
        q["number"].sum,
        q["number"].mean,
        q["number"].minimum,
        q["number"].maximum,
    ) == (30, 15, 10, 20)
    assert (q["follow"].relevant, q["follow"].hidden, q["follow"].unanswered) == (
        3,
        2,
        2,
    )
    assert (q["conditional"].relevant, q["conditional"].hidden) == (2, 3)
    assert (q["text"].answered, q["text"].invalid) == (2, 1)
    assert (q["date"].answered, q["date"].invalid) == (1, 1)
    assert [
        (row.answered, row.unanswered, row.invalid) for row in q["matrix"].matrixRows
    ] == [(2, 2, 1), (1, 3, 1)]
    output = json.dumps([item.model_dump() for item in result])
    assert not any(marker in output for marker in ("SENSITIVE_", "alien", "not-a-date"))
    empty = await aggregate_batch(definition, [])
    assert all(
        item.answered == 0 and item.mean is None and item.nps is None for item in empty
    )
    maximum = await aggregate_batch(definition, [{} for _ in range(100)])
    assert all(item.relevant + item.hidden == 100 for item in maximum)
    for oversized in ([{} for _ in range(101)], [{"text": "x" * 550_000}]):
        try:
            await aggregate_batch(definition, oversized)
        except DomainInvariantError as error:
            assert error.code == "limit_exceeded"
        else:
            raise AssertionError("Aggregate batch limit not enforced")
    try:
        await aggregate_batch(definition, [{"unexpected": "SENSITIVE_UNKNOWN"}])
    except DomainInvariantError as error:
        assert error.code == "invalid_response"
    else:
        raise AssertionError("Unknown answer fields accepted")
    Path("/proof/surveys-aggregates.json").write_text(output)
    print(
        "PASS: real aggregate adapter matches golden counts, NPS, matrix and relevance denominators; raw text absent; empty and bounded batches verified"
    )


asyncio.run(main())
