from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from leonaid.application.campaign_aliases import CampaignAliasCommand
from leonaid.domain.errors import DomainInvariantError

A = UUID("20000000-0000-4000-8000-000000000001")
B = UUID("20000000-0000-4000-8000-000000000003")


def create() -> CampaignAliasCommand:
    return CampaignAliasCommand(A, B, A, A, "create", 0, "krapfentaxi-zusatz")


def test_alias_command_fingerprint_binds_actor_scope_and_payload() -> None:
    command = create()
    assert command.fingerprint(A) == create().fingerprint(A)
    variants = [
        replace(command, alias_id=A),
        replace(command, alias="weitere-adresse"),
        replace(command, enabled=False),
        replace(command, action_id=B, target_action_id=B),
        replace(command, operation="update", revision=1),
    ]
    assert all(item.fingerprint(A) != command.fingerprint(A) for item in variants)
    assert command.fingerprint(B) != command.fingerprint(A)
    # A new retry key is not a different payload; the receipt key is separate.
    assert replace(command, command_id=B).fingerprint(A) == command.fingerprint(A)


@pytest.mark.parametrize(
    "alias",
    ["campaigns", "a/b", "https://example.org", "a%2fb", "a?b", "a#b", "a" * 161],
)
def test_alias_commands_reject_unsafe_addresses(alias: str) -> None:
    with pytest.raises(DomainInvariantError):
        replace(create(), alias=alias)


def test_alias_command_operation_contracts() -> None:
    with pytest.raises(DomainInvariantError):
        replace(create(), revision=1)
    with pytest.raises(DomainInvariantError):
        replace(create(), operation="update")
    with pytest.raises(DomainInvariantError):
        replace(create(), target_action_id=B)
    with pytest.raises(DomainInvariantError):
        replace(create(), operation="remove", revision=1)
    remove = replace(create(), operation="remove", revision=1, alias=None)
    assert remove.operation == "remove"
    with pytest.raises(DomainInvariantError):
        replace(remove, target_action_id=B)
