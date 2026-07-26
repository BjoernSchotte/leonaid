"""Typed, versioned action-template and effective configuration models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from leonaid.domain.actions import ActionCapability
from leonaid.domain.errors import DomainInvariantError

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ActionTemplateKey(StrEnum):
    BLANK = "blank"
    KRAPFENTAXI = "krapfentaxi"


class OfferingStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"


class OfferingUnit(StrEnum):
    BOX = "box"
    PIECE = "piece"
    PACKAGE = "package"
    SPONSORING = "sponsoring"


@dataclass(frozen=True, slots=True)
class TemplateOffering:
    code: str
    name: str
    status: OfferingStatus
    unit: OfferingUnit
    pieces_per_unit: int | None
    unit_price_minor: int
    currency: str

    def __post_init__(self) -> None:
        if not SLUG.fullmatch(self.code):
            raise DomainInvariantError(
                "template_offering_code_invalid",
                "Der Angebotsschlüssel muss ein URL-tauglicher Slug sein.",
            )
        if not self.name.strip():
            raise DomainInvariantError(
                "template_offering_name_empty",
                "Der Angebotsname darf nicht leer sein.",
            )
        if self.pieces_per_unit is not None and self.pieces_per_unit <= 0:
            raise DomainInvariantError(
                "template_offering_pieces_invalid",
                "Die Stückzahl je Einheit muss positiv sein.",
            )
        if self.unit is OfferingUnit.BOX and self.pieces_per_unit is None:
            raise DomainInvariantError(
                "template_box_pieces_required",
                "Ein Box-Angebot benötigt eine nachvollziehbare Stückzahl.",
            )
        if self.unit_price_minor < 0:
            raise DomainInvariantError(
                "template_offering_price_negative",
                "Der Angebotspreis darf nicht negativ sein.",
            )
        if (
            len(self.currency) != 3
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
        ):
            raise DomainInvariantError(
                "template_offering_currency_invalid",
                "Die Angebotswährung muss aus drei Großbuchstaben bestehen.",
            )

    def payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "name": self.name,
            "status": self.status.value,
            "unit": self.unit.value,
            "piecesPerUnit": self.pieces_per_unit,
            "unitPriceMinor": self.unit_price_minor,
            "currency": self.currency,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TemplateOffering:
        return cls(
            code=str(payload["code"]),
            name=str(payload["name"]),
            status=OfferingStatus(str(payload["status"])),
            unit=OfferingUnit(str(payload["unit"])),
            pieces_per_unit=(
                int(payload["piecesPerUnit"])
                if payload.get("piecesPerUnit") is not None
                else None
            ),
            unit_price_minor=int(payload["unitPriceMinor"]),
            currency=str(payload["currency"]),
        )


@dataclass(frozen=True, slots=True)
class OrderFormConfiguration:
    form_key: str
    title: str
    introduction: str
    submit_label: str
    require_company_name: bool
    require_contact_name: bool
    require_email: bool
    require_phone: bool
    require_delivery_address: bool
    require_billing_address: bool
    allow_message: bool

    def __post_init__(self) -> None:
        if not SLUG.fullmatch(self.form_key):
            raise DomainInvariantError(
                "template_form_key_invalid",
                "Der Formularschlüssel muss ein URL-tauglicher Slug sein.",
            )
        for value, code, label in (
            (self.title, "template_form_title_empty", "Formulartitel"),
            (
                self.introduction,
                "template_form_introduction_empty",
                "Formulareinleitung",
            ),
            (
                self.submit_label,
                "template_form_submit_label_empty",
                "Formularaktion",
            ),
        ):
            if not value.strip():
                raise DomainInvariantError(code, f"{label} darf nicht leer sein.")
        if not self.require_contact_name or not self.require_email:
            raise DomainInvariantError(
                "template_form_contact_incomplete",
                "Ein öffentliches Bestellformular benötigt Name und E-Mail.",
            )

    def payload(self) -> dict[str, object]:
        return {
            "formKey": self.form_key,
            "title": self.title,
            "introduction": self.introduction,
            "submitLabel": self.submit_label,
            "requireCompanyName": self.require_company_name,
            "requireContactName": self.require_contact_name,
            "requireEmail": self.require_email,
            "requirePhone": self.require_phone,
            "requireDeliveryAddress": self.require_delivery_address,
            "requireBillingAddress": self.require_billing_address,
            "allowMessage": self.allow_message,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> OrderFormConfiguration:
        return cls(
            form_key=str(payload["formKey"]),
            title=str(payload["title"]),
            introduction=str(payload["introduction"]),
            submit_label=str(payload["submitLabel"]),
            require_company_name=bool(payload["requireCompanyName"]),
            require_contact_name=bool(payload["requireContactName"]),
            require_email=bool(payload["requireEmail"]),
            require_phone=bool(payload["requirePhone"]),
            require_delivery_address=bool(payload["requireDeliveryAddress"]),
            require_billing_address=bool(payload["requireBillingAddress"]),
            allow_message=bool(payload["allowMessage"]),
        )


@dataclass(frozen=True, slots=True)
class ConfiguredOffering:
    id: UUID
    action_id: UUID
    definition: TemplateOffering
    allowed_quantity_units: frozenset[OfferingUnit]
    available_from: datetime | None
    available_until: datetime | None

    def __post_init__(self) -> None:
        if (
            not self.allowed_quantity_units
            or self.definition.unit not in self.allowed_quantity_units
        ):
            raise DomainInvariantError(
                "configured_offering_units_invalid",
                "Die Preiseinheit muss als erlaubte Mengeneinheit enthalten sein.",
            )
        if (self.available_from is None) != (self.available_until is None):
            raise DomainInvariantError(
                "configured_offering_period_incomplete",
                "Der Angebotszeitraum benötigt Beginn und Ende.",
            )
        if self.available_from is not None and self.available_until is not None:
            if (
                self.available_from.utcoffset() is None
                or self.available_until.utcoffset() is None
            ):
                raise DomainInvariantError(
                    "configured_offering_timezone_required",
                    "Der Angebotszeitraum benötigt eine eindeutige Zeitzone.",
                )
            if self.available_from >= self.available_until:
                raise DomainInvariantError(
                    "configured_offering_period_invalid",
                    "Der Angebotsbeginn muss vor dem Angebotsende liegen.",
                )

    def available_at(self, moment: datetime) -> bool:
        if self.definition.status is not OfferingStatus.ACTIVE:
            return False
        if moment.utcoffset() is None:
            raise DomainInvariantError(
                "configured_offering_evaluation_timezone_required",
                "Die Angebotsprüfung benötigt eine eindeutige Zeitzone.",
            )
        return (
            self.available_from is None
            or self.available_until is None
            or self.available_from <= moment < self.available_until
        )


@dataclass(frozen=True, slots=True)
class ConfiguredOrderForm:
    id: UUID
    action_id: UUID
    configuration: OrderFormConfiguration
    status: OfferingStatus = OfferingStatus.DRAFT


@dataclass(frozen=True, slots=True)
class ActionTemplateSnapshot:
    template_key: ActionTemplateKey
    template_version: int
    display_name: str
    capabilities: frozenset[ActionCapability]
    offerings: tuple[TemplateOffering, ...]
    order_form: OrderFormConfiguration | None
    copied_from_action_id: UUID | None = None

    def __post_init__(self) -> None:
        _validate_configuration(
            self.capabilities,
            self.offerings,
            self.order_form,
        )
        if self.template_version <= 0:
            raise DomainInvariantError(
                "template_version_invalid",
                "Die Template-Version muss positiv sein.",
            )
        if not self.display_name.strip():
            raise DomainInvariantError(
                "template_display_name_empty",
                "Der Template-Name darf nicht leer sein.",
            )

    def payload(self) -> dict[str, object]:
        return {
            "capabilities": sorted(item.value for item in self.capabilities),
            "offerings": [item.payload() for item in self.offerings],
            "orderForm": (
                self.order_form.payload() if self.order_form is not None else None
            ),
        }

    @classmethod
    def from_payload(
        cls,
        *,
        template_key: str,
        template_version: int,
        display_name: str,
        copied_from_action_id: UUID | None,
        payload: dict[str, Any],
    ) -> ActionTemplateSnapshot:
        raw_offerings = payload.get("offerings", [])
        raw_form = payload.get("orderForm")
        return cls(
            template_key=ActionTemplateKey(template_key),
            template_version=template_version,
            display_name=display_name,
            capabilities=frozenset(
                ActionCapability(str(item)) for item in payload.get("capabilities", [])
            ),
            offerings=tuple(
                TemplateOffering.from_payload(item)
                for item in raw_offerings
                if isinstance(item, dict)
            ),
            order_form=(
                OrderFormConfiguration.from_payload(raw_form)
                if isinstance(raw_form, dict)
                else None
            ),
            copied_from_action_id=copied_from_action_id,
        )


@dataclass(frozen=True, slots=True)
class ActionConfiguration:
    action_id: UUID
    snapshot: ActionTemplateSnapshot
    offerings: tuple[ConfiguredOffering, ...]
    order_form: ConfiguredOrderForm | None

    def __post_init__(self) -> None:
        if any(item.action_id != self.action_id for item in self.offerings):
            raise DomainInvariantError(
                "configured_offering_action_mismatch",
                "Alle Angebote müssen zur konfigurierten Aktion gehören.",
            )
        if self.order_form is not None and self.order_form.action_id != self.action_id:
            raise DomainInvariantError(
                "configured_form_action_mismatch",
                "Das Bestellformular muss zur konfigurierten Aktion gehören.",
            )

    def require_compatible_capabilities(
        self,
        capabilities: frozenset[ActionCapability],
    ) -> None:
        _validate_configuration(
            capabilities,
            tuple(item.definition for item in self.offerings),
            (self.order_form.configuration if self.order_form is not None else None),
        )

    def copy_for(
        self,
        action_id: UUID,
        *,
        source_action_id: UUID,
        capabilities: frozenset[ActionCapability],
    ) -> ActionConfiguration:
        offerings = tuple(
            ConfiguredOffering(
                id=uuid4(),
                action_id=action_id,
                definition=item.definition,
                allowed_quantity_units=item.allowed_quantity_units,
                available_from=None,
                available_until=None,
            )
            for item in self.offerings
        )
        order_form = (
            ConfiguredOrderForm(
                id=uuid4(),
                action_id=action_id,
                configuration=self.order_form.configuration,
                status=OfferingStatus.DRAFT,
            )
            if self.order_form is not None
            else None
        )
        effective_offerings = tuple(item.definition for item in offerings)
        snapshot = ActionTemplateSnapshot(
            template_key=self.snapshot.template_key,
            template_version=self.snapshot.template_version,
            display_name=self.snapshot.display_name,
            capabilities=capabilities,
            offerings=effective_offerings,
            order_form=(order_form.configuration if order_form is not None else None),
            copied_from_action_id=source_action_id,
        )
        _validate_configuration(capabilities, effective_offerings, snapshot.order_form)
        return ActionConfiguration(
            action_id=action_id,
            snapshot=snapshot,
            offerings=offerings,
            order_form=order_form,
        )


@dataclass(frozen=True, slots=True)
class ActionTemplate:
    key: ActionTemplateKey
    version: int
    display_name: str
    description: str
    capabilities: frozenset[ActionCapability]
    offerings: tuple[TemplateOffering, ...]
    order_form: OrderFormConfiguration | None

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise DomainInvariantError(
                "template_version_invalid",
                "Die Template-Version muss positiv sein.",
            )
        if not self.display_name.strip() or not self.description.strip():
            raise DomainInvariantError(
                "template_text_empty",
                "Template-Name und Beschreibung dürfen nicht leer sein.",
            )
        _validate_configuration(
            self.capabilities,
            self.offerings,
            self.order_form,
        )

    def configure(
        self,
        action_id: UUID,
        *,
        capabilities: frozenset[ActionCapability] | None = None,
    ) -> ActionConfiguration:
        effective_capabilities = (
            capabilities if capabilities is not None else self.capabilities
        )
        effective_offerings = self.offerings if capabilities is None else ()
        effective_form = self.order_form if capabilities is None else None
        _validate_configuration(
            effective_capabilities,
            effective_offerings,
            effective_form,
        )
        snapshot = ActionTemplateSnapshot(
            template_key=self.key,
            template_version=self.version,
            display_name=self.display_name,
            capabilities=effective_capabilities,
            offerings=effective_offerings,
            order_form=effective_form,
        )
        return ActionConfiguration(
            action_id=action_id,
            snapshot=snapshot,
            offerings=tuple(
                ConfiguredOffering(
                    id=uuid4(),
                    action_id=action_id,
                    definition=item,
                    allowed_quantity_units=frozenset({item.unit}),
                    available_from=None,
                    available_until=None,
                )
                for item in effective_offerings
            ),
            order_form=(
                ConfiguredOrderForm(
                    id=uuid4(),
                    action_id=action_id,
                    configuration=effective_form,
                )
                if effective_form is not None
                else None
            ),
        )


def _validate_configuration(
    capabilities: frozenset[ActionCapability],
    offerings: tuple[TemplateOffering, ...],
    order_form: OrderFormConfiguration | None,
) -> None:
    codes = [item.code for item in offerings]
    if len(codes) != len(set(codes)):
        raise DomainInvariantError(
            "template_offering_duplicate",
            "Angebotsschlüssel dürfen nicht doppelt vorkommen.",
        )
    if offerings and ActionCapability.OFFERINGS not in capabilities:
        raise DomainInvariantError(
            "template_offerings_capability_missing",
            "Standardangebote benötigen die Capability Angebote.",
        )
    if (
        ActionCapability.ORDERING in capabilities
        and ActionCapability.OFFERINGS not in capabilities
    ):
        raise DomainInvariantError(
            "action_capability_dependency_invalid",
            "Bestellungen benötigen die Capability Angebote.",
        )
    if order_form is not None and ActionCapability.ORDERING not in capabilities:
        raise DomainInvariantError(
            "template_ordering_capability_missing",
            "Ein Bestellformular benötigt die Capability Bestellungen.",
        )
