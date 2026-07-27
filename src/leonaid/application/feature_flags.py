"""Feature-flag administration and OpenFeature-backed evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Protocol
from uuid import UUID

from leonaid.application.errors import ResourceNotFound
from leonaid.application.policies import require_system_admin
from leonaid.domain.feature_flags import (
    FEATURE_FLAG_CATALOG,
    FeatureEvaluationContext,
    FeatureFlagDefinition,
    FeatureFlagEvaluation,
    FeatureFlagKey,
    FeatureFlagState,
    FeatureFlagSurface,
    feature_flag_definition,
)
from leonaid.domain.identity import IdentityPrincipal


class FeatureFlagRepository(Protocol):
    async def list(self) -> tuple[FeatureFlagState, ...]: ...

    async def update(
        self,
        *,
        key: FeatureFlagKey,
        enabled: bool,
        expected_revision: int,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> FeatureFlagState: ...


class FeatureFlagEvaluator(Protocol):
    @property
    def provider_name(self) -> str: ...

    def replace_snapshot(self, values: Mapping[FeatureFlagKey, bool]) -> None: ...

    def evaluate_boolean(
        self,
        definition: FeatureFlagDefinition,
        context: FeatureEvaluationContext,
    ) -> FeatureFlagEvaluation: ...


class FeatureFlagService:
    def __init__(
        self,
        repository: FeatureFlagRepository,
        evaluator: FeatureFlagEvaluator,
    ) -> None:
        self._repository = repository
        self._evaluator = evaluator

    async def list_admin(
        self,
        actor: IdentityPrincipal,
    ) -> tuple[tuple[FeatureFlagDefinition, FeatureFlagState], ...]:
        require_system_admin(actor)
        states = {state.key: state for state in await self._repository.list()}
        return tuple(
            (definition, states[definition.key]) for definition in FEATURE_FLAG_CATALOG
        )

    async def evaluations(
        self,
        actor: IdentityPrincipal,
        surface: FeatureFlagSurface,
    ) -> tuple[FeatureFlagEvaluation, ...]:
        states = await self._refresh()
        context = FeatureEvaluationContext.for_principal(actor, surface)
        return tuple(
            self._evaluator.evaluate_boolean(definition, context)
            for definition in FEATURE_FLAG_CATALOG
            if definition.client_safe and definition.key in states
        )

    async def enabled(
        self,
        actor: IdentityPrincipal,
        key: FeatureFlagKey,
        *,
        surface: FeatureFlagSurface,
    ) -> bool:
        states = await self._refresh()
        definition = feature_flag_definition(key)
        if key not in states:
            return definition.default_enabled
        context = FeatureEvaluationContext.for_principal(actor, surface)
        return self._evaluator.evaluate_boolean(definition, context).enabled

    async def require_enabled(
        self,
        actor: IdentityPrincipal,
        key: FeatureFlagKey,
        *,
        surface: FeatureFlagSurface,
    ) -> None:
        if await self.enabled(actor, key, surface=surface):
            return
        raise ResourceNotFound(
            "feature_flag_disabled",
            "Diese Funktion ist in der aktuellen Installation nicht aktiviert.",
        )

    async def update(
        self,
        actor: IdentityPrincipal,
        *,
        key: str,
        enabled: bool,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime | None = None,
    ) -> tuple[FeatureFlagDefinition, FeatureFlagState]:
        require_system_admin(actor)
        definition = feature_flag_definition(key)
        state = await self._repository.update(
            key=definition.key,
            enabled=enabled,
            expected_revision=expected_revision,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
        await self._refresh()
        return definition, state

    async def _refresh(self) -> dict[FeatureFlagKey, FeatureFlagState]:
        states = {state.key: state for state in await self._repository.list()}
        values = {
            definition.key: states.get(
                definition.key,
                FeatureFlagState(
                    id=UUID(int=0),
                    key=definition.key,
                    enabled=definition.default_enabled,
                    revision=1,
                    updated_by_user_id=None,
                    updated_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
                ),
            ).enabled
            for definition in FEATURE_FLAG_CATALOG
        }
        self._evaluator.replace_snapshot(values)
        return states
