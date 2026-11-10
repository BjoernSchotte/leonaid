from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from leonaid.adapters.feature_flags.openfeature import (
    LeonAidFeatureProvider,
    OpenFeatureBooleanEvaluator,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.feature_flags import (
    FEATURE_FLAG_DEFINITIONS,
    FeatureEvaluationContext,
    FeatureFlagKey,
    FeatureFlagState,
    FeatureFlagSurface,
    feature_flag_definition,
)
from leonaid.domain.identity import (
    AccountStatus,
    ActionMembership,
    ActionRole,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ADMIN_ID = UUID("10000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 27, 9, tzinfo=timezone.utc)


def system_admin() -> IdentityPrincipal:
    return IdentityPrincipal(
        account=UserAccount(
            id=ADMIN_ID,
            email="system-admin@leonaid.invalid",
            display_name="Simone System",
            status=AccountStatus.ACTIVE,
        ),
        global_roles=frozenset({GlobalRole.SYSTEM_ADMIN}),
        action_memberships=(
            ActionMembership(
                id=UUID("21000000-0000-4000-8000-000000000001"),
                action_id=ACTION_ID,
                action_name="Krapfentaxi 2026",
                user_id=ADMIN_ID,
                role=ActionRole.CHARITY_ADMIN,
                active_from=NOW,
            ),
        ),
    )


def test_catalog_rejects_unknown_keys() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        feature_flag_definition("admin.freely_invented")

    assert captured.value.code == "feature_flag_unknown"


def test_evaluation_context_contains_no_personal_data() -> None:
    context = FeatureEvaluationContext.for_principal(
        system_admin(),
        FeatureFlagSurface.WEB,
    )

    serialized = repr(context)
    assert context.targeting_key == str(ADMIN_ID)
    assert context.roles == ("charity_admin", "system_admin")
    assert "Simone" not in serialized
    assert "@leonaid.invalid" not in serialized


def test_official_openfeature_sdk_resolves_real_snapshot() -> None:
    provider = LeonAidFeatureProvider()
    evaluator = OpenFeatureBooleanEvaluator(provider)
    evaluator.replace_snapshot(
        {
            FeatureFlagKey.SYSTEM_STATUS_PANEL: True,
            FeatureFlagKey.PREVIEW_NOTICE: False,
        }
    )
    context = FeatureEvaluationContext.for_principal(
        system_admin(),
        FeatureFlagSurface.WEB,
    )

    system_status = evaluator.evaluate_boolean(
        FEATURE_FLAG_DEFINITIONS[FeatureFlagKey.SYSTEM_STATUS_PANEL],
        context,
    )
    preview = evaluator.evaluate_boolean(
        FEATURE_FLAG_DEFINITIONS[FeatureFlagKey.PREVIEW_NOTICE],
        context,
    )

    assert system_status.enabled is True
    assert system_status.variant == "enabled"
    assert system_status.reason == "STATIC"
    assert system_status.provider == "leonaid-postgres-snapshot"
    assert preview.enabled is False
    assert preview.variant == "disabled"


def test_feature_flag_state_requires_monotonic_revision_and_aware_time() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        FeatureFlagState(
            id=UUID("95000000-0000-4000-8000-000000000001"),
            key=FeatureFlagKey.SYSTEM_STATUS_PANEL,
            enabled=False,
            revision=0,
            updated_by_user_id=None,
            updated_at=NOW,
        )

    assert captured.value.code == "feature_flag_revision_invalid"


def test_offline_queue_flag_ships_off_and_matches_transport_and_schema() -> None:
    """specs/pwa-offline-queue §16: the PWA reads the flag; it starts off."""
    from pathlib import Path
    from typing import get_args

    from leonaid.entrypoints.fastapi.schemas import FeatureFlagKeyValue

    definition = FEATURE_FLAG_DEFINITIONS[FeatureFlagKey.PWA_OFFLINE_QUEUE]
    assert definition.key.value == "pwa.offline_queue"
    assert definition.default_enabled is False
    assert definition.client_safe is True
    assert set(get_args(FeatureFlagKeyValue)) == {key.value for key in FeatureFlagKey}
    migration = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/0057_pwa_offline_queue_flag.py"
    ).read_text(encoding="utf-8")
    # The keys that existed with 0057; later flags widen the check again.
    for key in (
        FeatureFlagKey.SYSTEM_STATUS_PANEL,
        FeatureFlagKey.PREVIEW_NOTICE,
        FeatureFlagKey.PWA_OFFLINE_QUEUE,
    ):
        assert f"'{key.value}'" in migration


def test_delivery_tours_flag_ships_off_and_matches_transport_and_schema() -> None:
    """specs/krapfentaxi-touren: tours start off; migration 0058 registers them."""
    from pathlib import Path
    from typing import get_args

    from leonaid.entrypoints.fastapi.schemas import FeatureFlagKeyValue

    definition = FEATURE_FLAG_DEFINITIONS[FeatureFlagKey.DELIVERY_TOURS]
    assert definition.key.value == "delivery.tours"
    assert definition.default_enabled is False
    assert definition.client_safe is True
    assert "delivery.tours" in get_args(FeatureFlagKeyValue)
    import importlib.util
    import inspect

    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/0058_delivery_tours.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0058", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "'delivery.tours'" in module.NEW_KEYS
    assert "'delivery.tours'" not in module.OLD_KEYS
    assert "'delivery.tours', false, 1" in inspect.getsource(module.upgrade)


def test_push_flag_ships_off_and_matches_transport_and_schema() -> None:
    """specs/mails-documents-donations-push §10: push starts off (0065).

    0065 is the newest flag migration, so its key check must know every
    key of the catalog; a later flag moves that assertion to its migration.
    """
    from pathlib import Path
    from typing import get_args

    from leonaid.entrypoints.fastapi.schemas import FeatureFlagKeyValue

    definition = FEATURE_FLAG_DEFINITIONS[FeatureFlagKey.PWA_PUSH]
    assert definition.key.value == "pwa.push"
    assert definition.default_enabled is False
    assert definition.client_safe is True
    assert "pwa.push" in get_args(FeatureFlagKeyValue)
    import importlib.util
    import inspect

    path = Path(__file__).resolve().parents[2] / "migrations/versions/0065_pwa_push.py"
    spec = importlib.util.spec_from_file_location("migration_0065", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for key in FeatureFlagKey:
        assert f"'{key.value}'" in module.NEW_KEYS
    assert "'pwa.push'" not in module.OLD_KEYS
    assert "'pwa.push', false, 1" in inspect.getsource(module.upgrade)
    # The kinds of the schema are the kinds of the domain.
    from leonaid.domain.push import PushKind

    for kind in PushKind:
        assert f"'{kind.value}'" in module.KINDS
