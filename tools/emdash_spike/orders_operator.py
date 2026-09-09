"""Scoped synthetic Twenty provisioning; never emit response bodies or credentials."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tools.seed.golden import TwentyClient, load_fixture, seed_twenty
from tools.twenty.provision import Provisioner, load_manifest, verify_integration_key


def main() -> None:
    assert os.environ["LEONAID_ENV"] == "test"
    assert os.environ["TWENTY_BASE_URL"] == "http://twenty-server:3000"
    phase = "schema"
    try:
        provisioner = Provisioner(load_manifest(Path("infra/twenty/schema.json")))
        try:
            provisioner.apply(Path("/proof/integration.env"))
        finally:
            provisioner.close()
        phase = "restricted-key"
        verify_integration_key(
            Path("/proof/integration.env"), "http://twenty-server:3000"
        )
        phase = "synthetic-crm-seed"
        dataset, _, _ = load_fixture(Path("tests/fixtures/golden/v1"))
        client = TwentyClient()
        try:
            seed_twenty(client, dataset)
        finally:
            client.close()
    except Exception as error:
        print(
            f"campaign-orders: operator failed; phase={phase}; type={type(error).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(
        "campaign-orders: actual Twenty schema, restricted key permissions and Golden CRM seed verified"
    )


if __name__ == "__main__":
    main()
