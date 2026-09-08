"""Prove survey validation and aggregation from the upgraded API's network."""

import asyncio

from leonaid.adapters.surveyjs_validation import aggregate_batch, validate_answers
from leonaid.domain.errors import DomainInvariantError


async def main() -> None:
    definition = {
        "title": "Upgrade survey probe",
        "pages": [
            {
                "name": "feedback",
                "elements": [
                    {
                        "type": "rating",
                        "name": "score",
                        "title": "Rating",
                        "rateMin": 1,
                        "rateMax": 5,
                        "isRequired": True,
                    }
                ],
            }
        ],
    }
    assert await validate_answers(definition, {}, complete=False) == {}
    assert await validate_answers(definition, {"score": 3}, complete=True) == {
        "score": 3
    }
    for answers in ({}, {"score": 6}):
        try:
            await validate_answers(definition, answers, complete=True)
        except DomainInvariantError as error:
            assert error.code == "invalid_response"
        else:
            raise AssertionError("Invalid completed response was accepted")
    questions = await aggregate_batch(definition, [{"score": 1}, {"score": 5}, {}])
    assert len(questions) == 1
    result = questions[0]
    assert (result.questionId, result.relevant, result.answered, result.unanswered) == (
        "score",
        3,
        2,
        1,
    )
    assert (result.sum, result.mean, result.minimum, result.maximum) == (6, 3, 1, 5)
    print("upgrade-surveys: real validation and aggregate adapters passed")


if __name__ == "__main__":
    asyncio.run(main())
