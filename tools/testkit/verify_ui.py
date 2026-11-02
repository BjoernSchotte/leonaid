#!/usr/bin/env python3
"""Cross-check the browser proof with API, Twenty and Golden Data."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from leonaid_testkit import TestContext, TestkitFailure


def load_json(path: Path, context: TestContext, step: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise context.failure(
            step, f"Proof {path} is not readable: {error}."
        ) from error
    if not isinstance(value, dict):
        raise context.failure(step, f"Proof {path} is not a JSON object.")
    return value


def main() -> None:
    proof_directory = Path(os.environ["TESTKIT_PROOF_DIR"])
    bootstrap_context = TestContext(
        request_id="poc013-proof-bootstrap",
        persona="Akquisiteurin Anna Akquise",
        charity_action="20000000-0000-4000-8000-000000000001",
        golden_dataset="1.0.0",
    )
    try:
        api = load_json(
            proof_directory / "api-proof.json",
            bootstrap_context,
            "api-proof-load",
        )
        context = TestContext(
            request_id=str(api.get("requestId")),
            persona=str(api.get("persona")),
            charity_action=str(api.get("charityAction")),
            golden_dataset=str(api.get("goldenDataset")),
        )
        ui = load_json(
            proof_directory / "ui-proof.json",
            context,
            "ui-proof-load",
        )
        sponsor = api.get("sponsor")
        if not isinstance(sponsor, dict):
            raise context.failure(
                "proof-compare", "API proof has no sponsor."
            )
        expected_id = sponsor.get("expectedTwentyId")
        ids = {
            "UI": ui.get("partyId"),
            "LeonAid API": sponsor.get("apiTwentyId"),
            "Twenty": sponsor.get("twentyRecordId"),
            "Read-only SQL": sponsor.get("sqlTwentyId"),
        }
        mismatches = {
            source: value for source, value in ids.items() if value != expected_id
        }
        if mismatches:
            raise context.failure(
                "proof-compare",
                f"Sponsor IDs differ from {expected_id}: {mismatches}.",
            )
        if ui.get("displayName") != sponsor.get("expectedName"):
            raise context.failure(
                "proof-compare",
                "UI and golden dataset do not show the same sponsor name.",
            )
    except TestkitFailure as error:
        print(f"testkit-ui-proof: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(
        "testkit-ui-proof: OK: UI, LeonAid API, Twenty and read-only SQL "
        "reference the same golden sponsor"
    )


if __name__ == "__main__":
    main()
