#!/usr/bin/env python3
"""Verify POC-033 reports and resulting records against real Twenty."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from tools.twenty.import_contacts import candidate_company_query, normalize_name

JsonObject = dict[str, Any]
NORDSTERN_SOURCE = "c1000000-0000-4000-8000-000000000001"


class ContractFailure(RuntimeError):
    """The real import result did not match the Golden contract."""


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"erforderliche Umgebungsvariable fehlt: {name}")
    return value


def load_report(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractFailure(f"Importreport ist nicht lesbar: {path}") from error
    if not isinstance(value, dict):
        raise ContractFailure(f"Importreport ist kein JSON-Objekt: {path}")
    return value


def expect_summary(
    report: JsonObject,
    *,
    new: int,
    update: int,
    unchanged: int,
    conflict: int,
    rejected: int,
    applied: int,
) -> None:
    expected = {
        "new": new,
        "update": update,
        "unchanged": unchanged,
        "conflict": conflict,
        "rejected": rejected,
    }
    if report.get("summary") != expected or report.get("appliedCount") != applied:
        raise ContractFailure(
            f"unerwarteter Importreport: summary={report.get('summary')} "
            f"applied={report.get('appliedCount')}"
        )


def rows(report: JsonObject) -> list[JsonObject]:
    value = report.get("rows")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ContractFailure("Importreport enthält keine gültigen Zeilen")
    return value


def row_by_source(report: JsonObject, source_id: str) -> JsonObject:
    found = [item for item in rows(report) if item.get("source_id") == source_id]
    if len(found) != 1:
        raise ContractFailure(f"Reportzeile fehlt oder ist doppelt: {source_id}")
    return found[0]


async def verify(arguments: argparse.Namespace) -> None:
    dry = load_report(arguments.dry)
    first = load_report(arguments.first)
    second = load_report(arguments.second)
    repeat = load_report(arguments.repeat)
    expect_summary(
        dry,
        new=1,
        update=1,
        unchanged=0,
        conflict=1,
        rejected=1,
        applied=0,
    )
    expect_summary(
        first,
        new=1,
        update=1,
        unchanged=0,
        conflict=1,
        rejected=1,
        applied=2,
    )
    expect_summary(
        second,
        new=0,
        update=1,
        unchanged=1,
        conflict=1,
        rejected=1,
        applied=1,
    )
    expect_summary(
        repeat,
        new=0,
        update=0,
        unchanged=2,
        conflict=1,
        rejected=1,
        applied=0,
    )

    first_nordstern = row_by_source(first, NORDSTERN_SOURCE)
    second_nordstern = row_by_source(second, NORDSTERN_SOURCE)
    repeat_nordstern = row_by_source(repeat, NORDSTERN_SOURCE)
    target_ids = {
        item.get("target_twenty_id")
        for item in (first_nordstern, second_nordstern, repeat_nordstern)
    }
    if len(target_ids) != 1 or None in target_ids:
        raise ContractFailure(
            "Nordstern verlor beim Wiederholungsimport seine Twenty-ID"
        )

    conflict_rows = [item for item in rows(dry) if item.get("status") == "conflict"]
    if len(conflict_rows) != 1 or len(conflict_rows[0].get("candidates", [])) != 2:
        raise ContractFailure("Dry Run zeigt den Golden-Personenkonflikt nicht")
    rejected_rows = [item for item in rows(dry) if item.get("status") == "rejected"]
    if len(rejected_rows) != 1 or "family_name fehlt" not in str(
        rejected_rows[0].get("message")
    ):
        raise ContractFailure(
            "Dry Run besitzt keinen zeilenbezogenen Pflichtfeldfehler"
        )

    settings = TwentyGatewaySettings(
        base_url=require_env("TWENTY_BASE_URL"),
        api_key=SecretStr(require_env("TWENTY_INTEGRATION_API_KEY")),
        timeout_seconds=5,
        page_size=20,
    )
    async with TwentyCrmGateway(settings) as gateway:
        nordstern_candidates = await gateway.search_companies(
            candidate_company_query("Nordstern Handel GmbH"),
            correlation_id="poc033:verify:nordstern",
        )
        nordstern = [
            record
            for record in nordstern_candidates
            if normalize_name(record.data.name)
            == normalize_name("Nordstern Handel GmbH")
        ]
        musterwerk_candidates = await gateway.search_companies(
            candidate_company_query("Musterwerk GmbH"),
            correlation_id="poc033:verify:musterwerk",
        )
        musterwerk = [
            record
            for record in musterwerk_candidates
            if normalize_name(record.data.name) == normalize_name("Musterwerk GmbH")
        ]
        max_people = await gateway.search_people(
            given_name="Max",
            family_name="Mustermann",
            correlation_id="poc033:verify:max",
        )
        invalid_people = await gateway.search_people(
            given_name="Unvollständig",
            family_name="Fehlt",
            correlation_id="poc033:verify:rejected",
        )

    if len(nordstern) != 1:
        raise ContractFailure("Nordstern wurde nicht exakt einmal angelegt")
    if (
        nordstern[0].data.address.postal_code != "48157"
        or nordstern[0].data.address.city != "Münster-Ost"
        or nordstern[0].twenty_id != UUID(str(next(iter(target_ids))))
    ):
        raise ContractFailure("Nordstern besitzt nicht exakt das zweite Update")
    if len(musterwerk) != 1:
        raise ContractFailure("Musterwerk wurde dupliziert")
    if (
        musterwerk[0].data.address.postal_code != "10117"
        or musterwerk[0].data.address.city != "Beispielstadt"
        or musterwerk[0].data.address.country != "Deutschland"
    ):
        raise ContractFailure("Musterwerk wurde nicht kontrolliert aktualisiert")
    if len(max_people) != 2:
        raise ContractFailure("Personenkonflikt wurde verändert statt beibehalten")
    if invalid_people:
        raise ContractFailure("verworfene Zeile wurde dennoch in Twenty angelegt")
    print(
        "crm-import-contract: Reports, Update, Konflikt, Ablehnung und "
        "Idempotenz real bewiesen"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--dry", type=Path, required=True)
    result.add_argument("--first", type=Path, required=True)
    result.add_argument("--second", type=Path, required=True)
    result.add_argument("--repeat", type=Path, required=True)
    return result


def main() -> int:
    try:
        asyncio.run(verify(parser().parse_args()))
    except (ContractFailure, OSError, ValueError, KeyError) as error:
        print(f"crm-import-contract: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
