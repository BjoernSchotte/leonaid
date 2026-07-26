#!/usr/bin/env python3
"""Real PostgreSQL/Twenty/API contract for POC-032 sponsor matching."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
GOLDEN_COMPANY_ID = UUID("40000000-0000-4000-8000-000000000002")
PRIVATE_MAX_ID = UUID("50000000-0000-4000-8000-000000000006")
SESSION_NAMESPACE = UUID("34ff87e2-3cb5-45e8-8122-fbc1022297c4")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc032-{user_id}-server-session-token-value"


def command_id(label: str) -> str:
    return str(uuid5(SESSION_NAMESPACE, f"sponsor-command:{label}"))


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (ANNA_ID, KLARA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    tokens: dict[UUID, str] = {}
    for user_id in users:
        token = token_for(user_id)
        tokens[user_id] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id,
                user_id,
                token_digest,
                expires_at,
                last_seen_at,
                fresh_login_at,
                created_at,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    return tokens


async def post(
    client: httpx.AsyncClient,
    path: str,
    token: str,
    body: Mapping[str, object],
    request_id: str,
) -> httpx.Response:
    return await client.post(
        path,
        cookies={SESSION_COOKIE_NAME: token},
        headers={"X-Request-ID": request_id},
        json=body,
    )


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(error.get("code"))


async def twenty_record(
    client: httpx.AsyncClient,
    collection: str,
    record_id: str,
) -> dict[str, Any]:
    response = await client.get(f"/rest/{collection}/{record_id}")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    record: object = None
    if isinstance(data, dict):
        if len(data) == 1:
            nested = next(iter(data.values()))
            record = nested if isinstance(nested, dict) else data
        else:
            record = data
    if not isinstance(record, dict):
        raise ContractFailure(f"Twenty-{collection}-Datensatz fehlt")
    return record


async def twenty_collection(
    client: httpx.AsyncClient,
    collection: str,
) -> list[dict[str, Any]]:
    response = await client.get(f"/rest/{collection}", params={"limit": 100})
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    records = data.get(collection) if isinstance(data, dict) else None
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ContractFailure(f"Twenty-{collection}-Liste fehlt")
    return records


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    tokens = await seed_sessions(connection)
    path = f"/api/v1/actions/{ACTION_ID}/acquisition/sponsor-match"
    company_draft: dict[str, object] = {
        "companyName": "Baeckerei  Sonnenseite K.G.",
        "postalCode": "99999",
        "city": "Nicht still überschreiben",
    }

    async with (
        httpx.AsyncClient(
            base_url=require_env("API_BASE_URL").rstrip("/"),
            timeout=60,
        ) as api,
        httpx.AsyncClient(
            base_url=require_env("TWENTY_BASE_URL").rstrip("/"),
            headers={
                "Authorization": f"Bearer {require_env('TWENTY_INTEGRATION_API_KEY')}"
            },
            timeout=60,
        ) as twenty,
    ):
        preview = await post(
            api,
            path,
            tokens[ANNA_ID],
            company_draft,
            "poc032:preview-company",
        )
        preview.raise_for_status()
        company_match = preview.json()
        if (
            company_match["status"] != "single_match"
            or company_match["normalizedKey"] != "baeckerei sonnenseite kg"
            or company_match["input"]["postalCode"] != "99999"
            or len(company_match["candidates"]) != 1
        ):
            raise ContractFailure("Normalisiertes Company-Matching ist nicht eindeutig")
        candidate = company_match["candidates"][0]
        if (
            UUID(candidate["twentyId"]) != GOLDEN_COMPANY_ID
            or candidate["postalCode"] != "10243"
            or candidate["city"] != "Beispielstadt"
            or candidate["assignedAcquirers"]
            != [{"userId": str(BERND_ID), "displayName": "Bernd Binder"}]
        ):
            raise ContractFailure(
                "Company-Treffer zeigt Bestand/Zuständigkeit nicht unverändert: "
                f"{candidate!r}"
            )

        resolve_body: dict[str, object] = {
            "commandId": command_id("reuse-unconfirmed"),
            "sponsor": company_draft,
            "expectedStatus": "single_match",
            "selectedTwentyId": str(GOLDEN_COMPANY_ID),
            "confirmExistingAssignments": False,
        }
        rejected = await post(
            api,
            f"{path}/resolve",
            tokens[ANNA_ID],
            resolve_body,
            "poc032:reuse-unconfirmed",
        )
        if (
            rejected.status_code != 409
            or error_code(rejected) != "sponsor_match_confirmation_required"
        ):
            raise ContractFailure("Mehrfachzuordnung war ohne Bestätigung möglich")
        premature = await connection.fetchval(
            """
            SELECT count(*)
            FROM acquisition_assignment
            WHERE action_id = $1
              AND twenty_company_id = $2
              AND acquirer_user_id = $3
            """,
            ACTION_ID,
            GOLDEN_COMPANY_ID,
            ANNA_ID,
        )
        if premature != 0:
            raise ContractFailure("Abgelehnte Bestätigung hat dennoch zugeordnet")

        resolve_body["commandId"] = command_id("reuse-confirmed")
        resolve_body["confirmExistingAssignments"] = True
        reused = await post(
            api,
            f"{path}/resolve",
            tokens[ANNA_ID],
            resolve_body,
            "poc032:reuse-confirmed",
        )
        reused.raise_for_status()
        reused_payload = reused.json()
        if (
            reused_payload["outcome"] != "reused"
            or reused_payload["assignmentCreated"] is not True
            or reused_payload["priorAssignees"]
            != [{"userId": str(BERND_ID), "displayName": "Bernd Binder"}]
        ):
            raise ContractFailure("Bestätigte Wiederverwendung ist nicht transparent")

        company_after = await twenty_record(
            twenty,
            "companies",
            str(GOLDEN_COMPANY_ID),
        )
        address = company_after.get("address")
        if not isinstance(address, dict):
            raise ContractFailure("Golden-Company besitzt keine Twenty-Adresse")
        if (
            address.get("addressPostcode") != "10243"
            or address.get("addressCity") != "Beispielstadt"
        ):
            raise ContractFailure(
                "Zusatzdaten haben den CRM-Bestand still überschrieben"
            )

        person_draft = {
            "givenName": "  MAX ",
            "familyName": "mustermann",
            "email": "neue-adresse@leonaid.invalid",
        }
        people = await post(
            api,
            path,
            tokens[ANNA_ID],
            person_draft,
            "poc032:preview-person",
        )
        people.raise_for_status()
        people_payload = people.json()
        if (
            people_payload["status"] != "ambiguous_match"
            or len(people_payload["candidates"]) != 2
        ):
            raise ContractFailure("Golden-Personenkonflikt ist nicht mehrdeutig")
        missing_selection = await post(
            api,
            f"{path}/resolve",
            tokens[ANNA_ID],
            {
                "commandId": command_id("person-no-selection"),
                "sponsor": person_draft,
                "expectedStatus": "ambiguous_match",
                "selectedTwentyId": None,
                "confirmExistingAssignments": False,
            },
            "poc032:person-no-selection",
        )
        if (
            missing_selection.status_code != 409
            or error_code(missing_selection) != "sponsor_match_selection_required"
        ):
            raise ContractFailure("Mehrdeutiger Personentreffer brauchte keine Auswahl")
        selected_person = await post(
            api,
            f"{path}/resolve",
            tokens[ANNA_ID],
            {
                "commandId": command_id("person-selected"),
                "sponsor": person_draft,
                "expectedStatus": "ambiguous_match",
                "selectedTwentyId": str(PRIVATE_MAX_ID),
                "confirmExistingAssignments": False,
            },
            "poc032:person-selected",
        )
        selected_person.raise_for_status()
        if UUID(selected_person.json()["twentyId"]) != PRIVATE_MAX_ID:
            raise ContractFailure("Ausgewählter Personentreffer wurde nicht verwendet")
        private_person = await twenty_record(twenty, "people", str(PRIVATE_MAX_ID))
        primary_email = private_person.get("emails", {}).get("primaryEmail")
        if primary_email != "max.mustermann.privat@leonaid.invalid":
            raise ContractFailure("Zusatz-E-Mail hat bestehenden Kontakt überschrieben")

        new_company_draft = {
            "companyName": "POC032 Nordlicht Werkstatt GmbH",
            "givenName": "Nora",
            "familyName": "Nordlicht",
            "email": "nora.nordlicht@leonaid.invalid",
            "streetLine1": "Testweg 32",
            "postalCode": "20320",
            "city": "Hamburg",
        }
        no_company = await post(
            api,
            path,
            tokens[ANNA_ID],
            new_company_draft,
            "poc032:new-company-preview",
        )
        no_company.raise_for_status()
        if no_company.json()["status"] != "no_match":
            raise ContractFailure("Neue Company wurde fälschlich gematcht")
        new_company_command = command_id("new-company")
        new_company_body = {
            "commandId": new_company_command,
            "sponsor": new_company_draft,
            "expectedStatus": "no_match",
            "selectedTwentyId": None,
            "confirmExistingAssignments": False,
        }
        created_company_responses = await asyncio.gather(
            post(
                api,
                f"{path}/resolve",
                tokens[ANNA_ID],
                new_company_body,
                "poc032:new-company-resolve-a",
            ),
            post(
                api,
                f"{path}/resolve",
                tokens[ANNA_ID],
                new_company_body,
                "poc032:new-company-resolve-b",
            ),
        )
        for response in created_company_responses:
            response.raise_for_status()
        company_payloads = [response.json() for response in created_company_responses]
        if (
            {payload["outcome"] for payload in company_payloads} != {"created"}
            or {payload["replayed"] for payload in company_payloads} != {False, True}
            or len({payload["twentyId"] for payload in company_payloads}) != 1
            or len({payload["assignmentId"] for payload in company_payloads}) != 1
        ):
            raise ContractFailure(
                "Paralleler Retry wurde nicht als identischer Vorgang wiedergegeben"
            )
        created_company_payload = company_payloads[0]
        if (
            created_company_payload["assignmentCreated"] is not True
            or not created_company_payload["contactTwentyId"]
        ):
            raise ContractFailure(
                "Neue Company wurde nicht mit Zuordnung und Kontakt angelegt"
            )

        replay = await post(
            api,
            f"{path}/resolve",
            tokens[ANNA_ID],
            new_company_body,
            "poc032:new-company-retry",
        )
        replay.raise_for_status()
        if (
            replay.json()["replayed"] is not True
            or replay.json()["twentyId"] != created_company_payload["twentyId"]
            or replay.json()["assignmentId"] != created_company_payload["assignmentId"]
        ):
            raise ContractFailure("Sequentieller Retry ist nicht idempotent")

        changed_body = dict(new_company_body)
        changed_body["sponsor"] = {**new_company_draft, "city": "Anderer Ort"}
        changed = await post(
            api,
            f"{path}/resolve",
            tokens[ANNA_ID],
            changed_body,
            "poc032:new-company-idempotency-conflict",
        )
        if changed.status_code != 409 or error_code(changed) != "idempotency_conflict":
            raise ContractFailure(
                "Dieselbe Vorgangs-ID akzeptierte abweichende Eingaben"
            )

        created_company_record = await twenty_record(
            twenty,
            "companies",
            created_company_payload["twentyId"],
        )
        if created_company_record.get("name") != new_company_draft["companyName"]:
            raise ContractFailure("Twenty-Company besitzt nicht den exakten Namen")
        created_contact = await twenty_record(
            twenty,
            "people",
            created_company_payload["contactTwentyId"],
        )
        if (
            created_contact.get("name", {}).get("firstName") != "Nora"
            or created_contact.get("name", {}).get("lastName") != "Nordlicht"
            or created_contact.get("emails", {}).get("primaryEmail")
            != "nora.nordlicht@leonaid.invalid"
            or created_contact.get("companyId") != created_company_payload["twentyId"]
        ):
            raise ContractFailure(
                "Twenty-Kontakt ist nicht exakt mit der neuen Company verknüpft"
            )
        company_duplicates = [
            record
            for record in await twenty_collection(twenty, "companies")
            if record.get("name") == new_company_draft["companyName"]
        ]
        contact_duplicates = [
            record
            for record in await twenty_collection(twenty, "people")
            if record.get("emails", {}).get("primaryEmail")
            == "nora.nordlicht@leonaid.invalid"
        ]
        if len(company_duplicates) != 1 or len(contact_duplicates) != 1:
            raise ContractFailure("Retry erzeugte Duplikate in Twenty")
        assignment_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM acquisition_assignment
            WHERE action_id = $1
              AND twenty_company_id = $2
              AND acquirer_user_id = $3
            """,
            ACTION_ID,
            UUID(created_company_payload["twentyId"]),
            ANNA_ID,
        )
        if assignment_count != 1:
            raise ContractFailure("Retry erzeugte doppelte Zuordnungen")

        new_person_draft = {
            "givenName": "Noah",
            "familyName": "POC032Probe",
            "email": "noah.poc032@leonaid.invalid",
        }
        no_person = await post(
            api,
            path,
            tokens[ANNA_ID],
            new_person_draft,
            "poc032:new-person-preview",
        )
        no_person.raise_for_status()
        if no_person.json()["status"] != "no_match":
            raise ContractFailure("Neue Person wurde fälschlich gematcht")
        created_person = await post(
            api,
            f"{path}/resolve",
            tokens[ANNA_ID],
            {
                "commandId": command_id("new-person"),
                "sponsor": new_person_draft,
                "expectedStatus": "no_match",
                "selectedTwentyId": None,
                "confirmExistingAssignments": False,
            },
            "poc032:new-person-resolve",
        )
        created_person.raise_for_status()
        if created_person.json()["outcome"] != "created":
            raise ContractFailure("Neue Person wurde nicht real angelegt")
        await twenty_record(twenty, "people", created_person.json()["twentyId"])

        unauthorized = await post(
            api,
            path,
            tokens[KLARA_ID],
            company_draft,
            "poc032:admin-no-self-assignment",
        )
        if unauthorized.status_code != 404:
            raise ContractFailure("Charity-Admin konnte sich als Akquisiteur zuordnen")

        audit_rows = await connection.fetch(
            """
            SELECT event_type, entity_id, payload
            FROM audit_event
            WHERE request_id = ANY($1::text[])
            ORDER BY request_id
            """,
            [
                "poc032:reuse-confirmed",
                "poc032:person-selected",
                "poc032:new-company-resolve-a",
                "poc032:new-company-resolve-b",
                "poc032:new-person-resolve",
            ],
        )
        if len(audit_rows) != 4 or {str(row["event_type"]) for row in audit_rows} != {
            "sponsor_party_created",
            "sponsor_party_reused",
        }:
            raise ContractFailure("Neuanlage/Wiederverwendung ist nicht auditiert")
        history_count = await connection.fetchval(
            """
            SELECT count(*)
            FROM acquisition_assignment_history AS history
            JOIN acquisition_assignment AS assignment
              ON assignment.id = history.assignment_id
            WHERE assignment.action_id = $1
              AND assignment.acquirer_user_id = $2
              AND history.previous_state = '{}'::jsonb
            """,
            ACTION_ID,
            ANNA_ID,
        )
        if history_count < 4:
            raise ContractFailure("Initiale Zuordnungen besitzen keine Historie")

        await connection.execute(
            """
            DELETE FROM acquisition_assignment
            WHERE action_id = $1
              AND twenty_company_id = $2
              AND acquirer_user_id = $3
            """,
            ACTION_ID,
            GOLDEN_COMPANY_ID,
            ANNA_ID,
        )
        print(
            "matching-contract: OK:",
            "single/ambiguous/no-match, echte Neuanlage, unveränderte Zusatzdaten,",
            "explizite Mehrfachzuordnung und Audit bewiesen",
        )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
