from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from leonaid.application.campaign_renderer import CampaignRendererCommand
from leonaid.domain.errors import DomainInvariantError

A = UUID("20000000-0000-4000-8000-000000000001")
B = UUID("20000000-0000-4000-8000-000000000003")


def command() -> CampaignRendererCommand:
    return CampaignRendererCommand(A, B, A, 1, "campaign")


@pytest.mark.parametrize("revision", [0, -1, True, "1", 1.5, None])
def test_renderer_rejects_invalid_revision(revision: Any) -> None:
    with pytest.raises(DomainInvariantError):
        replace(command(), revision=revision)


@pytest.mark.parametrize("renderer", ["", "cms", "CAMPAIGN", "https://other", None, []])
def test_renderer_rejects_unknown_target(renderer: Any) -> None:
    with pytest.raises(DomainInvariantError):
        replace(command(), renderer=renderer)


def test_renderer_fingerprint_binds_authority_and_selection_not_retry_key() -> None:
    original = command()
    assert len(original.fingerprint(A)) == 64
    assert replace(original, command_id=B).fingerprint(A) == original.fingerprint(A)
    assert original.fingerprint(B) != original.fingerprint(A)
    for variant in (
        replace(original, alias_id=A),
        replace(original, action_id=B),
        replace(original, revision=2),
        replace(original, renderer="legacy"),
    ):
        assert variant.fingerprint(A) != original.fingerprint(A)
