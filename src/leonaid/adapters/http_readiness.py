"""HTTP implementation of a narrow external-service readiness port."""

from __future__ import annotations

import httpx

from leonaid.application.platform import ProbeValue


class HttpReadinessProbe:
    def __init__(self, name: str, url: str) -> None:
        self._name = name
        self._url = url

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> dict[str, ProbeValue]:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(self._url)
        response.raise_for_status()
        return {"httpStatus": response.status_code}
