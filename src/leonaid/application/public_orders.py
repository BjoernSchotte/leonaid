"""Public order orchestration across publication, CRM and transactional Core data."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5

from leonaid.application.commitments import CommitmentLineDraft
from leonaid.application.crm import (
    CompanyData,
    CompanyRecord,
    CrmGateway,
    CrmPartyKind,
    PersonData,
    PersonRecord,
    PostalAddress,
)
from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.application.sponsor_matching import (
    candidate_company_query,
    company_matches,
    normalize_match_name,
    person_matches,
)
from leonaid.domain.action_templates import OrderFormConfiguration
from leonaid.domain.actions import PublicActionAlias
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentPartyKind,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.errors import DomainInvariantError

PUBLIC_ORDER_NAMESPACE = UUID("98694fa6-c472-4288-8cce-bc94d052a8a8")
PRIVACY_NOTICE_VERSION = "public-order-poc-2026-07"
TOKEN_VERSION = 1
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
PHONE = re.compile(r"^\+[1-9][0-9]{5,14}$")


def _text(
    value: str | None,
    *,
    label: str,
    maximum: int,
    required: bool,
) -> str | None:
    if value is None:
        if required:
            raise DomainInvariantError(
                f"public_order_{label}_required",
                f"{label.replace('_', ' ').capitalize()} fehlt.",
            )
        return None
    normalized = " ".join(value.split())
    if required and not normalized:
        raise DomainInvariantError(
            f"public_order_{label}_required",
            f"{label.replace('_', ' ').capitalize()} fehlt.",
        )
    if len(normalized) > maximum:
        raise DomainInvariantError(
            f"public_order_{label}_too_long",
            f"{label.replace('_', ' ').capitalize()} ist zu lang.",
        )
    return normalized or None


def _phone(value: str | None) -> str | None:
    normalized = _text(
        value,
        label="phone",
        maximum=40,
        required=False,
    )
    if normalized is None:
        return None
    canonical = re.sub(r"[\s()./-]", "", normalized)
    if canonical.startswith("00"):
        canonical = f"+{canonical[2:]}"
    elif canonical.startswith("0"):
        canonical = f"+49{canonical[1:]}"
    if not PHONE.fullmatch(canonical):
        raise DomainInvariantError(
            "public_order_phone_invalid",
            "Bitte gib eine gültige Telefonnummer ein, zum Beispiel +49 821 123456.",
        )
    return canonical


@dataclass(frozen=True, slots=True)
class PublicOrderPartyDraft:
    company_name: str | None
    given_name: str
    family_name: str
    email: str
    phone: str | None = None

    def __post_init__(self) -> None:
        company_name = _text(
            self.company_name,
            label="company_name",
            maximum=300,
            required=False,
        )
        given_name = _text(
            self.given_name,
            label="given_name",
            maximum=200,
            required=True,
        )
        family_name = _text(
            self.family_name,
            label="family_name",
            maximum=200,
            required=True,
        )
        email = _text(
            self.email,
            label="email",
            maximum=320,
            required=True,
        )
        phone = _phone(self.phone)
        assert given_name is not None
        assert family_name is not None
        assert email is not None
        email = email.casefold()
        if not EMAIL.fullmatch(email):
            raise DomainInvariantError(
                "public_order_email_invalid",
                "Bitte gib eine gültige E-Mail-Adresse ein.",
            )
        object.__setattr__(self, "company_name", company_name)
        object.__setattr__(self, "given_name", given_name)
        object.__setattr__(self, "family_name", family_name)
        object.__setattr__(self, "email", email)
        object.__setattr__(self, "phone", phone)

    @property
    def party_kind(self) -> CrmPartyKind:
        return (
            CrmPartyKind.COMPANY
            if self.company_name is not None
            else CrmPartyKind.PERSON
        )

    @property
    def normalized_key(self) -> str:
        if self.company_name is not None:
            return normalize_match_name(self.company_name)
        return normalize_match_name(f"{self.given_name} {self.family_name}")

    def payload(self) -> dict[str, object]:
        return {
            "companyName": self.company_name,
            "givenName": self.given_name,
            "familyName": self.family_name,
            "email": self.email,
            "phone": self.phone,
        }


@dataclass(frozen=True, slots=True)
class PublicOrderDraft:
    party: PublicOrderPartyDraft
    delivery_recipient: DeliveryRecipientSnapshot
    invoice_recipient: InvoiceRecipientSnapshot
    lines: tuple[CommitmentLineDraft, ...]
    message: str | None
    privacy_acknowledged: bool
    binding_order_confirmed: bool
    privacy_notice_version: str
    website: str | None = None

    def __post_init__(self) -> None:
        if not self.lines:
            raise DomainInvariantError(
                "public_order_lines_required",
                "Wähle mindestens ein Angebot aus.",
            )
        offering_ids = tuple(line.offering_id for line in self.lines)
        if len(offering_ids) != len(set(offering_ids)):
            raise DomainInvariantError(
                "public_order_offering_duplicate",
                "Ein Angebot darf nur einmal bestellt werden.",
            )
        if any(line.quoted_unit_price_minor is None for line in self.lines):
            raise DomainInvariantError(
                "public_order_quote_required",
                "Der angezeigte Preis fehlt. Lade die Seite neu.",
            )
        message = _text(
            self.message,
            label="message",
            maximum=1000,
            required=False,
        )
        website = _text(
            self.website,
            label="website",
            maximum=300,
            required=False,
        )
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "website", website)
        if not self.privacy_acknowledged:
            raise DomainInvariantError(
                "public_order_privacy_required",
                "Bestätige die Hinweise zur Verarbeitung deiner Bestelldaten.",
            )
        if not self.binding_order_confirmed:
            raise DomainInvariantError(
                "public_order_confirmation_required",
                "Bestätige, dass du die Bestellung verbindlich absenden möchtest.",
            )
        if self.privacy_notice_version != PRIVACY_NOTICE_VERSION:
            raise Conflict(
                "public_order_privacy_notice_changed",
                "Die Datenschutzhinweise wurden aktualisiert. Lade die Seite neu.",
            )

    def request_hash(self, *, action_id: UUID, public_alias: str) -> str:
        payload = {
            "actionId": str(action_id),
            "publicAlias": public_alias,
            "party": self.party.payload(),
            "deliveryRecipient": self.delivery_recipient.payload(),
            "invoiceRecipient": self.invoice_recipient.payload(),
            "lines": [
                {
                    "offeringId": str(line.offering_id),
                    "quantity": line.quantity,
                    "unit": line.unit.value,
                    "quotedUnitPriceMinor": line.quoted_unit_price_minor,
                }
                for line in self.lines
            ],
            "message": self.message,
            "privacyAcknowledged": self.privacy_acknowledged,
            "bindingOrderConfirmed": self.binding_order_confirmed,
            "privacyNoticeVersion": self.privacy_notice_version,
            "website": self.website,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicFormClaims:
    action_id: UUID
    public_alias: str
    issued_at: datetime
    expires_at: datetime


class PublicOrderTokenCodec:
    def __init__(self, secret: str, *, ttl: timedelta = timedelta(hours=2)) -> None:
        if len(secret) < 32:
            raise ValueError(
                "Public-Formular-Secret muss mindestens 32 Zeichen lang sein."
            )
        if ttl <= timedelta(minutes=5):
            raise ValueError(
                "Public-Formular-Token muss länger als fünf Minuten gelten."
            )
        self._secret = secret.encode("utf-8")
        self._ttl = ttl

    def issue(
        self,
        action_id: UUID,
        public_alias: str,
        *,
        issued_at: datetime | None = None,
    ) -> str:
        alias = PublicActionAlias(public_alias.strip()).value
        moment = issued_at or datetime.now(timezone.utc)
        if moment.utcoffset() is None:
            raise ValueError("Token-Zeitpunkt benötigt eine Zeitzone.")
        payload = json.dumps(
            {
                "actionId": str(action_id),
                "alias": alias,
                "issuedAt": int(moment.timestamp()),
                "expiresAt": int((moment + self._ttl).timestamp()),
                "version": TOKEN_VERSION,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = self._encode(payload)
        signature = self._encode(
            hmac.new(
                self._secret,
                b"leonaid-public-order:" + encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"{encoded}.{signature}"

    def verify(
        self,
        token: str,
        *,
        expected_alias: str,
        evaluated_at: datetime | None = None,
    ) -> PublicFormClaims:
        moment = evaluated_at or datetime.now(timezone.utc)
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected_signature = self._encode(
                hmac.new(
                    self._secret,
                    b"leonaid-public-order:" + encoded.encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise ValueError("signature")
            payload = json.loads(self._decode(encoded))
            if not isinstance(payload, dict) or payload.get("version") != TOKEN_VERSION:
                raise ValueError("payload")
            action_id = UUID(str(payload["actionId"]))
            alias = PublicActionAlias(str(payload["alias"])).value
            issued_at = datetime.fromtimestamp(
                int(payload["issuedAt"]),
                tz=timezone.utc,
            )
            expires_at = datetime.fromtimestamp(
                int(payload["expiresAt"]),
                tz=timezone.utc,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise PermissionDenied(
                "public_order_token_invalid",
                "Das Bestellformular ist nicht mehr gültig. Lade die Seite neu.",
            ) from error
        if (
            moment.utcoffset() is None
            or alias != PublicActionAlias(expected_alias.strip()).value
            or issued_at > moment + timedelta(minutes=1)
            or expires_at <= moment
            or expires_at - issued_at != self._ttl
        ):
            raise PermissionDenied(
                "public_order_token_invalid",
                "Das Bestellformular ist nicht mehr gültig. Lade die Seite neu.",
            )
        return PublicFormClaims(
            action_id=action_id,
            public_alias=alias,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)


def public_order_fingerprint(
    secret: str,
    *,
    forwarded_for: str | None,
    client_host: str | None,
    user_agent: str | None,
) -> str:
    forwarded = [
        item.strip() for item in (forwarded_for or "").split(",") if item.strip()
    ]
    address = forwarded[-1] if forwarded else (client_host or "unknown")
    material = f"{address[:128]}|{(user_agent or 'unknown')[:320]}".encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"),
        b"leonaid-public-rate:" + material,
        hashlib.sha256,
    ).hexdigest()


class PublicOrderCrmOutcome(StrEnum):
    CREATED = "created"
    REUSED = "reused"


@dataclass(frozen=True, slots=True)
class ResolvedPublicParty:
    buyer: BuyerSnapshot
    contact_twenty_id: UUID | None
    outcome: PublicOrderCrmOutcome


@dataclass(frozen=True, slots=True)
class PublicOrderContext:
    action_id: UUID
    action_name: str
    order_form: OrderFormConfiguration


@dataclass(frozen=True, slots=True)
class PublicOrderResult:
    commitment: Commitment
    crm_outcome: PublicOrderCrmOutcome
    contact_twenty_id: UUID | None
    activity_recipient_ids: tuple[UUID, ...]
    replayed: bool


class PublicOrderCommand(Protocol):
    @property
    def existing_result(self) -> PublicOrderResult | None: ...

    async def context(
        self,
        *,
        action_id: UUID,
        public_alias: str,
        evaluated_at: datetime,
    ) -> PublicOrderContext: ...

    async def record_order(
        self,
        *,
        action_id: UUID,
        public_alias: str,
        party: ResolvedPublicParty,
        draft: PublicOrderDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PublicOrderResult: ...

    async def complete(self, result: PublicOrderResult) -> None: ...


class PublicOrderRepository(Protocol):
    def order_command(
        self,
        *,
        lock_key: str,
        idempotency_key: str,
        request_hash: str,
    ) -> AbstractAsyncContextManager[PublicOrderCommand]: ...

    async def admit_submission(
        self,
        *,
        action_id: UUID,
        idempotency_key: str,
        fingerprint_hash: str,
        attempted_at: datetime,
    ) -> None: ...


class PublicOrderService:
    def __init__(
        self,
        repository: PublicOrderRepository,
        crm: CrmGateway,
        token_codec: PublicOrderTokenCodec,
    ) -> None:
        self._repository = repository
        self._crm = crm
        self._token_codec = token_codec

    def issue_access_token(
        self,
        action_id: UUID,
        public_alias: str,
        *,
        issued_at: datetime | None = None,
    ) -> str:
        return self._token_codec.issue(
            action_id,
            public_alias,
            issued_at=issued_at,
        )

    async def submit(
        self,
        public_alias: str,
        *,
        access_token: str,
        command_id: UUID,
        draft: PublicOrderDraft,
        fingerprint_hash: str,
        request_id: str,
        evaluated_at: datetime | None = None,
    ) -> PublicOrderResult:
        moment = evaluated_at or datetime.now(timezone.utc)
        claims = self._token_codec.verify(
            access_token,
            expected_alias=public_alias,
            evaluated_at=moment,
        )
        idempotency_key = f"public.order:{claims.action_id}:{command_id}"
        if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise DomainInvariantError(
                "public_order_idempotency_invalid",
                "Die Vorgangs-ID ist ungültig. Lade die Seite neu.",
            )
        request_hash = draft.request_hash(
            action_id=claims.action_id,
            public_alias=claims.public_alias,
        )
        lock_key = (
            f"public.order.party:{claims.action_id}:"
            f"{draft.party.party_kind.value}:{draft.party.normalized_key}"
        )
        async with self._repository.order_command(
            lock_key=lock_key,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        ) as command:
            if command.existing_result is not None:
                return command.existing_result
            context = await command.context(
                action_id=claims.action_id,
                public_alias=claims.public_alias,
                evaluated_at=moment,
            )
            await self._repository.admit_submission(
                action_id=claims.action_id,
                idempotency_key=idempotency_key,
                fingerprint_hash=fingerprint_hash,
                attempted_at=moment,
            )
            if draft.website is not None:
                raise Conflict(
                    "public_order_rejected",
                    "Die Bestellung konnte nicht verarbeitet werden. Lade die Seite neu.",
                )
            self._require_form_fields(context.order_form, draft)
            party = await self._resolve_party(
                draft.party,
                delivery=draft.delivery_recipient,
                idempotency_key=idempotency_key,
                request_id=request_id,
            )
            result = await command.record_order(
                action_id=claims.action_id,
                public_alias=claims.public_alias,
                party=party,
                draft=draft,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                request_id=request_id,
                occurred_at=moment,
            )
            await command.complete(result)
            return result

    @staticmethod
    def _require_form_fields(
        form: OrderFormConfiguration,
        draft: PublicOrderDraft,
    ) -> None:
        if form.require_company_name and draft.party.company_name is None:
            raise DomainInvariantError(
                "public_order_company_required",
                "Für diese Aktion ist ein Firmenname erforderlich.",
            )
        if form.require_phone and draft.party.phone is None:
            raise DomainInvariantError(
                "public_order_phone_required",
                "Für diese Aktion ist eine Telefonnummer erforderlich.",
            )
        if not form.allow_message and draft.message is not None:
            raise DomainInvariantError(
                "public_order_message_forbidden",
                "Für dieses Formular ist keine Nachricht vorgesehen.",
            )

    async def _resolve_party(
        self,
        draft: PublicOrderPartyDraft,
        *,
        delivery: DeliveryRecipientSnapshot,
        idempotency_key: str,
        request_id: str,
    ) -> ResolvedPublicParty:
        primary_id = uuid5(PUBLIC_ORDER_NAMESPACE, f"{idempotency_key}:primary")
        contact_id = uuid5(PUBLIC_ORDER_NAMESPACE, f"{idempotency_key}:contact")
        if draft.party_kind is CrmPartyKind.COMPANY:
            return await self._resolve_company(
                draft,
                delivery=delivery,
                primary_id=primary_id,
                contact_id=contact_id,
                request_id=request_id,
            )
        return await self._resolve_person(
            draft,
            primary_id=primary_id,
            request_id=request_id,
        )

    async def _resolve_company(
        self,
        draft: PublicOrderPartyDraft,
        *,
        delivery: DeliveryRecipientSnapshot,
        primary_id: UUID,
        contact_id: UUID,
        request_id: str,
    ) -> ResolvedPublicParty:
        assert draft.company_name is not None
        direct = await self._crm.search_companies(
            candidate_company_query(draft.company_name),
            correlation_id=f"{request_id}:company-search",
        )
        matches = company_matches(direct, draft.normalized_key)
        if not matches:
            matches = company_matches(
                await self._crm.list_companies(
                    correlation_id=f"{request_id}:company-fallback",
                ),
                draft.normalized_key,
            )
        if len(matches) > 1:
            raise Conflict(
                "public_order_party_ambiguous",
                "Die Firma ist mehrfach vorhanden. Bitte wende dich an den Veranstalter.",
            )
        outcome = PublicOrderCrmOutcome.REUSED
        company: CompanyRecord
        if matches:
            company = matches[0]
        else:
            recovered = await self._crm.get_company(
                primary_id,
                correlation_id=f"{request_id}:company-recover",
            )
            if recovered is not None:
                if normalize_match_name(recovered.data.name) != draft.normalized_key:
                    raise Conflict(
                        "public_order_party_recovery_conflict",
                        "Die Bestellung kann nicht sicher fortgesetzt werden.",
                    )
                company = recovered
            else:
                company, _receipt = await self._crm.create_company(
                    primary_id,
                    CompanyData(
                        name=draft.company_name,
                        address=PostalAddress(
                            street_line_1=delivery.street_line_1,
                            postal_code=delivery.postal_code,
                            city=delivery.city,
                            country=delivery.country_code,
                        ),
                    ),
                    correlation_id=f"{request_id}:company-create",
                )
            outcome = PublicOrderCrmOutcome.CREATED
        contact_id_value = await self._resolve_company_contact(
            draft,
            company_id=company.twenty_id,
            deterministic_id=contact_id,
            request_id=request_id,
        )
        return ResolvedPublicParty(
            buyer=BuyerSnapshot(
                party_kind=CommitmentPartyKind.COMPANY,
                twenty_id=company.twenty_id,
                display_name=company.data.name,
                email=draft.email,
            ),
            contact_twenty_id=contact_id_value,
            outcome=outcome,
        )

    async def _resolve_company_contact(
        self,
        draft: PublicOrderPartyDraft,
        *,
        company_id: UUID,
        deterministic_id: UUID,
        request_id: str,
    ) -> UUID:
        records = await self._crm.search_people(
            given_name=draft.given_name,
            family_name=draft.family_name,
            correlation_id=f"{request_id}:contact-search",
        )
        matches = tuple(
            record
            for record in person_matches(
                records, normalize_match_name(f"{draft.given_name} {draft.family_name}")
            )
            if record.data.company_twenty_id == company_id
        )
        if len(matches) > 1:
            email_matches = tuple(
                record for record in matches if record.data.email == draft.email
            )
            if len(email_matches) == 1:
                return email_matches[0].twenty_id
            raise Conflict(
                "public_order_contact_ambiguous",
                "Der Kontakt ist mehrfach vorhanden. Bitte wende dich an den Veranstalter.",
            )
        if matches:
            return matches[0].twenty_id
        recovered = await self._crm.get_person(
            deterministic_id,
            correlation_id=f"{request_id}:contact-recover",
        )
        if recovered is not None:
            if recovered.data.company_twenty_id != company_id or normalize_match_name(
                f"{recovered.data.given_name} {recovered.data.family_name}"
            ) != normalize_match_name(f"{draft.given_name} {draft.family_name}"):
                raise Conflict(
                    "public_order_contact_recovery_conflict",
                    "Die Bestellung kann nicht sicher fortgesetzt werden.",
                )
            return recovered.twenty_id
        person, _receipt = await self._crm.create_person(
            deterministic_id,
            PersonData(
                given_name=draft.given_name,
                family_name=draft.family_name,
                email=draft.email,
                phone=draft.phone,
                company_twenty_id=company_id,
            ),
            correlation_id=f"{request_id}:contact-create",
        )
        return person.twenty_id

    async def _resolve_person(
        self,
        draft: PublicOrderPartyDraft,
        *,
        primary_id: UUID,
        request_id: str,
    ) -> ResolvedPublicParty:
        direct = await self._crm.search_people(
            given_name=draft.given_name,
            family_name=draft.family_name,
            correlation_id=f"{request_id}:person-search",
        )
        matches = tuple(
            record
            for record in person_matches(direct, draft.normalized_key)
            if record.data.company_twenty_id is None
        )
        if not matches:
            matches = tuple(
                record
                for record in person_matches(
                    await self._crm.list_people(
                        correlation_id=f"{request_id}:person-fallback",
                    ),
                    draft.normalized_key,
                )
                if record.data.company_twenty_id is None
            )
        if len(matches) > 1:
            email_matches = tuple(
                record for record in matches if record.data.email == draft.email
            )
            if len(email_matches) == 1:
                matches = email_matches
            else:
                raise Conflict(
                    "public_order_party_ambiguous",
                    "Der Kontakt ist mehrfach vorhanden. Bitte wende dich an den Veranstalter.",
                )
        outcome = PublicOrderCrmOutcome.REUSED
        person: PersonRecord
        if matches:
            person = matches[0]
        else:
            recovered = await self._crm.get_person(
                primary_id,
                correlation_id=f"{request_id}:person-recover",
            )
            if recovered is not None:
                if (
                    recovered.data.company_twenty_id is not None
                    or normalize_match_name(
                        f"{recovered.data.given_name} {recovered.data.family_name}"
                    )
                    != draft.normalized_key
                ):
                    raise Conflict(
                        "public_order_party_recovery_conflict",
                        "Die Bestellung kann nicht sicher fortgesetzt werden.",
                    )
                person = recovered
            else:
                person, _receipt = await self._crm.create_person(
                    primary_id,
                    PersonData(
                        given_name=draft.given_name,
                        family_name=draft.family_name,
                        email=draft.email,
                        phone=draft.phone,
                    ),
                    correlation_id=f"{request_id}:person-create",
                )
            outcome = PublicOrderCrmOutcome.CREATED
        return ResolvedPublicParty(
            buyer=BuyerSnapshot(
                party_kind=CommitmentPartyKind.PERSON,
                twenty_id=person.twenty_id,
                display_name=(
                    f"{person.data.given_name} {person.data.family_name}".strip()
                ),
                email=draft.email,
            ),
            contact_twenty_id=person.twenty_id,
            outcome=outcome,
        )
