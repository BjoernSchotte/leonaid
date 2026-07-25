"""Stable identifiers shared by LeonAid aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError


@dataclass(frozen=True, slots=True)
class EntityId:
    """A stable UUIDv4 generated outside database implementation details."""

    value: UUID

    @classmethod
    def parse(cls, raw: str) -> EntityId:
        try:
            value = UUID(raw)
        except (AttributeError, ValueError) as error:
            raise DomainInvariantError(
                "entity_id_invalid",
                "Die fachliche ID muss eine gültige UUID sein.",
            ) from error
        if value.version != 4:
            raise DomainInvariantError(
                "entity_id_version_invalid",
                "Die fachliche ID muss eine UUID der Version 4 sein.",
            )
        return cls(value)

    def __str__(self) -> str:
        return str(self.value)
