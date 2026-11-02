from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.pilot_deployment.validate import (
    CORE_MEMORY_BUDGET_MIB,
    MONITORING_MEMORY_MIB,
    REQUIRED_SERVICES,
    DeploymentContractError,
    memory_mib,
    validate_memory_budget,
)

ROOT = Path(__file__).resolve().parents[2]
MONITORING_SERVICES = {"pilot-exporter", "prometheus", "alertmanager"}


class ComposeLoader(yaml.SafeLoader):
    """SafeLoader that reads Compose override tags such as !reset as plain data."""


def compose_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


ComposeLoader.add_multi_constructor("!", compose_tag)


def compose_services(relative: str) -> dict[str, Any]:
    document = yaml.load(
        (ROOT / relative).read_text(encoding="utf-8"), Loader=ComposeLoader
    )
    services: dict[str, Any] = document["services"]
    return services


def core_services() -> dict[str, Any]:
    services = compose_services("infra/compose/compose.yml")
    return {name: services[name] for name in REQUIRED_SERVICES}


def test_memory_units() -> None:
    assert memory_mib("1728m") == 1728
    assert memory_mib(1811939328) == 1728
    assert memory_mib("1811939328") == 1728
    assert memory_mib("1g") == 1024
    assert memory_mib("64M") == 64
    with pytest.raises(DeploymentContractError):
        memory_mib("lots")


def test_pilot_core_fits_the_budget() -> None:
    validate_memory_budget(core_services())


def test_monitoring_reserve_matches_the_pilot_overlay() -> None:
    services = compose_services("infra/pilot/compose.yml")
    total = sum(memory_mib(services[name]["mem_limit"]) for name in MONITORING_SERVICES)
    assert total == MONITORING_MEMORY_MIB


def test_budget_rejects_an_oversized_limit() -> None:
    services = core_services()
    services["twenty-postgres"] = {
        **services["twenty-postgres"],
        "mem_limit": f"{CORE_MEMORY_BUDGET_MIB}m",
    }
    with pytest.raises(DeploymentContractError, match="pilot budget"):
        validate_memory_budget(services)


def test_budget_rejects_a_heap_without_native_headroom() -> None:
    services = core_services()
    worker = services["twenty-worker"]
    services["twenty-worker"] = {
        **worker,
        "environment": {
            **worker["environment"],
            "NODE_OPTIONS": "--max-old-space-size=1300",
        },
    }
    with pytest.raises(DeploymentContractError, match="native memory"):
        validate_memory_budget(services)
