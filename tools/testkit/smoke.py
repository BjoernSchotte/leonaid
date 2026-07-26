#!/usr/bin/env python3
"""Prove the shared testkit against all real PoC dependencies."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from leonaid_testkit import (
    LeonAidApiClient,
    MailpitClient,
    ReadOnlySqlClient,
    RustFsClient,
    TestContext,
    TestkitFailure,
    TwentyClient,
)

DATASET_VERSION = "1.0.0"
ANNA_EMAIL = "anna.akquise@leonaid.invalid"
ANNA_PERSONA = "Akquisiteurin Anna Akquise"
ANNA_USER_ID = "10000000-0000-4000-8000-000000000004"
ACTION_ID = "20000000-0000-4000-8000-000000000001"
SPONSOR_ID = "40000000-0000-4000-8000-000000000001"
SPONSOR_NAME = "Musterwerk GmbH"


def require_env(name: str, context: TestContext) -> str:
    value = os.environ.get(name)
    if not value:
        raise context.failure("configuration", f"Umgebungsvariable {name} fehlt.")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def run() -> None:
    context = TestContext(
        request_id=f"poc013-{uuid4()}",
        persona=ANNA_PERSONA,
        charity_action=ACTION_ID,
        golden_dataset=DATASET_VERSION,
    )
    diagnostic = str(context.failure("diagnostic-contract", "Absichtliche Probe."))
    for expected_part in (
        context.request_id,
        context.persona,
        context.charity_action,
        context.golden_dataset,
        "diagnostic-contract",
    ):
        if expected_part not in diagnostic:
            raise context.failure(
                "diagnostic-contract",
                f"Fehlerdiagnose enthält {expected_part!r} nicht.",
            )
    dataset_path = Path(
        os.environ.get(
            "GOLDEN_DATASET_PATH",
            "/repo/tests/fixtures/golden/v1/dataset.json",
        )
    )
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if (
        not isinstance(dataset, dict)
        or dataset.get("datasetVersion") != DATASET_VERSION
    ):
        raise context.failure(
            "golden-dataset-load",
            f"Golden Dataset {dataset_path} besitzt nicht Version {DATASET_VERSION}.",
        )

    output_directory = Path(require_env("TESTKIT_PROOF_DIR", context))
    output_directory.mkdir(parents=True, exist_ok=True)
    mailpit = MailpitClient(
        api_url=require_env("MAILPIT_API_URL", context),
        smtp_host=require_env("MAILPIT_SMTP_HOST", context),
        smtp_port=int(require_env("MAILPIT_SMTP_PORT", context)),
        context=context,
    )
    api = LeonAidApiClient(
        base_url=require_env("LEONAID_API_BASE_URL", context),
        context=context,
    )
    twenty = TwentyClient(
        base_url=require_env("TWENTY_BASE_URL", context),
        api_key=require_env("TWENTY_INTEGRATION_API_KEY", context),
        context=context,
    )
    try:
        await api.wait_ready()
        session = await api.login(
            email=ANNA_EMAIL,
            persona=ANNA_PERSONA,
            expected_user_id=ANNA_USER_ID,
            expected_display_name="Anna Akquise",
            mailpit=mailpit,
        )
        parties = await api.get_json(
            f"/api/v1/actions/{ACTION_ID}/acquisition/parties",
            session=session,
            step="leonaid-sponsor-read",
            params={"q": SPONSOR_NAME, "limit": 20},
        )
        items = parties.get("items")
        if not isinstance(items, list):
            raise context.failure(
                "leonaid-sponsor-read",
                "LeonAid API liefert keine Sponsor-Liste.",
            )
        matches = [
            item
            for item in items
            if isinstance(item, dict) and item.get("displayName") == SPONSOR_NAME
        ]
        if len(matches) != 1:
            raise context.failure(
                "leonaid-sponsor-read",
                f"Golden-Sponsor wurde {len(matches)}-mal statt genau einmal gefunden.",
            )
        api_sponsor = matches[0]
        api_twenty_id = api_sponsor.get("twentyId")
        if api_twenty_id != SPONSOR_ID:
            raise context.failure(
                "leonaid-sponsor-read",
                f"LeonAid API referenziert Twenty-ID {api_twenty_id!r}.",
            )

        twenty_sponsor = await twenty.get_company(SPONSOR_ID)
        if (
            twenty_sponsor.get("id") != SPONSOR_ID
            or twenty_sponsor.get("name") != SPONSOR_NAME
        ):
            raise context.failure(
                "twenty-company-read",
                "Twenty Golden-Firma stimmt nicht mit API und Fixture überein.",
            )

        async with ReadOnlySqlClient(
            database_url=require_env("CORE_DATABASE_URL", context),
            context=context,
        ) as sql:
            snapshot = await sql.fetchrow(
                """
                SELECT dataset_version, dataset_sha256
                FROM golden_seed_snapshot
                WHERE dataset_version = $1
                """,
                DATASET_VERSION,
            )
            assignment = await sql.fetchrow(
                """
                SELECT twenty_company_id::text AS twenty_id
                FROM acquisition_assignment
                WHERE action_id = $1::uuid
                  AND acquirer_user_id = $2::uuid
                  AND twenty_company_id = $3::uuid
                """,
                ACTION_ID,
                "10000000-0000-4000-8000-000000000004",
                SPONSOR_ID,
            )
        if assignment.get("twenty_id") != SPONSOR_ID:
            raise context.failure(
                "sql-sponsor-read",
                "Read-only SQL findet nicht dieselbe Twenty-ID.",
            )

        mail_subject = f"POC-013 Testkit {context.request_id}"
        delivered = await mailpit.send_and_wait(
            sender="testkit@leonaid.invalid",
            recipient="poc013-smoke@leonaid.invalid",
            subject=mail_subject,
            text=(
                "Realer SMTP/Mailpit-Smoke-Test für "
                f"{context.golden_dataset} und {context.charity_action}."
            ),
        )
        if delivered.subject != mail_subject:
            raise context.failure(
                "mailpit-delivery",
                "Mailpit lieferte nicht den versendeten Betreff zurück.",
            )

        rustfs = RustFsClient(
            endpoint_url=require_env("RUSTFS_ENDPOINT_URL", context),
            access_key=require_env("RUSTFS_ACCESS_KEY", context),
            secret_key=require_env("RUSTFS_SECRET_KEY", context),
            bucket=require_env("RUSTFS_BUCKET", context),
            context=context,
        )
        object_content = (
            f"LeonAid POC-013\n{context.request_id}\n{SPONSOR_ID}\n".encode()
        )
        object_key = f"testkit/poc013/{context.request_id}.txt"
        object_sha256 = await rustfs.round_trip(
            key=object_key,
            content=object_content,
        )

        write_json(
            output_directory / "api-proof.json",
            {
                "charityAction": ACTION_ID,
                "datasetSha256": str(snapshot["dataset_sha256"]).strip(),
                "goldenDataset": DATASET_VERSION,
                "mailpit": {
                    "messageId": delivered.message_id,
                    "recipient": "poc013-smoke@leonaid.invalid",
                    "subject": delivered.subject,
                },
                "persona": ANNA_PERSONA,
                "requestId": context.request_id,
                "rustfs": {
                    "key": object_key,
                    "sha256": object_sha256,
                    "temporaryObjectDeleted": True,
                },
                "sponsor": {
                    "apiName": api_sponsor["displayName"],
                    "apiTwentyId": api_twenty_id,
                    "expectedName": SPONSOR_NAME,
                    "expectedTwentyId": SPONSOR_ID,
                    "sqlTwentyId": assignment["twenty_id"],
                    "twentyName": twenty_sponsor["name"],
                    "twentyRecordId": twenty_sponsor["id"],
                },
            },
        )
        session_path = output_directory / "persona-session.env"
        session_path.write_text(
            f"ANNA_EMAIL={ANNA_EMAIL}\nANNA_SESSION={session.token}\n",
            encoding="utf-8",
        )
        session_path.chmod(0o600)
    finally:
        await twenty.close()
        await api.close()
        await mailpit.close()

    print(
        "testkit-smoke: OK: echter Login, API/Twenty/SQL-Sponsor, "
        "SMTP/Mailpit und RustFS-Hash"
    )


def main() -> None:
    try:
        asyncio.run(run())
    except TestkitFailure as error:
        print(f"testkit-smoke: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except Exception as error:  # noqa: BLE001 - preserve required context
        fallback = TestContext(
            request_id="poc013-unhandled",
            persona=ANNA_PERSONA,
            charity_action=ACTION_ID,
            golden_dataset=DATASET_VERSION,
        )
        print(
            f"testkit-smoke: ERROR: "
            f"{fallback.failure('unhandled', f'Unerwarteter Fehler: {error}.')}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
