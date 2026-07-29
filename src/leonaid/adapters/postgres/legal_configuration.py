"""PostgreSQL persistence for immutable legal configuration versions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.domain.invoices import InvoiceIssuerSnapshot, TaxTreatment
from leonaid.domain.legal_configuration import (
    EInvoiceDecision,
    LegalConfigurationApproval,
    LegalConfigurationDraft,
    LegalConfigurationState,
    LegalConfigurationVersion,
    RetentionSchedule,
)

SINGLETON_ID = UUID("00000000-0000-4000-8000-000000000044")


class AsyncpgLegalConfigurationRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def state(self) -> LegalConfigurationState:
        async with self._pool.acquire() as connection:
            return await self._state(connection)

    async def active_configuration(self) -> LegalConfigurationVersion | None:
        async with self._pool.acquire() as connection:
            version_id = await connection.fetchval(
                """
                SELECT active_version_id
                FROM legal_configuration_state
                WHERE id = $1
                """,
                SINGLETON_ID,
            )
            return await self._version(connection, version_id)

    async def save_draft(
        self,
        *,
        configuration: LegalConfigurationDraft,
        actor_user_id: UUID,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime,
    ) -> LegalConfigurationState:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                state = await self._locked_state(connection)
                self._require_revision(state, expected_revision)
                version = int(
                    await connection.fetchval(
                        "SELECT COALESCE(MAX(version), 0) + 1 "
                        "FROM legal_configuration_version"
                    )
                )
                version_id = uuid4()
                await connection.execute(
                    """
                    INSERT INTO legal_configuration_version (
                        id, version, legal_name, street_line_1, postal_code,
                        city, country_code, tax_identifier, issuer_email,
                        bank_account_holder, iban, bic, tax_treatment,
                        tax_rate_basis_points, tax_note, number_prefix,
                        number_width, payment_terms_days,
                        public_order_legal_basis, public_order_notice_text,
                        consent_text_version, privacy_contact_email,
                        invoice_retention_days, commitment_retention_days,
                        contact_retention_days, consent_evidence_retention_days,
                        audit_retention_days, e_invoice_decision,
                        tax_evidence_id, privacy_evidence_id,
                        e_invoice_evidence_id, created_by_user_id, created_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                        $13, $14, $15, $16, $17, $18, $19, $20, $21, $22,
                        $23, $24, $25, $26, $27, $28, $29, $30, $31, $32, $33
                    )
                    """,
                    version_id,
                    version,
                    configuration.issuer.legal_name,
                    configuration.issuer.street_line_1,
                    configuration.issuer.postal_code,
                    configuration.issuer.city,
                    configuration.issuer.country_code,
                    configuration.issuer.tax_identifier,
                    configuration.issuer.email,
                    configuration.bank_account_holder,
                    configuration.iban,
                    configuration.bic,
                    configuration.tax_treatment.value,
                    configuration.tax_rate_basis_points,
                    configuration.tax_note,
                    configuration.number_prefix,
                    configuration.number_width,
                    configuration.payment_terms_days,
                    configuration.public_order_legal_basis,
                    configuration.public_order_notice_text,
                    configuration.consent_text_version,
                    configuration.privacy_contact_email,
                    configuration.retention.invoice_days,
                    configuration.retention.commitment_days,
                    configuration.retention.contact_days,
                    configuration.retention.consent_evidence_days,
                    configuration.retention.audit_days,
                    configuration.e_invoice_decision.value,
                    configuration.tax_evidence_id,
                    configuration.privacy_evidence_id,
                    configuration.e_invoice_evidence_id,
                    actor_user_id,
                    occurred_at,
                )
                revision = await self._update_state(
                    connection,
                    expected_revision=expected_revision,
                    actor_user_id=actor_user_id,
                    occurred_at=occurred_at,
                    draft_version_id=version_id,
                    activate=False,
                )
                await self._audit(
                    connection,
                    actor_user_id=actor_user_id,
                    entity_id=version_id,
                    event_type="legal_configuration_draft_saved",
                    request_id=request_id,
                    occurred_at=occurred_at,
                    payload={"version": version, "revision": revision},
                )
                return await self._state(connection)

    async def approve(
        self,
        *,
        version_id: UUID,
        actor_user_id: UUID,
        evidence_id: str,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime,
    ) -> LegalConfigurationState:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                state = await self._locked_state(connection)
                self._require_revision(state, expected_revision)
                if state.draft is None or state.draft.id != version_id:
                    raise ResourceNotFound(
                        "legal_configuration_draft_not_found",
                        "Der freizugebende Entwurf ist nicht mehr aktuell.",
                    )
                if state.draft.created_by_user_id == actor_user_id:
                    raise Conflict(
                        "legal_configuration_four_eyes_required",
                        "Der Ersteller kann den eigenen Entwurf nicht freigeben.",
                    )
                await connection.execute(
                    """
                    INSERT INTO legal_configuration_approval (
                        version_id, approved_by_user_id, evidence_id, approved_at
                    )
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (version_id) DO UPDATE
                    SET approved_by_user_id = EXCLUDED.approved_by_user_id,
                        evidence_id = EXCLUDED.evidence_id,
                        approved_at = EXCLUDED.approved_at
                    """,
                    version_id,
                    actor_user_id,
                    evidence_id,
                    occurred_at,
                )
                revision = await self._update_state(
                    connection,
                    expected_revision=expected_revision,
                    actor_user_id=actor_user_id,
                    occurred_at=occurred_at,
                    draft_version_id=version_id,
                    activate=False,
                )
                await self._audit(
                    connection,
                    actor_user_id=actor_user_id,
                    entity_id=version_id,
                    event_type="legal_configuration_approved",
                    request_id=request_id,
                    occurred_at=occurred_at,
                    payload={"revision": revision},
                )
                return await self._state(connection)

    async def activate(
        self,
        *,
        version_id: UUID,
        actor_user_id: UUID,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime,
    ) -> LegalConfigurationState:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                state = await self._locked_state(connection)
                self._require_revision(state, expected_revision)
                if (
                    state.draft is None
                    or state.draft.id != version_id
                    or state.draft_approval is None
                ):
                    raise Conflict(
                        "legal_configuration_activation_conflict",
                        "Entwurf oder Vier-Augen-Freigabe ist nicht mehr aktuell.",
                    )
                revision = await self._update_state(
                    connection,
                    expected_revision=expected_revision,
                    actor_user_id=actor_user_id,
                    occurred_at=occurred_at,
                    draft_version_id=version_id,
                    activate=True,
                )
                await self._audit(
                    connection,
                    actor_user_id=actor_user_id,
                    entity_id=version_id,
                    event_type="legal_configuration_activated",
                    request_id=request_id,
                    occurred_at=occurred_at,
                    payload={
                        "version": state.draft.version,
                        "revision": revision,
                    },
                )
                return await self._state(connection)

    async def _locked_state(
        self,
        connection: asyncpg.Connection[Any],
    ) -> LegalConfigurationState:
        await connection.fetchrow(
            "SELECT id FROM legal_configuration_state WHERE id = $1 FOR UPDATE",
            SINGLETON_ID,
        )
        return await self._state(connection)

    async def _state(
        self,
        connection: asyncpg.Connection[Any],
    ) -> LegalConfigurationState:
        row = await connection.fetchrow(
            """
            SELECT revision, draft_version_id, active_version_id
            FROM legal_configuration_state
            WHERE id = $1
            """,
            SINGLETON_ID,
        )
        if row is None:
            raise RuntimeError(
                "Die rechtliche Konfiguration wurde nicht initialisiert."
            )
        draft = await self._version(connection, row["draft_version_id"])
        active = await self._version(connection, row["active_version_id"])
        approval = (
            await self._approval(connection, draft.id) if draft is not None else None
        )
        return LegalConfigurationState(
            revision=int(row["revision"]),
            draft=draft,
            active=active,
            draft_approval=approval,
        )

    async def _version(
        self,
        connection: asyncpg.Connection[Any],
        version_id: UUID | None,
    ) -> LegalConfigurationVersion | None:
        if version_id is None:
            return None
        row = await connection.fetchrow(
            """
            SELECT version.*, creator.display_name AS created_by_display_name
            FROM legal_configuration_version AS version
            JOIN user_account AS creator
              ON creator.id = version.created_by_user_id
            WHERE version.id = $1
            """,
            version_id,
        )
        if row is None:
            raise RuntimeError("Eine referenzierte Konfigurationsversion fehlt.")
        configuration = LegalConfigurationDraft(
            issuer=InvoiceIssuerSnapshot(
                legal_name=str(row["legal_name"]),
                street_line_1=str(row["street_line_1"]),
                postal_code=str(row["postal_code"]),
                city=str(row["city"]),
                country_code=str(row["country_code"]),
                tax_identifier=str(row["tax_identifier"]),
                email=str(row["issuer_email"]),
            ),
            bank_account_holder=str(row["bank_account_holder"]),
            iban=str(row["iban"]),
            bic=str(row["bic"]) if row["bic"] is not None else None,
            tax_treatment=TaxTreatment(str(row["tax_treatment"])),
            tax_rate_basis_points=int(row["tax_rate_basis_points"]),
            tax_note=str(row["tax_note"]),
            number_prefix=str(row["number_prefix"]),
            number_width=int(row["number_width"]),
            payment_terms_days=int(row["payment_terms_days"]),
            public_order_legal_basis=str(row["public_order_legal_basis"]),
            public_order_notice_text=str(row["public_order_notice_text"]),
            consent_text_version=str(row["consent_text_version"]),
            privacy_contact_email=str(row["privacy_contact_email"]),
            retention=RetentionSchedule(
                invoice_days=int(row["invoice_retention_days"]),
                commitment_days=int(row["commitment_retention_days"]),
                contact_days=int(row["contact_retention_days"]),
                consent_evidence_days=int(row["consent_evidence_retention_days"]),
                audit_days=int(row["audit_retention_days"]),
            ),
            e_invoice_decision=EInvoiceDecision(str(row["e_invoice_decision"])),
            tax_evidence_id=str(row["tax_evidence_id"]),
            privacy_evidence_id=str(row["privacy_evidence_id"]),
            e_invoice_evidence_id=(
                str(row["e_invoice_evidence_id"])
                if row["e_invoice_evidence_id"] is not None
                else None
            ),
        )
        return LegalConfigurationVersion(
            id=row["id"],
            version=int(row["version"]),
            configuration=configuration,
            created_by_user_id=row["created_by_user_id"],
            created_by_display_name=str(row["created_by_display_name"]),
            created_at=row["created_at"],
        )

    async def _approval(
        self,
        connection: asyncpg.Connection[Any],
        version_id: UUID,
    ) -> LegalConfigurationApproval | None:
        row = await connection.fetchrow(
            """
            SELECT approval.*, approver.display_name AS approved_by_display_name
            FROM legal_configuration_approval AS approval
            JOIN user_account AS approver
              ON approver.id = approval.approved_by_user_id
            WHERE approval.version_id = $1
            """,
            version_id,
        )
        if row is None:
            return None
        return LegalConfigurationApproval(
            version_id=row["version_id"],
            approved_by_user_id=row["approved_by_user_id"],
            approved_by_display_name=str(row["approved_by_display_name"]),
            evidence_id=str(row["evidence_id"]),
            approved_at=row["approved_at"],
        )

    @staticmethod
    def _require_revision(
        state: LegalConfigurationState,
        expected_revision: int,
    ) -> None:
        if state.revision != expected_revision:
            raise Conflict(
                "legal_configuration_revision_conflict",
                "Die Konfiguration wurde zwischenzeitlich geändert. Lade sie neu.",
            )

    @staticmethod
    async def _update_state(
        connection: asyncpg.Connection[Any],
        *,
        expected_revision: int,
        actor_user_id: UUID,
        occurred_at: datetime,
        draft_version_id: UUID,
        activate: bool,
    ) -> int:
        if activate:
            row = await connection.fetchrow(
                """
                UPDATE legal_configuration_state
                SET revision = revision + 1,
                    draft_version_id = NULL,
                    active_version_id = $1,
                    updated_by_user_id = $2,
                    updated_at = $3
                WHERE id = $4 AND revision = $5
                RETURNING revision
                """,
                draft_version_id,
                actor_user_id,
                occurred_at,
                SINGLETON_ID,
                expected_revision,
            )
        else:
            row = await connection.fetchrow(
                """
                UPDATE legal_configuration_state
                SET revision = revision + 1,
                    draft_version_id = $1,
                    updated_by_user_id = $2,
                    updated_at = $3
                WHERE id = $4 AND revision = $5
                RETURNING revision
                """,
                draft_version_id,
                actor_user_id,
                occurred_at,
                SINGLETON_ID,
                expected_revision,
            )
        if row is None:
            raise Conflict(
                "legal_configuration_revision_conflict",
                "Die Konfiguration wurde zwischenzeitlich geändert. Lade sie neu.",
            )
        return int(row["revision"])

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        actor_user_id: UUID,
        entity_id: UUID,
        event_type: str,
        request_id: str,
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type,
                entity_type, entity_id, request_id, payload, occurred_at
            )
            VALUES ($1, NULL, $2, $3, 'legal_configuration', $4, $5, $6::jsonb, $7)
            """,
            uuid4(),
            actor_user_id,
            event_type,
            entity_id,
            request_id,
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )
