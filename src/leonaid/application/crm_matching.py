"""Exact CRM party matching shared by imports, sponsor capture and public orders.

Every company or person has one normalized match key. Two parties match when
their keys are equal; more than one match is an ambiguity that callers must
surface instead of creating a duplicate.

Twenty cannot evaluate the normalization itself, so the CRM adapter stores the
key in a provisioned CRM field on every write, and an idempotent repair run
backfills records that were created or renamed outside LeonAid. A lookup
combines two bounded Twenty queries and never lists a whole collection:

* the exact key lookup finds every record whose stored key is current, also
  for spelling variants such as ``Müller``/``Mueller`` or ``K.G.``/``KG``;
* the name search finds records without a stored key (for example records
  created in the Twenty UI since the last repair) whenever the name contains
  the searched token literally.

The result is always filtered by recomputing the key from the current name, so
a stale stored key never produces a false match.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from leonaid.application.crm import CompanyRecord, PersonRecord

MATCH_KEY_MAX_LENGTH = 700


def normalize_match_name(value: str) -> str:
    """Return the PoC match key shared by imports and interactive matching."""

    normalized = unicodedata.normalize("NFC", value.casefold())
    normalized = normalized.replace("k.g.", "kg").replace("e.k.", "ek")
    normalized = (
        normalized.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    normalized = unicodedata.normalize("NFKD", normalized)
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def company_match_key(name: str) -> str:
    return normalize_match_name(name)


def person_match_key(given_name: str, family_name: str) -> str:
    return normalize_match_name(f"{given_name} {family_name}")


def candidate_company_query(value: str) -> str:
    """Choose a useful Twenty pre-filter without changing the exact match key."""

    ignored = {"ag", "ek", "gbr", "gmbh", "kg", "mbh", "ohg", "ug"}
    tokens = [
        token
        for token in normalize_match_name(value).split()
        if token not in ignored and len(token) >= 2
    ]
    if not tokens:
        tokens = normalize_match_name(value).split()
    if not tokens:
        raise ValueError("Firmenname enthält keinen suchbaren Bestandteil.")
    return max(tokens, key=len)


def company_matches(
    records: tuple[CompanyRecord, ...],
    normalized_key: str,
) -> tuple[CompanyRecord, ...]:
    return tuple(
        record
        for record in records
        if company_match_key(record.data.name) == normalized_key
    )


def person_matches(
    records: tuple[PersonRecord, ...],
    normalized_key: str,
) -> tuple[PersonRecord, ...]:
    return tuple(
        record
        for record in records
        if person_match_key(record.data.given_name, record.data.family_name)
        == normalized_key
    )


class CrmMatchLookup(Protocol):
    """The bounded CRM queries an exact match lookup needs."""

    async def search_companies(
        self,
        name_query: str,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, ...]: ...

    async def find_companies_by_match_key(
        self,
        match_key: str,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, ...]: ...

    async def search_people(
        self,
        *,
        given_name: str,
        family_name: str,
        correlation_id: str,
    ) -> tuple[PersonRecord, ...]: ...

    async def find_people_by_match_key(
        self,
        match_key: str,
        *,
        correlation_id: str,
    ) -> tuple[PersonRecord, ...]: ...


def _unique[RecordT: (CompanyRecord, PersonRecord)](
    groups: Iterable[tuple[RecordT, ...]],
) -> tuple[RecordT, ...]:
    seen: set[UUID] = set()
    result: list[RecordT] = []
    for group in groups:
        for record in group:
            if record.twenty_id not in seen:
                seen.add(record.twenty_id)
                result.append(record)
    return tuple(result)


async def find_company_matches(
    crm: CrmMatchLookup,
    company_name: str,
    *,
    correlation_id: str,
) -> tuple[CompanyRecord, ...]:
    """Return every CRM company whose current name has the same match key."""

    normalized_key = company_match_key(company_name)
    if not normalized_key:
        raise ValueError("Firmenname enthält keinen suchbaren Bestandteil.")
    by_key, by_name = await asyncio.gather(
        crm.find_companies_by_match_key(
            normalized_key,
            correlation_id=f"{correlation_id}:key",
        ),
        crm.search_companies(
            candidate_company_query(company_name),
            correlation_id=f"{correlation_id}:name",
        ),
    )
    return company_matches(_unique((by_key, by_name)), normalized_key)


async def find_person_matches(
    crm: CrmMatchLookup,
    *,
    given_name: str,
    family_name: str,
    correlation_id: str,
) -> tuple[PersonRecord, ...]:
    """Return every CRM person whose current full name has the same match key."""

    normalized_key = person_match_key(given_name, family_name)
    if not normalized_key:
        # Names without letters or digits have no storable key (the adapter
        # stores none for them); only the literal name search can find them.
        return person_matches(
            await crm.search_people(
                given_name=given_name,
                family_name=family_name,
                correlation_id=f"{correlation_id}:name",
            ),
            normalized_key,
        )
    by_key, by_name = await asyncio.gather(
        crm.find_people_by_match_key(
            normalized_key,
            correlation_id=f"{correlation_id}:key",
        ),
        crm.search_people(
            given_name=given_name,
            family_name=family_name,
            correlation_id=f"{correlation_id}:name",
        ),
    )
    return person_matches(_unique((by_key, by_name)), normalized_key)
