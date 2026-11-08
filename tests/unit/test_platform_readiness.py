"""Twenty is a readiness dependency only with an integration key (E-031)."""

from __future__ import annotations

from leonaid.entrypoints.fastapi.platform import crm_probes
from tests.unit.test_configuration import valid_settings


def test_unconfigured_crm_is_no_readiness_dependency() -> None:
    assert crm_probes(valid_settings()) == ()
    assert crm_probes(valid_settings(TWENTY_INTEGRATION_API_KEY="  ")) == ()


def test_configured_crm_requires_a_healthy_twenty() -> None:
    probes = crm_probes(valid_settings(TWENTY_INTEGRATION_API_KEY="k" * 40))
    assert [probe.name for probe in probes] == ["twenty"]
