"""Neutral CharityAction aggregate and lifecycle rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError


class CharityActionStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


ALLOWED_ACTION_TRANSITIONS: dict[
    CharityActionStatus,
    frozenset[CharityActionStatus],
] = {
    CharityActionStatus.DRAFT: frozenset({CharityActionStatus.SCHEDULED}),
    CharityActionStatus.SCHEDULED: frozenset(
        {CharityActionStatus.DRAFT, CharityActionStatus.ACTIVE}
    ),
    CharityActionStatus.ACTIVE: frozenset({CharityActionStatus.COMPLETED}),
    CharityActionStatus.COMPLETED: frozenset({CharityActionStatus.ARCHIVED}),
    CharityActionStatus.ARCHIVED: frozenset(),
}


class ActionCapability(StrEnum):
    ACQUISITION = "acquisition"
    OFFERINGS = "offerings"
    ORDERING = "ordering"
    INVOICING = "invoicing"


@dataclass(frozen=True, slots=True)
class ActionGoal:
    goal_value: Decimal | None
    actual_value: Decimal
    unit: str | None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.goal_value is not None and self.goal_value < 0:
            raise DomainInvariantError(
                "action_goal_negative",
                "Der Zielwert darf nicht negativ sein.",
            )
        if self.actual_value < 0:
            raise DomainInvariantError(
                "action_actual_negative",
                "Der Ist-Wert darf nicht negativ sein.",
            )
        if (self.goal_value is None) != (self.unit is None):
            raise DomainInvariantError(
                "action_goal_unit_incomplete",
                "Zielwert und Einheit müssen gemeinsam gepflegt werden.",
            )
        if self.unit is not None and not self.unit.strip():
            raise DomainInvariantError(
                "action_goal_unit_empty",
                "Die Zieleinheit darf nicht leer sein.",
            )
        for value, code, label in (
            (self.goal_value, "action_goal_precision", "Zielwert"),
            (self.actual_value, "action_actual_precision", "Ist-Wert"),
        ):
            if value is None:
                continue
            exponent = value.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -4:
                raise DomainInvariantError(
                    code,
                    f"Der {label} darf höchstens vier Nachkommastellen haben.",
                )
        if self.currency is not None and (
            len(self.currency) != 3 or not self.currency.isalpha()
        ):
            raise DomainInvariantError(
                "action_currency_invalid",
                "Die Währung muss aus drei Buchstaben bestehen.",
            )
        if self.currency is not None and self.currency != self.currency.upper():
            raise DomainInvariantError(
                "action_currency_invalid",
                "Die Währung muss großgeschrieben sein.",
            )


@dataclass(frozen=True, slots=True)
class Beneficiary:
    id: UUID
    action_id: UUID
    organization_name: str
    public_description: str
    sort_order: int

    def __post_init__(self) -> None:
        if not self.organization_name.strip():
            raise DomainInvariantError(
                "beneficiary_name_empty",
                "Der Name eines Begünstigten darf nicht leer sein.",
            )
        if not self.public_description.strip():
            raise DomainInvariantError(
                "beneficiary_description_empty",
                "Die öffentliche Beschreibung eines Begünstigten darf nicht leer sein.",
            )
        if self.sort_order < 0:
            raise DomainInvariantError(
                "beneficiary_sort_order_negative",
                "Die Reihenfolge eines Begünstigten darf nicht negativ sein.",
            )


@dataclass(frozen=True, slots=True)
class CharityAction:
    id: UUID
    carrier_name: str
    name: str
    purpose: str
    status: CharityActionStatus
    starts_on: date
    ends_on: date
    archive_slug: str
    capabilities: frozenset[ActionCapability]
    beneficiaries: tuple[Beneficiary, ...]
    goal: ActionGoal

    def __post_init__(self) -> None:
        for value, code, message in (
            (
                self.carrier_name,
                "action_carrier_empty",
                "Der Trägername darf nicht leer sein.",
            ),
            (self.name, "action_name_empty", "Der Aktionsname darf nicht leer sein."),
            (
                self.purpose,
                "action_purpose_empty",
                "Der Aktionszweck darf nicht leer sein.",
            ),
            (
                self.archive_slug,
                "action_archive_slug_empty",
                "Der Archiv-Slug darf nicht leer sein.",
            ),
        ):
            if not value.strip():
                raise DomainInvariantError(code, message)
        if self.starts_on > self.ends_on:
            raise DomainInvariantError(
                "action_period_invalid",
                "Der Aktionsbeginn darf nicht nach dem Aktionsende liegen.",
            )
        if not self.beneficiaries:
            raise DomainInvariantError(
                "action_beneficiary_required",
                "Eine Charity-Aktion benötigt mindestens einen Begünstigten.",
            )
        if any(item.action_id != self.id for item in self.beneficiaries):
            raise DomainInvariantError(
                "action_beneficiary_mismatch",
                "Alle Begünstigten müssen zur Charity-Aktion gehören.",
            )
        normalized_names = [
            " ".join(item.organization_name.split()).casefold()
            for item in self.beneficiaries
        ]
        if len(normalized_names) != len(set(normalized_names)):
            raise DomainInvariantError(
                "action_beneficiary_duplicate",
                "Begünstigte dürfen innerhalb einer Aktion nicht doppelt vorkommen.",
            )
        if (
            ActionCapability.ORDERING in self.capabilities
            and ActionCapability.OFFERINGS not in self.capabilities
        ):
            raise DomainInvariantError(
                "action_capability_dependency_invalid",
                "Bestellungen benötigen die Capability Angebote.",
            )

    def transition_to(self, target: CharityActionStatus) -> CharityAction:
        if target is self.status:
            return self
        if target not in ALLOWED_ACTION_TRANSITIONS[self.status]:
            raise DomainInvariantError(
                "action_status_transition_invalid",
                f"Der Aktionsstatus darf nicht von {self.status.value} "
                f"nach {target.value} wechseln.",
            )
        return replace(self, status=target)

    def with_goal(self, goal: ActionGoal) -> CharityAction:
        if self.status is CharityActionStatus.ARCHIVED:
            raise DomainInvariantError(
                "action_archived_immutable",
                "Eine archivierte Charity-Aktion kann nicht mehr geändert werden.",
            )
        return replace(self, goal=goal)

    def with_capabilities(
        self,
        capabilities: frozenset[ActionCapability],
    ) -> CharityAction:
        if self.status not in {
            CharityActionStatus.DRAFT,
            CharityActionStatus.SCHEDULED,
        }:
            raise DomainInvariantError(
                "action_capabilities_locked",
                "Capabilities können nur im Entwurf oder in der Planung geändert werden.",
            )
        return replace(self, capabilities=capabilities)

    def with_beneficiaries(
        self,
        beneficiaries: tuple[Beneficiary, ...],
    ) -> CharityAction:
        if self.status is CharityActionStatus.ARCHIVED:
            raise DomainInvariantError(
                "action_archived_immutable",
                "Eine archivierte Charity-Aktion kann nicht mehr geändert werden.",
            )
        return replace(self, beneficiaries=beneficiaries)
