"""A production deletion must fail safely when its recovery archive is unavailable."""

from pathlib import Path

import pytest

from leonaid.adapters.postgres.survey_checkpoint_publisher import (
    AsyncpgErasureCheckpointPublisher,
    configured_publisher,
)
from leonaid.application.errors import DependencyUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize("directory", [None, Path("relative/archive")])
async def test_missing_or_relative_archive_configuration_never_acknowledges(directory):
    secret = "SYNTHETIC_RECOVERY_SECRET_NOT_FOR_REAL_USE"
    publisher = AsyncpgErasureCheckpointPublisher(None, directory, secret)
    with pytest.raises(DependencyUnavailable) as failure:
        await publisher.publish()
    assert failure.value.code == "survey_erasure_archive_unavailable"
    assert secret not in str(failure.value)
    assert "relative/archive" not in str(failure.value)


@pytest.mark.asyncio
async def test_worker_factory_does_not_silently_disable_gate_when_unconfigured(monkeypatch):
    monkeypatch.delenv("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", raising=False)
    publisher = configured_publisher(None)
    with pytest.raises(DependencyUnavailable):
        await publisher.publish()
