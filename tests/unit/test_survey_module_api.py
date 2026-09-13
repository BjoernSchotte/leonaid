"""Direct module calls validate inputs before acquiring a real database pool."""

from uuid import uuid4

import asyncpg
import pytest
from pydantic import ValidationError

from leonaid.adapters.postgres.surveys import AsyncpgSurveyRepository
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.application.errors import PermissionDenied
from leonaid.modules.surveys.api import (
    Create,
    DraftSave,
    SurveySchedule,
    SurveyService,
    TimeoutSettings,
    CreateAnalysisSnapshot,
    ResponsePage,
    Start,
    AnswerSave,
)


@pytest.mark.asyncio
async def test_direct_mutations_revalidate_changed_input_models() -> None:
    # A real uninitialized pool deliberately cannot perform I/O. Invalid values
    # must fail at the same model boundary used by HTTP, before repository work.
    pool = asyncpg.create_pool(min_size=0, max_size=1)
    service = SurveyService(AsyncpgSurveyRepository(pool))
    actor = IdentityPrincipal(
        UserAccount(uuid4(), "direct@example.test", "Direct", AccountStatus.ACTIVE),
        frozenset(),
        (),
    )
    survey_id = uuid4()
    create = Create(operationId="create", title="Valid", definition={})
    create.title = " "
    with pytest.raises(ValidationError, match="title"):
        await service.create_survey(actor, survey_id, create)

    draft = DraftSave(operationId="save", expectedRevision=1, definition={})
    draft.definition["oversized"] = "x" * 262145
    with pytest.raises(ValidationError, match="Definition too large"):
        await service.save_draft(actor, survey_id, draft)

    schedule = SurveySchedule(operationId="schedule", expectedRevision=1, endsAt=None)
    schedule.endsAt = "2026-09-13T12:00:00"
    with pytest.raises(ValidationError, match="explicit time zone"):
        await service.schedule_end(actor, survey_id, schedule)

    analysis = CreateAnalysisSnapshot.model_validate(
        {"operationId": "analysis", "filter": {"versionId": str(uuid4())}}
    )
    analysis.filter.statuses.append("completed")
    with pytest.raises(ValidationError, match="Duplicate response status"):
        await service.create_analysis(actor, survey_id, analysis)

    page = ResponsePage(snapshotId=uuid4())
    page.offset = 5001
    with pytest.raises(ValidationError, match="offset"):
        await service.list_responses(actor, survey_id, page)

    start = Start(operationId="start", resumeSecret="a" * 32)
    start.resumeSecret = "short"
    with pytest.raises(ValidationError, match="resumeSecret"):
        await service.start_participation(survey_id, start)

    answers = AnswerSave(operationId="answers", expectedRevision=1, answers={})
    answers.answers["oversized"] = "x" * 262145
    with pytest.raises(ValidationError, match="Answers too large"):
        await service.save_response(survey_id, uuid4(), answers, "a" * 32)

    # The existing repository authorization applies to direct calls as well.
    with pytest.raises(PermissionDenied):
        await service.get_settings(actor)
    with pytest.raises(PermissionDenied):
        await service.update_settings(
            actor,
            TimeoutSettings(
                operationId="settings", expectedRevision=1, inactivityTimeoutSeconds=60
            ),
        )


def test_settings_revalidation_preserves_omitted_versus_explicit_null() -> None:
    settings = TimeoutSettings(
        operationId="settings", expectedRevision=1, inactivityTimeoutSeconds=60
    )
    assert "endedRetentionSeconds" not in TimeoutSettings.model_validate(
        settings
    ).model_dump(exclude_unset=True)
    settings.endedRetentionSeconds = None
    assert (
        TimeoutSettings.model_validate(settings).model_dump(exclude_unset=True)[
            "endedRetentionSeconds"
        ]
        is None
    )
