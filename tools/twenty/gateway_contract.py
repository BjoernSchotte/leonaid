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

from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.crm import (
    CompanyData,
    CompanyUpdate,
    CrmGatewayError,
    CrmPartyKind,
    CrmSyncReceipt,
    CrmSyncStatus,
    PersonData,
    PersonUpdate,
    PostalAddress,
)

JsonObject = dict[str, Any]
NAMESPACE = UUID("7dd77a50-54f3-4b04-a6a1-309a4915e586")
COMPANY_PREFIX = "POC031 Seitenprobe"
PERSON_FAMILY_NAME = "POC031-Seitenprobe"
COMPANY_COUNT = 65
PERSON_COUNT = 61


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
        },
    )
    print(
        "twenty-gateway-contract: CRUD, 60er-Batches, Korrelation und "
        "Cursor-Pagination real bewiesen"
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
    for command in ("exercise", "expect-outage", "verify-after-restart"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--state", type=Path, required=True)
    return result


async def async_main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "exercise":
        await exercise(arguments.state)
    elif arguments.command == "expect-outage":
        await expect_outage(arguments.state)
    elif arguments.command == "verify-after-restart":
        await verify_after_restart(arguments.state)
    else:
        raise AssertionError("unbekanntes Contract-Kommando")


def main() -> None:
    try:
        asyncio.run(async_main())
    except (ContractFailure, CrmGatewayError, ValueError, KeyError) as error:
        print(f"twenty-gateway-contract: ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
