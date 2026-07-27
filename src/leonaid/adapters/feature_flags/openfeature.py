"""Official OpenFeature Python SDK adapter backed by an atomic snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from threading import RLock

from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.flag_evaluation import (
    FlagResolutionDetails,
    FlagValueType,
    Reason,
)
from openfeature.exception import ErrorCode
from openfeature.provider import AbstractProvider, Metadata

from leonaid.domain.feature_flags import (
    FeatureEvaluationContext,
    FeatureFlagDefinition,
    FeatureFlagEvaluation,
    FeatureFlagKey,
)

OPENFEATURE_DOMAIN = "leonaid"
PROVIDER_NAME = "leonaid-postgres-snapshot"


class LeonAidFeatureProvider(AbstractProvider):
    def __init__(self) -> None:
        super().__init__()
        self._lock = RLock()
        self._values: Mapping[str, bool] = {}

    def get_metadata(self) -> Metadata:
        return Metadata(PROVIDER_NAME)

    def replace_snapshot(self, values: Mapping[FeatureFlagKey, bool]) -> None:
        with self._lock:
            self._values = {key.value: enabled for key, enabled in values.items()}

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[bool]:
        del evaluation_context
        with self._lock:
            if flag_key not in self._values:
                return FlagResolutionDetails(
                    value=default_value,
                    error_code=ErrorCode.FLAG_NOT_FOUND,
                    error_message="Feature-Flag ist nicht registriert.",
                    reason=Reason.DEFAULT,
                    variant="default",
                )
            enabled = self._values[flag_key]
        return FlagResolutionDetails(
            value=enabled,
            reason=Reason.STATIC,
            variant="enabled" if enabled else "disabled",
        )

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[str]:
        return self._type_mismatch(flag_key, default_value, evaluation_context)

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[int]:
        return self._type_mismatch(flag_key, default_value, evaluation_context)

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[float]:
        return self._type_mismatch(flag_key, default_value, evaluation_context)

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Sequence[FlagValueType] | Mapping[str, FlagValueType],
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[Sequence[FlagValueType] | Mapping[str, FlagValueType]]:
        return self._type_mismatch(flag_key, default_value, evaluation_context)

    @staticmethod
    def _type_mismatch[ValueT](
        flag_key: str,
        default_value: ValueT,
        evaluation_context: EvaluationContext | None,
    ) -> FlagResolutionDetails[ValueT]:
        del flag_key, evaluation_context
        return FlagResolutionDetails(
            value=default_value,
            error_code=ErrorCode.TYPE_MISMATCH,
            error_message="LeonAid registriert im PoC ausschließlich Boolean-Flags.",
            reason=Reason.ERROR,
            variant="default",
        )


class OpenFeatureBooleanEvaluator:
    def __init__(self, provider: LeonAidFeatureProvider) -> None:
        self._provider = provider
        api.set_provider_and_wait(provider, domain=OPENFEATURE_DOMAIN)
        self._client = api.get_client(OPENFEATURE_DOMAIN, "0.0.0")

    @property
    def provider_name(self) -> str:
        return self._provider.get_metadata().name

    def replace_snapshot(self, values: Mapping[FeatureFlagKey, bool]) -> None:
        self._provider.replace_snapshot(values)

    def evaluate_boolean(
        self,
        definition: FeatureFlagDefinition,
        context: FeatureEvaluationContext,
    ) -> FeatureFlagEvaluation:
        details = self._client.get_boolean_details(
            definition.key.value,
            definition.default_enabled,
            EvaluationContext(
                targeting_key=context.targeting_key,
                attributes={
                    "roles": list(context.roles),
                    "surface": context.surface.value,
                },
            ),
        )
        return FeatureFlagEvaluation(
            key=definition.key,
            enabled=details.value,
            variant=details.variant or "default",
            reason=str(details.reason or Reason.UNKNOWN.value),
            provider=self.provider_name,
        )
