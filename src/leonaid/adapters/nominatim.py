"""Geocoder over the Nominatim JSON API (specs/krapfentaxi-touren §8.2).

Works with the public Nominatim, a self-hosted one or any provider with the
same API. Only street, postal code, city and country codes are sent, as a
structured query. Requests are spaced ``min_interval`` seconds apart (the
public service allows one per second) across all callers of one instance.
Errors are reported as a fixed code; the address never reaches a log.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from leonaid.domain.delivery_geo import (
    Failed,
    Found,
    GeocodeOutcome,
    GeocodeQuery,
    GeoPoint,
    NotFound,
    accept,
)
from leonaid.domain.errors import DomainInvariantError


class NominatimGeocoder:
    def __init__(
        self,
        url: str,
        user_agent: str,
        *,
        min_interval: float = 1.0,
        timeout: float = 10.0,
    ) -> None:
        if min_interval < 0 or timeout <= 0:
            raise ValueError("min_interval must be >= 0 and timeout > 0")
        self._url = url
        self._min_interval = min_interval
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=False,
        )
        self._lock = asyncio.Lock()
        self._last_request: float | None = None
        host = httpx.URL(url).host
        self._provider_id = f"nominatim:{host}"

    @property
    def provider_id(self) -> str:
        return self._provider_id

    async def close(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        # Called with the lock held: the gap counts from the previous start.
        if self._last_request is not None:
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def lookup(self, query: GeocodeQuery) -> GeocodeOutcome:
        params = {
            "street": query.street,
            "postalcode": query.postal_code,
            "city": query.city,
            "countrycodes": query.country_code.casefold(),
            "format": "jsonv2",
            "addressdetails": "1",
            "limit": "1",
        }
        async with self._lock:
            await self._throttle()
            try:
                response = await self._client.get(self._url, params=params)
            except httpx.TimeoutException:
                return Failed("timeout")
            except httpx.HTTPError:
                return Failed("transport")
        if response.status_code == 429:
            return Failed("rate_limited")
        if response.status_code != 200:
            return Failed(f"http_{response.status_code}")
        try:
            return _outcome(json.loads(response.content), query)
        except (ValueError, TypeError, KeyError, DomainInvariantError):
            return Failed("invalid_response")


def _outcome(document: Any, query: GeocodeQuery) -> GeocodeOutcome:
    if not isinstance(document, list):
        raise ValueError("not a result list")
    if not document:
        return NotFound()
    hit = document[0]
    if not isinstance(hit, dict):
        raise ValueError("not a result")
    address = hit.get("address")
    if not isinstance(address, dict):
        address = {}
    postcode = address.get("postcode")
    house_number = address.get("house_number")
    place_rank = hit.get("place_rank")
    if isinstance(place_rank, bool) or not isinstance(place_rank, int):
        place_rank = None
    if not accept(
        postcode if isinstance(postcode, str) else None,
        house_number if isinstance(house_number, str) else None,
        place_rank,
        query,
    ):
        return NotFound()
    return Found(GeoPoint.parse(hit["lat"], hit["lon"]))
