#!/usr/bin/env python3
"""Real-system contract probe for the LeonAid Twenty CRM gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import httpx
from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.crm import (
    CompanyData,
    CompanyRecord,
    CompanyUpdate,
    CrmGatewayError,
    CrmPartyKind,
    CrmSyncReceipt,
    CrmSyncStatus,
    PersonData,
    PersonRecord,
    PersonUpdate,
    PostalAddress,
)
from leonaid.application.crm_matching import (
    company_match_key,
    find_company_matches,
    find_person_matches,
    person_match_key,
)

JsonObject = dict[str, Any]
NAMESPACE = UUID("7dd77a50-54f3-4b04-a6a1-309a4915e586")
COMPANY_PREFIX = "POC031 Seitenprobe"
PERSON_FAMILY_NAME = "POC031-Seitenprobe"
COMPANY_COUNT = 65
PERSON_COUNT = 61
# Records written around the gateway, as the Twenty UI or a CSV import would.
UNKEYED_COMPANY_NAME = "POC031 Großbäckerei Übermut K.G."
UNKEYED_COMPANY_INPUT = "POC031 Grossbaeckerei  Uebermut KG"
UNKEYED_GIVEN_NAME = "Jürgen"
UNKEYED_FAMILY_NAME = "POC031-Müller-Überall"
STALE_COMPANY_OLD_NAME = "POC031 Altname Apotheke"
STALE_COMPANY_NEW_NAME = "POC031 Löwen-Apotheke"


class ContractFailure(RuntimeError):
    """The real Twenty instance violated the CRM gateway contract."""


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"erforderliche Umgebungsvariable fehlt: {name}")
    return value


def local_id(kind: str, number: int) -> UUID:
    return uuid5(NAMESPACE, f"{kind}:{number}")


def settings(*, timeout_seconds: float = 5.0) -> TwentyGatewaySettings:
    return TwentyGatewaySettings(
        base_url=require_env("TWENTY_BASE_URL"),
        api_key=SecretStr(require_env("TWENTY_INTEGRATION_API_KEY")),
        timeout_seconds=timeout_seconds,
        page_size=13,
        requests_per_minute=100,
        max_rate_limit_retries=1,
        max_retry_after_seconds=2,
    )


def company(number: int) -> CompanyData:
    return CompanyData(
        name=f"{COMPANY_PREFIX} {number:03d}",
        address=PostalAddress(
            street_line_1=f"Löwenweg {number}",
            postal_code=f"{48000 + number:05d}",
            city="Münster",
            country="Deutschland",
        ),
    )


def person(number: int, company_twenty_id: UUID) -> PersonData:
    return PersonData(
        given_name=f"Probe{number:03d}",
        family_name=PERSON_FAMILY_NAME,
        email=f"poc031-{number:03d}@example.invalid",
        company_twenty_id=company_twenty_id,
        phone=f"+49151100{number:05d}",
    )


def assert_receipt(
    receipt: CrmSyncReceipt,
    *,
    expected_local_id: UUID,
    expected_kind: CrmPartyKind,
    correlation_id: str,
) -> None:
    if receipt.leonaid_id != expected_local_id:
        raise ContractFailure("Sync-Receipt verlor die LeonAid-ID")
    if receipt.party_kind is not expected_kind:
        raise ContractFailure("Sync-Receipt enthält den falschen Party-Typ")
    if receipt.status is not CrmSyncStatus.SYNCED:
        raise ContractFailure("Sync-Receipt ist nicht als synchron markiert")
    if receipt.correlation_id != correlation_id:
        raise ContractFailure("Sync-Receipt verlor die Korrelation")


def write_state(path: Path, state: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def read_state(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractFailure(f"Contract-State ist nicht lesbar: {path}") from error
    if not isinstance(value, dict):
        raise ContractFailure("Contract-State muss ein JSON-Objekt sein")
    return value


async def exercise(state_path: Path) -> None:
    correlation = "poc031:contract:batch"
    async with TwentyCrmGateway(settings()) as gateway:
        batch_input = tuple(
            (local_id("company", number), company(number))
            for number in range(1, COMPANY_COUNT + 1)
        )
        created = await gateway.create_companies(
            batch_input,
            correlation_id=correlation,
        )
        if len(created) != COMPANY_COUNT:
            raise ContractFailure("Company-Batch ist unvollständig")
        for (expected_id, _), (_, receipt) in zip(batch_input, created, strict=True):
            assert_receipt(
                receipt,
                expected_local_id=expected_id,
                expected_kind=CrmPartyKind.COMPANY,
                correlation_id=correlation,
            )

        found = await gateway.search_companies(
            COMPANY_PREFIX,
            correlation_id="poc031:contract:company-pagination",
        )
        found_ids = [record.twenty_id for record in found]
        if len(found_ids) != COMPANY_COUNT or len(set(found_ids)) != COMPANY_COUNT:
            raise ContractFailure(
                "Cursor-Pagination fand die 65 Companies nicht genau einmal"
            )
        expected_ids = {record.twenty_id for record, _ in created}
        if set(found_ids) != expected_ids:
            raise ContractFailure("Company-Pagination verlor oder erfand IDs")

        first_record, first_receipt = created[0]
        updated, update_receipt = await gateway.update_company(
            first_receipt.leonaid_id,
            first_record.twenty_id,
            CompanyUpdate(
                name=f"{COMPANY_PREFIX} 001 aktualisiert",
                address=PostalAddress(
                    street_line_1="Löwenweg 1A",
                    postal_code="48143",
                    city="Münster",
                    country="Deutschland",
                ),
            ),
            correlation_id="poc031:contract:update-company",
        )
        if (
            updated.data.name != f"{COMPANY_PREFIX} 001 aktualisiert"
            or updated.data.address.postal_code != "48143"
        ):
            raise ContractFailure("kontrolliertes Company-Update ist nicht sichtbar")
        assert_receipt(
            update_receipt,
            expected_local_id=first_receipt.leonaid_id,
            expected_kind=CrmPartyKind.COMPANY,
            correlation_id="poc031:contract:update-company",
        )
        loaded_company = await gateway.get_company(
            updated.twenty_id,
            correlation_id="poc031:contract:get-company",
        )
        if loaded_company != updated:
            raise ContractFailure("Company-Read stimmt nicht mit Update überein")

        single_company_local_id = local_id("company-single", 1)
        single_company, single_company_receipt = await gateway.create_company(
            single_company_local_id,
            CompanyData(
                name="POC031 Einzelunternehmen",
                address=PostalAddress(
                    postal_code="48155",
                    city="Münster",
                    country="Deutschland",
                ),
            ),
            correlation_id="poc031:contract:create-company",
        )
        assert_receipt(
            single_company_receipt,
            expected_local_id=single_company_local_id,
            expected_kind=CrmPartyKind.COMPANY,
            correlation_id="poc031:contract:create-company",
        )
        if (
            await gateway.get_company(
                single_company.twenty_id,
                correlation_id="poc031:contract:get-created-company",
            )
            != single_company
        ):
            raise ContractFailure("einzeln angelegte Company ist nicht lesbar")

        people_input = tuple(
            (
                local_id("person", number),
                person(number, first_record.twenty_id),
            )
            for number in range(1, PERSON_COUNT + 1)
        )
        created_people = await gateway.create_people(
            people_input,
            correlation_id="poc031:contract:people-batch",
        )
        if len(created_people) != PERSON_COUNT:
            raise ContractFailure("People-Batch ist unvollständig")
        for (expected_id, _), (_, receipt) in zip(
            people_input, created_people, strict=True
        ):
            assert_receipt(
                receipt,
                expected_local_id=expected_id,
                expected_kind=CrmPartyKind.PERSON,
                correlation_id="poc031:contract:people-batch",
            )

        people_found = await gateway.search_people(
            given_name="Probe",
            family_name=PERSON_FAMILY_NAME,
            correlation_id="poc031:contract:person-pagination",
        )
        people_ids = [record.twenty_id for record in people_found]
        if len(people_ids) != PERSON_COUNT or len(set(people_ids)) != PERSON_COUNT:
            raise ContractFailure(
                "Cursor-Pagination fand die 61 People nicht genau einmal"
            )

        first_person, first_person_receipt = created_people[0]
        updated_person, person_update_receipt = await gateway.update_person(
            first_person_receipt.leonaid_id,
            first_person.twenty_id,
            PersonUpdate(
                given_name="ProbeAktualisiert",
                email="poc031-updated@example.invalid",
                phone="+4915110099999",
            ),
            correlation_id="poc031:contract:update-person",
        )
        if (
            updated_person.data.given_name != "ProbeAktualisiert"
            or updated_person.data.family_name != PERSON_FAMILY_NAME
            or updated_person.data.email != "poc031-updated@example.invalid"
            or updated_person.data.company_twenty_id != first_record.twenty_id
            or updated_person.data.phone != "+4915110099999"
        ):
            raise ContractFailure("kontrolliertes Person-Update ist nicht sichtbar")
        assert_receipt(
            person_update_receipt,
            expected_local_id=first_person_receipt.leonaid_id,
            expected_kind=CrmPartyKind.PERSON,
            correlation_id="poc031:contract:update-person",
        )
        loaded_person = await gateway.get_person(
            updated_person.twenty_id,
            correlation_id="poc031:contract:get-person",
        )
        if loaded_person != updated_person:
            raise ContractFailure("Person-Read stimmt nicht mit Update überein")

        single_person_local_id = local_id("person-single", 1)
        single_person, single_person_receipt = await gateway.create_person(
            single_person_local_id,
            PersonData(
                given_name="Einzel",
                family_name="POC031-Sponsor",
                email="poc031-einzel@example.invalid",
                company_twenty_id=single_company.twenty_id,
                phone="+4915110088888",
            ),
            correlation_id="poc031:contract:create-person",
        )
        assert_receipt(
            single_person_receipt,
            expected_local_id=single_person_local_id,
            expected_kind=CrmPartyKind.PERSON,
            correlation_id="poc031:contract:create-person",
        )
        if (
            await gateway.get_person(
                single_person.twenty_id,
                correlation_id="poc031:contract:get-created-person",
            )
            != single_person
        ):
            raise ContractFailure("einzeln angelegte Person ist nicht lesbar")

        match_state = await exercise_match_keys(
            gateway,
            company_ids=tuple(record.twenty_id for record, _ in created),
            person_ids=tuple(record.twenty_id for record, _ in created_people),
            first_company=updated,
            first_person=updated_person,
            single_company_id=single_company.twenty_id,
            single_person_id=single_person.twenty_id,
        )

    write_state(
        state_path,
        {
            "companyIds": sorted(str(value) for value in expected_ids),
            "companyCount": COMPANY_COUNT,
            "firstCompanyId": str(first_record.twenty_id),
            "firstCompanyLeonAidId": str(first_receipt.leonaid_id),
            "singleCompanyId": str(single_company.twenty_id),
            "personIds": sorted(str(record.twenty_id) for record, _ in created_people),
            "personCount": PERSON_COUNT,
            "firstPersonId": str(first_person.twenty_id),
            "firstPersonLeonAidId": str(first_person_receipt.leonaid_id),
            "singlePersonId": str(single_person.twenty_id),
            **match_state,
        },
    )
    print(
        "twenty-gateway-contract: CRUD, 60er-Batches, Korrelation und "
        "Cursor-Pagination real bewiesen"
    )


def raw_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=require_env("TWENTY_BASE_URL").rstrip("/"),
        headers={
            "Authorization": f"Bearer {require_env('TWENTY_INTEGRATION_API_KEY')}"
        },
        timeout=30,
    )


def raw_record(response: httpx.Response) -> JsonObject:
    if response.status_code not in {200, 201}:
        raise ContractFailure(
            f"Twenty-Rohzugriff scheiterte: HTTP {response.status_code} "
            f"{response.text[:300]}"
        )
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else None
    if isinstance(data, dict) and len(data) == 1:
        nested = next(iter(data.values()))
        if isinstance(nested, dict):
            return nested
    if not isinstance(data, dict):
        raise ContractFailure("Twenty-Rohzugriff lieferte keinen Datensatz")
    return data


def ids(records: tuple[CompanyRecord, ...] | tuple[PersonRecord, ...]) -> set[UUID]:
    return {record.twenty_id for record in records}


async def exercise_match_keys(
    gateway: TwentyCrmGateway,
    *,
    company_ids: tuple[UUID, ...],
    person_ids: tuple[UUID, ...],
    first_company: CompanyRecord,
    first_person: PersonRecord,
    single_company_id: UUID,
    single_person_id: UUID,
) -> JsonObject:
    """Prove key writes, exact lookups, batched reads and the 200-record page."""

    if ids(
        await gateway.find_companies_by_match_key(
            company_match_key(first_company.data.name),
            correlation_id="poc031:keys:renamed-company",
        )
    ) != {first_company.twenty_id}:
        raise ContractFailure("Company-Update pflegte den Match-Schlüssel nicht")
    # The person update changed only the given name; the gateway must still
    # store the key of the complete new name.
    if ids(
        await gateway.find_people_by_match_key(
            person_match_key(
                first_person.data.given_name, first_person.data.family_name
            ),
            correlation_id="poc031:keys:renamed-person",
        )
    ) != {first_person.twenty_id}:
        raise ContractFailure("Teil-Umbenennung pflegte den Person-Schlüssel nicht")

    variant, _ = await gateway.create_company(
        local_id("company-variant", 1),
        CompanyData(name="POC031 Bäckerei Sonnenschein K.G."),
        correlation_id="poc031:keys:create-variant",
    )
    by_key = await gateway.find_companies_by_match_key(
        "poc031 baeckerei sonnenschein kg",
        correlation_id="poc031:keys:variant-key",
    )
    found = await find_company_matches(
        gateway,
        "poc031 BAECKEREI  Sonnenschein KG",
        correlation_id="poc031:keys:variant-match",
    )
    if ids(by_key) != {variant.twenty_id} or ids(found) != {variant.twenty_id}:
        raise ContractFailure(
            "Schreibvariante wurde nicht exakt über den Schlüssel gefunden"
        )

    twins = await gateway.create_companies(
        (
            (local_id("company-twin", 1), CompanyData(name="POC031 Doppel-Werk GmbH")),
            (local_id("company-twin", 2), CompanyData(name="poc031 doppel werk GMBH")),
        ),
        correlation_id="poc031:keys:create-twins",
    )
    ambiguous = await find_company_matches(
        gateway,
        "POC031 Doppel Werk GmbH",
        correlation_id="poc031:keys:twins",
    )
    if ids(ambiguous) != {record.twenty_id for record, _ in twins}:
        raise ContractFailure(
            "Batch-Anlage pflegte keine Schlüssel oder Mehrdeutigkeit fehlt"
        )

    missing_id = local_id("company-missing", 1)
    companies = await gateway.get_companies(
        (*company_ids, single_company_id, missing_id),
        correlation_id="poc031:keys:get-companies",
    )
    if ids(companies) != {*company_ids, single_company_id}:
        raise ContractFailure("gebündelter Company-Read über 50 IDs ist unvollständig")
    people = await gateway.get_people(
        (*person_ids, single_person_id),
        correlation_id="poc031:keys:get-people",
    )
    if ids(people) != {*person_ids, single_person_id}:
        raise ContractFailure("gebündelter Person-Read über 50 IDs ist unvollständig")
    contacts = await gateway.list_company_contacts(
        (first_company.twenty_id, single_company_id),
        correlation_id="poc031:keys:contacts",
    )
    if ids(contacts) != {*person_ids, single_person_id}:
        raise ContractFailure("Kontakte der angefragten Firmen sind unvollständig")
    if await gateway.get_companies((), correlation_id="poc031:keys:empty") != ():
        raise ContractFailure("leere ID-Liste muss ohne Treffer bleiben")

    async with raw_client() as twenty:
        page = await twenty.get(
            "/rest/companies",
            params={
                "limit": 200,
                "filter": f'name[ilike]:"%{COMPANY_PREFIX}%"',
            },
        )
        page.raise_for_status()
        page_payload = page.json()
        page_records = page_payload["data"]["companies"]
        if (
            len(page_records) != COMPANY_COUNT
            or page_payload["pageInfo"]["hasNextPage"] is not False
        ):
            raise ContractFailure("Twenty liefert keine Seite mit 200 Datensätzen")

        unkeyed_company = raw_record(
            await twenty.post(
                "/rest/companies",
                json={
                    "id": str(local_id("company-unkeyed", 1)),
                    "name": UNKEYED_COMPANY_NAME,
                },
            )
        )
        unkeyed_person = raw_record(
            await twenty.post(
                "/rest/people",
                json={
                    "id": str(local_id("person-unkeyed", 1)),
                    "name": {
                        "firstName": UNKEYED_GIVEN_NAME,
                        "lastName": UNKEYED_FAMILY_NAME,
                    },
                },
            )
        )
        stale, _ = await gateway.create_company(
            local_id("company-stale", 1),
            CompanyData(name=STALE_COMPANY_OLD_NAME),
            correlation_id="poc031:keys:create-stale",
        )
        renamed = raw_record(
            await twenty.patch(
                f"/rest/companies/{stale.twenty_id}",
                json={"name": STALE_COMPANY_NEW_NAME},
            )
        )
    if unkeyed_company.get("leonaidMatchKey") or unkeyed_person.get("leonaidMatchKey"):
        raise ContractFailure("Rohdatensätze dürfen noch keinen Schlüssel besitzen")
    if renamed.get("leonaidMatchKey") != company_match_key(STALE_COMPANY_OLD_NAME):
        raise ContractFailure(
            "Umbenennung außerhalb LeonAids muss den Schlüssel veralten"
        )
    # Without a stored key neither the key lookup nor the literal name search
    # can see these spelling variants; the repair run must close that gap.
    if await find_company_matches(
        gateway,
        UNKEYED_COMPANY_INPUT,
        correlation_id="poc031:keys:unkeyed-before",
    ):
        raise ContractFailure("ungepflegte Schreibvariante wurde unerwartet gefunden")
    # A stale stored key must never produce a match for the old name.
    if await find_company_matches(
        gateway,
        STALE_COMPANY_OLD_NAME,
        correlation_id="poc031:keys:stale-before",
    ):
        raise ContractFailure("veralteter Schlüssel erzeugte einen falschen Treffer")
    print(
        "twenty-gateway-contract: Match-Schlüssel, exakte Varianten, "
        "Mehrdeutigkeit, ID-Batches und 200er-Seite real bewiesen"
    )
    return {
        "unkeyedCompanyId": str(unkeyed_company["id"]),
        "unkeyedPersonId": str(unkeyed_person["id"]),
        "staleCompanyId": str(stale.twenty_id),
    }


async def verify_match_key_repair(state_path: Path) -> None:
    """Run after the operator command repaired keys written outside LeonAid."""

    state = read_state(state_path)
    async with TwentyCrmGateway(settings()) as gateway:
        company = await find_company_matches(
            gateway,
            UNKEYED_COMPANY_INPUT,
            correlation_id="poc031:repair:company",
        )
        person = await find_person_matches(
            gateway,
            given_name="Juergen",
            family_name="POC031 Mueller Ueberall",
            correlation_id="poc031:repair:person",
        )
        renamed = await find_company_matches(
            gateway,
            "POC031 Loewen Apotheke",
            correlation_id="poc031:repair:renamed",
        )
        old_name = await find_company_matches(
            gateway,
            STALE_COMPANY_OLD_NAME,
            correlation_id="poc031:repair:old-name",
        )
        second_run = await gateway.repair_match_keys(
            updated_since=None,
            correlation_id="poc031:repair:idempotent",
        )
    if ids(company) != {UUID(str(state["unkeyedCompanyId"]))}:
        raise ContractFailure("Backfill machte die Bestandsfirma nicht auffindbar")
    if ids(person) != {UUID(str(state["unkeyedPersonId"]))}:
        raise ContractFailure("Backfill machte die Bestandsperson nicht auffindbar")
    if ids(renamed) != {UUID(str(state["staleCompanyId"]))} or old_name:
        raise ContractFailure("Reparatur korrigierte den veralteten Schlüssel nicht")
    if any(report.repaired for report in second_run) or not all(
        report.scanned for report in second_run
    ):
        raise ContractFailure("zweiter Reparaturlauf war nicht idempotent")
    print(
        "twenty-gateway-contract: Backfill/Reparatur macht Bestandsdatensätze "
        "auffindbar und ist idempotent"
    )


async def expect_outage(state_path: Path) -> None:
    state = read_state(state_path)
    company_id = UUID(str(state["firstCompanyId"]))
    leonaid_id = UUID(str(state["firstCompanyLeonAidId"]))
    api_key = require_env("TWENTY_INTEGRATION_API_KEY")
    read_codes: list[str] = []
    async with TwentyCrmGateway(settings(timeout_seconds=0.75)) as gateway:
        for number in (1, 2):
            correlation = f"poc031:outage:read:{number}"
            try:
                await gateway.get_company(
                    company_id,
                    correlation_id=correlation,
                )
            except CrmGatewayError as error:
                if (
                    error.code not in {"crm_unavailable", "crm_timeout"}
                    or not error.retryable
                    or error.outcome_unknown
                    or error.correlation_id != correlation
                ):
                    raise ContractFailure(
                        "Twenty-Ausfall erzeugte keinen stabilen Read-Fehler"
                    ) from error
                if api_key in str(error) or api_key in repr(error.__dict__):
                    raise ContractFailure("Gateway-Fehler enthält den API-Key")
                read_codes.append(error.code)
            else:
                raise ContractFailure("gestopptes Twenty beantwortete einen Read")
        try:
            await gateway.update_company(
                leonaid_id,
                company_id,
                CompanyUpdate(name=f"{COMPANY_PREFIX} darf nicht verloren gehen"),
                correlation_id="poc031:outage:write",
            )
        except CrmGatewayError as error:
            if (
                error.code not in {"crm_unavailable", "crm_timeout"}
                or not error.retryable
                or not error.outcome_unknown
                or error.sync_status is not CrmSyncStatus.OUTCOME_UNKNOWN
            ):
                raise ContractFailure(
                    "Twenty-Ausfall markierte den Schreibausgang nicht als unbekannt"
                ) from error
            if error.leonaid_id != leonaid_id or error.twenty_id != company_id:
                raise ContractFailure("Ausfallfehler verlor LeonAid-/Twenty-ID")
            if api_key in str(error) or api_key in repr(error.__dict__):
                raise ContractFailure("Gateway-Fehler enthält den API-Key")
        else:
            raise ContractFailure("gestopptes Twenty beantwortete einen Write")
    if len(set(read_codes)) != 1:
        raise ContractFailure("wiederholter Twenty-Ausfall war nicht stabil")
    print(
        "twenty-gateway-outage: wiederholbarer Read-Fehler und "
        "outcome_unknown für Write bewiesen"
    )


async def verify_after_restart(state_path: Path) -> None:
    state = read_state(state_path)
    expected_company_ids = {UUID(value) for value in state["companyIds"]}
    expected_person_ids = {UUID(value) for value in state["personIds"]}
    single_company_id = UUID(str(state["singleCompanyId"]))
    single_person_id = UUID(str(state["singlePersonId"]))
    async with TwentyCrmGateway(settings()) as gateway:
        companies = await gateway.search_companies(
            COMPANY_PREFIX,
            correlation_id="poc031:restart:companies",
        )
        people = await gateway.search_people(
            given_name="Probe",
            family_name=PERSON_FAMILY_NAME,
            correlation_id="poc031:restart:people",
        )
        single_company = await gateway.get_company(
            single_company_id,
            correlation_id="poc031:restart:single-company",
        )
        single_person = await gateway.get_person(
            single_person_id,
            correlation_id="poc031:restart:single-person",
        )
    if {record.twenty_id for record in companies} != expected_company_ids:
        raise ContractFailure("Company-Daten gingen beim Twenty-Ausfall verloren")
    if {record.twenty_id for record in people} != expected_person_ids:
        raise ContractFailure("Person-Daten gingen beim Twenty-Ausfall verloren")
    if single_company is None or single_company.twenty_id != single_company_id:
        raise ContractFailure("einzeln angelegte Company ging beim Ausfall verloren")
    if single_person is None or single_person.twenty_id != single_person_id:
        raise ContractFailure("einzeln angelegte Person ging beim Ausfall verloren")
    print(
        "twenty-gateway-restart: alle zuvor bestätigten CRM-Datensätze "
        "sind exakt erhalten"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)
    for command in (
        "exercise",
        "verify-match-key-repair",
        "expect-outage",
        "verify-after-restart",
    ):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--state", type=Path, required=True)
    return result


async def async_main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "exercise":
        await exercise(arguments.state)
    elif arguments.command == "verify-match-key-repair":
        await verify_match_key_repair(arguments.state)
    elif arguments.command == "expect-outage":
        await expect_outage(arguments.state)
    elif arguments.command == "verify-after-restart":
        await verify_after_restart(arguments.state)
    else:
        raise AssertionError("unbekanntes Contract-Kommando")


def main() -> None:
    try:
        asyncio.run(async_main())
    except (
        ContractFailure,
        CrmGatewayError,
        ValueError,
        KeyError,
        httpx.HTTPError,
    ) as error:
        detail = (
            f" [code={error.code} operation={error.operation} "
            f"correlation={error.correlation_id} http={error.http_status}]"
            if isinstance(error, CrmGatewayError)
            else ""
        )
        print(f"twenty-gateway-contract: ERROR: {error}{detail}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
