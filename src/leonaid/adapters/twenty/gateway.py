"""Twenty 2.24.0 adapter for LeonAid's semantic CRM port."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Self
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import SecretStr

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

JsonObject = dict[str, Any]
OperationKind = Literal["read", "write"]
logger = logging.getLogger(__name__)

TWENTY_RATE_LIMIT_PER_MINUTE = 100
TWENTY_BATCH_LIMIT = 60


@dataclass(frozen=True, slots=True)
class TwentyGatewaySettings:
    base_url: str
    api_key: SecretStr
    timeout_seconds: float = 5.0
    page_size: int = 20
    requests_per_minute: int = TWENTY_RATE_LIMIT_PER_MINUTE
    max_rate_limit_retries: int = 2
    max_retry_after_seconds: float = 60.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("Twenty base_url muss eine absolute HTTP(S)-URL sein.")
        if not self.api_key.get_secret_value():
            raise ValueError("Twenty API-Key darf nicht leer sein.")
        if self.timeout_seconds <= 0:
            raise ValueError("Twenty Timeout muss positiv sein.")
        if not 1 <= self.page_size <= TWENTY_BATCH_LIMIT:
            raise ValueError(
                f"Twenty page_size muss zwischen 1 und {TWENTY_BATCH_LIMIT} liegen."
            )
        if not 1 <= self.requests_per_minute <= TWENTY_RATE_LIMIT_PER_MINUTE:
            raise ValueError(
                "Twenty requests_per_minute muss zwischen 1 und 100 liegen."
            )
        if self.max_rate_limit_retries < 0:
            raise ValueError("Twenty Rate-Limit-Retries dürfen nicht negativ sein.")
        if self.max_retry_after_seconds <= 0:
            raise ValueError("Twenty Retry-After-Obergrenze muss positiv sein.")


class _SlidingWindowRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self._limit = requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                cutoff = now - 60.0
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._limit:
                    self._timestamps.append(now)
                    return
                await asyncio.sleep(max(0.01, 60.0 - (now - self._timestamps[0])))


class TwentyCrmGateway:
    """No Twenty wire field escapes this adapter."""

    def __init__(self, settings: TwentyGatewaySettings) -> None:
        self._settings = settings
        timeout = httpx.Timeout(
            settings.timeout_seconds,
            connect=settings.timeout_seconds,
            read=settings.timeout_seconds,
            write=settings.timeout_seconds,
            pool=settings.timeout_seconds,
        )
        self._client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": (f"Bearer {settings.api_key.get_secret_value()}"),
                "Accept": "application/json",
                "User-Agent": "LeonAid/0.0.0 TwentyGateway/2.24.0",
            },
        )
        self._rate_limiter = _SlidingWindowRateLimiter(settings.requests_per_minute)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def list_companies(
        self,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, ...]:
        records = await self._list_collection(
            "companies",
            filter_expression=None,
            correlation_id=correlation_id,
            operation="list_companies",
        )
        return tuple(_company_from_wire(record) for record in records)

    async def search_companies(
        self,
        name_query: str,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, ...]:
        query = _search_text(name_query, "Firmen-Suchbegriff")
        records = await self._list_collection(
            "companies",
            filter_expression=_contains_filter("name", query),
            correlation_id=correlation_id,
            operation="search_companies",
        )
        return tuple(_company_from_wire(record) for record in records)

    async def get_company(
        self,
        twenty_id: UUID,
        *,
        correlation_id: str,
    ) -> CompanyRecord | None:
        response = await self._request(
            "GET",
            f"/rest/companies/{twenty_id}",
            operation="get_company",
            operation_kind="read",
            correlation_id=correlation_id,
            twenty_id=twenty_id,
        )
        if response.status_code == 404:
            return None
        return _company_from_wire(_single_record(response, "company"))

    async def create_company(
        self,
        leonaid_id: UUID,
        company: CompanyData,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, CrmSyncReceipt]:
        response = await self._request(
            "POST",
            "/rest/companies",
            operation="create_company",
            operation_kind="write",
            correlation_id=correlation_id,
            leonaid_id=leonaid_id,
            json_body={
                "id": str(leonaid_id),
                **_company_to_wire(company),
            },
        )
        record = _company_from_wire(_single_record(response, "company"))
        return record, _receipt(
            leonaid_id,
            record.twenty_id,
            CrmPartyKind.COMPANY,
            correlation_id,
        )

    async def create_companies(
        self,
        companies: tuple[tuple[UUID, CompanyData], ...],
        *,
        correlation_id: str,
    ) -> tuple[tuple[CompanyRecord, CrmSyncReceipt], ...]:
        _correlation_id(correlation_id)
        if not companies:
            return ()
        completed: list[tuple[CompanyRecord, CrmSyncReceipt]] = []
        for index in range(0, len(companies), TWENTY_BATCH_LIMIT):
            chunk = companies[index : index + TWENTY_BATCH_LIMIT]
            try:
                wire_records = await self._graphql_batch(
                    "createCompanies",
                    "CompanyCreateInput",
                    [_company_to_wire(company) for _, company in chunk],
                    _company_selection(),
                    operation="create_companies",
                    correlation_id=correlation_id,
                )
            except CrmGatewayError as error:
                raise _with_completed(error, tuple(item[1] for item in completed))
            if len(wire_records) != len(chunk):
                raise CrmGatewayError(
                    "crm_batch_response_invalid",
                    "Twenty lieferte nicht für jede Firma ein Batch-Ergebnis.",
                    operation="create_companies",
                    correlation_id=correlation_id,
                    retryable=False,
                    outcome_unknown=True,
                    completed=tuple(item[1] for item in completed),
                )
            for (leonaid_id, _), wire in zip(chunk, wire_records, strict=True):
                record = _company_from_wire(wire)
                completed.append(
                    (
                        record,
                        _receipt(
                            leonaid_id,
                            record.twenty_id,
                            CrmPartyKind.COMPANY,
                            correlation_id,
                        ),
                    )
                )
        return tuple(completed)

    async def update_company(
        self,
        leonaid_id: UUID,
        twenty_id: UUID,
        update: CompanyUpdate,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, CrmSyncReceipt]:
        response = await self._request(
            "PATCH",
            f"/rest/companies/{twenty_id}",
            operation="update_company",
            operation_kind="write",
            correlation_id=correlation_id,
            leonaid_id=leonaid_id,
            twenty_id=twenty_id,
            json_body=_company_update_to_wire(update),
        )
        record = _company_from_wire(_single_record(response, "company"))
        return record, _receipt(
            leonaid_id,
            record.twenty_id,
            CrmPartyKind.COMPANY,
            correlation_id,
        )

    async def list_people(
        self,
        *,
        correlation_id: str,
    ) -> tuple[PersonRecord, ...]:
        records = await self._list_collection(
            "people",
            filter_expression=None,
            correlation_id=correlation_id,
            operation="list_people",
        )
        return tuple(_person_from_wire(record) for record in records)

    async def search_people(
        self,
        *,
        given_name: str,
        family_name: str,
        correlation_id: str,
    ) -> tuple[PersonRecord, ...]:
        given = _search_text(given_name, "Vorname")
        family = _search_text(family_name, "Nachname")
        filter_expression = ",".join(
            (
                _contains_filter("name.firstName", given),
                _contains_filter("name.lastName", family),
            )
        )
        records = await self._list_collection(
            "people",
            filter_expression=filter_expression,
            correlation_id=correlation_id,
            operation="search_people",
        )
        return tuple(_person_from_wire(record) for record in records)

    async def get_person(
        self,
        twenty_id: UUID,
        *,
        correlation_id: str,
    ) -> PersonRecord | None:
        response = await self._request(
            "GET",
            f"/rest/people/{twenty_id}",
            operation="get_person",
            operation_kind="read",
            correlation_id=correlation_id,
            twenty_id=twenty_id,
        )
        if response.status_code == 404:
            return None
        return _person_from_wire(_single_record(response, "person"))

    async def create_person(
        self,
        leonaid_id: UUID,
        person: PersonData,
        *,
        correlation_id: str,
    ) -> tuple[PersonRecord, CrmSyncReceipt]:
        response = await self._request(
            "POST",
            "/rest/people",
            operation="create_person",
            operation_kind="write",
            correlation_id=correlation_id,
            leonaid_id=leonaid_id,
            json_body={
                "id": str(leonaid_id),
                **_person_to_wire(person),
            },
        )
        record = _person_from_wire(_single_record(response, "person"))
        return record, _receipt(
            leonaid_id,
            record.twenty_id,
            CrmPartyKind.PERSON,
            correlation_id,
        )

    async def create_people(
        self,
        people: tuple[tuple[UUID, PersonData], ...],
        *,
        correlation_id: str,
    ) -> tuple[tuple[PersonRecord, CrmSyncReceipt], ...]:
        _correlation_id(correlation_id)
        if not people:
            return ()
        completed: list[tuple[PersonRecord, CrmSyncReceipt]] = []
        for index in range(0, len(people), TWENTY_BATCH_LIMIT):
            chunk = people[index : index + TWENTY_BATCH_LIMIT]
            try:
                wire_records = await self._graphql_batch(
                    "createPeople",
                    "PersonCreateInput",
                    [_person_to_wire(person) for _, person in chunk],
                    _person_selection(),
                    operation="create_people",
                    correlation_id=correlation_id,
                )
            except CrmGatewayError as error:
                raise _with_completed(error, tuple(item[1] for item in completed))
            if len(wire_records) != len(chunk):
                raise CrmGatewayError(
                    "crm_batch_response_invalid",
                    "Twenty lieferte nicht für jede Person ein Batch-Ergebnis.",
                    operation="create_people",
                    correlation_id=correlation_id,
                    retryable=False,
                    outcome_unknown=True,
                    completed=tuple(item[1] for item in completed),
                )
            for (leonaid_id, _), wire in zip(chunk, wire_records, strict=True):
                record = _person_from_wire(wire)
                completed.append(
                    (
                        record,
                        _receipt(
                            leonaid_id,
                            record.twenty_id,
                            CrmPartyKind.PERSON,
                            correlation_id,
                        ),
                    )
                )
        return tuple(completed)

    async def update_person(
        self,
        leonaid_id: UUID,
        twenty_id: UUID,
        update: PersonUpdate,
        *,
        correlation_id: str,
    ) -> tuple[PersonRecord, CrmSyncReceipt]:
        response = await self._request(
            "PATCH",
            f"/rest/people/{twenty_id}",
            operation="update_person",
            operation_kind="write",
            correlation_id=correlation_id,
            leonaid_id=leonaid_id,
            twenty_id=twenty_id,
            json_body=_person_update_to_wire(update),
        )
        record = _person_from_wire(_single_record(response, "person"))
        return record, _receipt(
            leonaid_id,
            record.twenty_id,
            CrmPartyKind.PERSON,
            correlation_id,
        )

    async def _list_collection(
        self,
        collection: Literal["companies", "people"],
        *,
        filter_expression: str | None,
        correlation_id: str,
        operation: str,
    ) -> tuple[JsonObject, ...]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_ids: set[UUID] = set()
        records: list[JsonObject] = []
        page_number = 0
        while True:
            page_number += 1
            if page_number > 10_000:
                raise CrmGatewayError(
                    "crm_pagination_invalid",
                    "Twenty-Pagination überschritt die Sicherheitsgrenze.",
                    operation=operation,
                    correlation_id=correlation_id,
                    retryable=False,
                    outcome_unknown=False,
                )
            params: dict[str, str | int] = {"limit": self._settings.page_size}
            if filter_expression is not None:
                params["filter"] = filter_expression
            if cursor is not None:
                params["starting_after"] = cursor
            response = await self._request(
                "GET",
                f"/rest/{collection}",
                operation=operation,
                operation_kind="read",
                correlation_id=correlation_id,
                params=params,
            )
            payload = _json_object(response, "Listen-Response")
            data = _mapping(payload.get("data"), "Listen-Response.data")
            page = _object_list(data.get(collection), f"data.{collection}")
            for record in page:
                record_id = _uuid(record.get("id"), f"{collection}.id")
                if record_id in seen_ids:
                    raise CrmGatewayError(
                        "crm_pagination_duplicate",
                        "Twenty-Pagination lieferte einen Datensatz doppelt.",
                        operation=operation,
                        correlation_id=correlation_id,
                        retryable=False,
                        outcome_unknown=False,
                        twenty_id=record_id,
                    )
                seen_ids.add(record_id)
                records.append(record)
            page_info = _mapping(payload.get("pageInfo"), "Listen-Response.pageInfo")
            if page_info.get("hasNextPage") is not True:
                return tuple(records)
            next_cursor = page_info.get("endCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                raise CrmGatewayError(
                    "crm_pagination_invalid",
                    "Twenty-Pagination enthält keinen Folgecursor.",
                    operation=operation,
                    correlation_id=correlation_id,
                    retryable=False,
                    outcome_unknown=False,
                )
            if next_cursor in seen_cursors:
                raise CrmGatewayError(
                    "crm_pagination_loop",
                    "Twenty-Pagination wiederholt denselben Cursor.",
                    operation=operation,
                    correlation_id=correlation_id,
                    retryable=False,
                    outcome_unknown=False,
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    async def _graphql_batch(
        self,
        mutation_name: Literal["createCompanies", "createPeople"],
        input_name: Literal["CompanyCreateInput", "PersonCreateInput"],
        values: list[JsonObject],
        selection: str,
        *,
        operation: str,
        correlation_id: str,
    ) -> list[JsonObject]:
        if not 1 <= len(values) <= TWENTY_BATCH_LIMIT:
            raise ValueError(
                f"Twenty-Batch muss 1 bis {TWENTY_BATCH_LIMIT} Einträge enthalten."
            )
        query = (
            f"mutation Batch($data: [{input_name}!]!) {{ "
            f"{mutation_name}(data: $data) {{ {selection} }} }}"
        )
        response = await self._request(
            "POST",
            "/graphql",
            operation=operation,
            operation_kind="write",
            correlation_id=correlation_id,
            json_body={"query": query, "variables": {"data": values}},
        )
        payload = _json_object(response, "GraphQL-Batch")
        if payload.get("errors"):
            raise CrmGatewayError(
                "crm_request_rejected",
                "Twenty hat den CRM-Batch abgewiesen.",
                operation=operation,
                correlation_id=correlation_id,
                retryable=False,
                outcome_unknown=False,
                http_status=response.status_code,
            )
        data = _mapping(payload.get("data"), "GraphQL-Batch.data")
        return _object_list(data.get(mutation_name), mutation_name)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        operation_kind: OperationKind,
        correlation_id: str,
        leonaid_id: UUID | None = None,
        twenty_id: UUID | None = None,
        params: Mapping[str, str | int] | None = None,
        json_body: JsonObject | None = None,
    ) -> httpx.Response:
        request_id = _correlation_id(correlation_id)
        for attempt in range(self._settings.max_rate_limit_retries + 1):
            await self._rate_limiter.acquire()
            started_at = time.monotonic()
            logger.info(
                "twenty_crm_request_started",
                extra={
                    "operation": operation,
                    "correlationId": request_id,
                    "attempt": attempt + 1,
                    "leonaidId": str(leonaid_id) if leonaid_id else None,
                    "twentyId": str(twenty_id) if twenty_id else None,
                },
            )
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers={
                        "X-Request-ID": request_id,
                        "X-Correlation-ID": request_id,
                    },
                )
            except httpx.TimeoutException:
                _log_failure(
                    "crm_timeout",
                    operation,
                    request_id,
                    leonaid_id,
                    twenty_id,
                )
                raise CrmGatewayError(
                    "crm_timeout",
                    "Twenty hat nicht innerhalb des konfigurierten Timeouts geantwortet.",
                    operation=operation,
                    correlation_id=request_id,
                    retryable=True,
                    outcome_unknown=operation_kind == "write",
                    leonaid_id=leonaid_id,
                    twenty_id=twenty_id,
                ) from None
            except httpx.RequestError:
                _log_failure(
                    "crm_unavailable",
                    operation,
                    request_id,
                    leonaid_id,
                    twenty_id,
                )
                raise CrmGatewayError(
                    "crm_unavailable",
                    "Twenty ist derzeit nicht erreichbar.",
                    operation=operation,
                    correlation_id=request_id,
                    retryable=True,
                    outcome_unknown=operation_kind == "write",
                    leonaid_id=leonaid_id,
                    twenty_id=twenty_id,
                ) from None

            logger.info(
                "twenty_crm_request_finished",
                extra={
                    "operation": operation,
                    "correlationId": request_id,
                    "attempt": attempt + 1,
                    "statusCode": response.status_code,
                    "durationMs": round((time.monotonic() - started_at) * 1000),
                    "leonaidId": str(leonaid_id) if leonaid_id else None,
                    "twentyId": str(twenty_id) if twenty_id else None,
                },
            )
            if response.status_code == 429:
                if attempt >= self._settings.max_rate_limit_retries:
                    raise CrmGatewayError(
                        "crm_rate_limited",
                        "Twenty hat das Anfrage-Limit erreicht.",
                        operation=operation,
                        correlation_id=request_id,
                        retryable=True,
                        outcome_unknown=False,
                        leonaid_id=leonaid_id,
                        twenty_id=twenty_id,
                        http_status=429,
                    )
                await asyncio.sleep(self._retry_after(response))
                continue
            if response.status_code == 404:
                return response
            if response.status_code in {401, 403}:
                raise CrmGatewayError(
                    "crm_permission_denied",
                    "Twenty hat den Zugriff verweigert.",
                    operation=operation,
                    correlation_id=request_id,
                    retryable=False,
                    outcome_unknown=False,
                    leonaid_id=leonaid_id,
                    twenty_id=twenty_id,
                    http_status=response.status_code,
                )
            if 400 <= response.status_code < 500:
                raise CrmGatewayError(
                    "crm_request_rejected",
                    "Twenty hat die CRM-Anfrage abgewiesen.",
                    operation=operation,
                    correlation_id=request_id,
                    retryable=False,
                    outcome_unknown=False,
                    leonaid_id=leonaid_id,
                    twenty_id=twenty_id,
                    http_status=response.status_code,
                )
            if response.status_code >= 500:
                raise CrmGatewayError(
                    "crm_unavailable",
                    "Twenty konnte die CRM-Anfrage nicht verarbeiten.",
                    operation=operation,
                    correlation_id=request_id,
                    retryable=True,
                    outcome_unknown=operation_kind == "write",
                    leonaid_id=leonaid_id,
                    twenty_id=twenty_id,
                    http_status=response.status_code,
                )
            return response
        raise AssertionError("Rate-Limit-Schleife muss terminieren.")

    def _retry_after(self, response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After", "1")
        try:
            seconds = float(raw)
        except ValueError:
            seconds = 1.0
        return min(max(seconds, 0.1), self._settings.max_retry_after_seconds)


def _correlation_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("correlation_id muss 1 bis 128 Zeichen enthalten.")
    if any(character.isspace() or ord(character) < 32 for character in normalized):
        raise ValueError(
            "correlation_id darf keine Leer- oder Steuerzeichen enthalten."
        )
    return normalized


def _search_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} darf nicht leer sein.")
    if len(normalized) > 200:
        raise ValueError(f"{label} darf höchstens 200 Zeichen enthalten.")
    return normalized


def _contains_filter(field_name: str, value: str) -> str:
    return f"{field_name}[ilike]:{json.dumps(f'%{value}%', ensure_ascii=False)}"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CrmGatewayError(
            "crm_response_invalid",
            f"Twenty lieferte ein ungültiges Format für {label}.",
            operation="parse_response",
            correlation_id="internal:response",
            retryable=False,
            outcome_unknown=False,
        )
    return value


def _json_object(response: httpx.Response, label: str) -> JsonObject:
    try:
        value = response.json()
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise CrmGatewayError(
            "crm_response_invalid",
            f"Twenty lieferte kein JSON-Objekt für {label}.",
            operation="parse_response",
            correlation_id="internal:response",
            retryable=False,
            outcome_unknown=False,
            http_status=response.status_code,
        )
    return value


def _object_list(value: object, label: str) -> list[JsonObject]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CrmGatewayError(
            "crm_response_invalid",
            f"Twenty lieferte keine Liste für {label}.",
            operation="parse_response",
            correlation_id="internal:response",
            retryable=False,
            outcome_unknown=False,
        )
    result: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            raise CrmGatewayError(
                "crm_response_invalid",
                f"Twenty lieferte einen ungültigen Datensatz für {label}.",
                operation="parse_response",
                correlation_id="internal:response",
                retryable=False,
                outcome_unknown=False,
            )
        result.append(item)
    return result


def _single_record(response: httpx.Response, singular_name: str) -> JsonObject:
    payload = _json_object(response, f"{singular_name}-Response")
    data = _mapping(payload.get("data", payload), f"{singular_name}-Response.data")
    nested = data.get(singular_name)
    if isinstance(nested, dict):
        return nested
    if len(data) == 1:
        only_value = next(iter(data.values()))
        if isinstance(only_value, dict):
            return only_value
    return dict(data)


def _uuid(value: object, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (AttributeError, ValueError):
        raise CrmGatewayError(
            "crm_response_invalid",
            f"Twenty lieferte keine gültige UUID für {label}.",
            operation="parse_response",
            correlation_id="internal:response",
            retryable=False,
            outcome_unknown=False,
        ) from None


def _company_to_wire(company: CompanyData) -> JsonObject:
    return {
        "name": company.name,
        "address": _address_to_wire(company.address),
    }


def _company_update_to_wire(update: CompanyUpdate) -> JsonObject:
    result: JsonObject = {}
    if update.name is not None:
        result["name"] = update.name
    if update.address is not None:
        result["address"] = _address_to_wire(update.address)
    return result


def _address_to_wire(address: PostalAddress) -> JsonObject:
    return {
        "addressStreet1": address.street_line_1 or "",
        "addressStreet2": address.street_line_2 or "",
        "addressPostcode": address.postal_code or "",
        "addressCity": address.city or "",
        "addressState": address.state or "",
        "addressCountry": address.country or "",
    }


def _person_to_wire(person: PersonData) -> JsonObject:
    result: JsonObject = {
        "name": {
            "firstName": person.given_name,
            "lastName": person.family_name,
        },
        "emails": {
            "primaryEmail": person.email or "",
            "additionalEmails": [],
        },
    }
    if person.company_twenty_id is not None:
        result["companyId"] = str(person.company_twenty_id)
    if person.phone is not None:
        result["phones"] = {
            "primaryPhoneNumber": person.phone,
            "additionalPhones": [],
        }
    return result


def _person_update_to_wire(update: PersonUpdate) -> JsonObject:
    result: JsonObject = {}
    if update.given_name is not None or update.family_name is not None:
        name: JsonObject = {}
        if update.given_name is not None:
            name["firstName"] = update.given_name
        if update.family_name is not None:
            name["lastName"] = update.family_name
        result["name"] = name
    if update.email is not None:
        result["emails"] = {
            "primaryEmail": update.email,
            "additionalEmails": [],
        }
    if update.company_twenty_id is not None:
        result["companyId"] = str(update.company_twenty_id)
    if update.phone is not None:
        result["phones"] = {
            "primaryPhoneNumber": update.phone,
            "additionalPhones": [],
        }
    return result


def _company_from_wire(value: Mapping[str, Any]) -> CompanyRecord:
    address_value = value.get("address")
    address = address_value if isinstance(address_value, Mapping) else {}
    return CompanyRecord(
        twenty_id=_uuid(value.get("id"), "company.id"),
        data=CompanyData(
            name=str(value.get("name", "")),
            address=PostalAddress(
                street_line_1=_wire_optional(address.get("addressStreet1")),
                street_line_2=_wire_optional(address.get("addressStreet2")),
                postal_code=_wire_optional(address.get("addressPostcode")),
                city=_wire_optional(address.get("addressCity")),
                state=_wire_optional(address.get("addressState")),
                country=_wire_optional(address.get("addressCountry")),
            ),
        ),
    )


def _person_from_wire(value: Mapping[str, Any]) -> PersonRecord:
    name_value = value.get("name")
    name = name_value if isinstance(name_value, Mapping) else {}
    emails_value = value.get("emails")
    emails = emails_value if isinstance(emails_value, Mapping) else {}
    phones_value = value.get("phones")
    phones = phones_value if isinstance(phones_value, Mapping) else {}
    company_id = value.get("companyId")
    if company_id is None:
        company_value = value.get("company")
        if isinstance(company_value, Mapping):
            company_id = company_value.get("id")
    return PersonRecord(
        twenty_id=_uuid(value.get("id"), "person.id"),
        data=PersonData(
            given_name=str(name.get("firstName", "")),
            family_name=str(name.get("lastName", "")),
            email=_wire_optional(emails.get("primaryEmail")),
            company_twenty_id=(
                None
                if company_id in {None, ""}
                else _uuid(company_id, "person.company")
            ),
            phone=_phone_from_wire(phones),
        ),
    )


def _phone_from_wire(value: Mapping[str, Any]) -> str | None:
    number = _wire_optional(value.get("primaryPhoneNumber"))
    if number is None:
        return None
    if number.startswith("+"):
        return number
    calling_code = _wire_optional(value.get("primaryPhoneCallingCode"))
    if calling_code is None or not calling_code.startswith("+"):
        return None
    return f"{calling_code}{number.lstrip('0')}"


def _wire_optional(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _receipt(
    leonaid_id: UUID,
    twenty_id: UUID,
    kind: CrmPartyKind,
    correlation_id: str,
) -> CrmSyncReceipt:
    receipt = CrmSyncReceipt(
        leonaid_id=leonaid_id,
        twenty_id=twenty_id,
        party_kind=kind,
        status=CrmSyncStatus.SYNCED,
        correlation_id=_correlation_id(correlation_id),
    )
    logger.info(
        "twenty_crm_sync_succeeded",
        extra={
            "correlationId": receipt.correlation_id,
            "leonaidId": str(receipt.leonaid_id),
            "twentyId": str(receipt.twenty_id),
            "partyKind": receipt.party_kind.value,
            "syncStatus": receipt.status.value,
        },
    )
    return receipt


def _log_failure(
    code: str,
    operation: str,
    correlation_id: str,
    leonaid_id: UUID | None,
    twenty_id: UUID | None,
) -> None:
    logger.warning(
        "twenty_crm_request_failed",
        extra={
            "errorCode": code,
            "operation": operation,
            "correlationId": correlation_id,
            "leonaidId": str(leonaid_id) if leonaid_id else None,
            "twentyId": str(twenty_id) if twenty_id else None,
        },
    )


def _with_completed(
    error: CrmGatewayError,
    completed: tuple[CrmSyncReceipt, ...],
) -> CrmGatewayError:
    return CrmGatewayError(
        error.code,
        error.message,
        operation=error.operation,
        correlation_id=error.correlation_id,
        retryable=error.retryable,
        outcome_unknown=error.outcome_unknown,
        leonaid_id=error.leonaid_id,
        twenty_id=error.twenty_id,
        http_status=error.http_status,
        completed=completed,
    )


def _company_selection() -> str:
    return (
        "id name address { addressStreet1 addressStreet2 addressPostcode "
        "addressCity addressState addressCountry }"
    )


def _person_selection() -> str:
    return (
        "id name { firstName lastName } emails { primaryEmail additionalEmails } "
        "companyId"
    )
