#!/usr/bin/env python3
"""Real PostgreSQL/FastAPI contract for legal configuration."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

SIMONE_ID = UUID("10000000-0000-4000-8000-000000000001")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
PROFILELESS_ACTION_ID = UUID("97530000-0000-4000-8000-000000000001")
SESSION_NAMESPACE = UUID("35cd44c4-6106-4f7f-84c9-ced1d57cb044")


PRIVACY_POLICY = (
    "## Verantwortlicher\n\n"
    "Verantwortlich ist der im Impressum genannte Golden-Förderverein. "
    "Dieser synthetische Text prüft die Datenschutzseite.\n\n"
    "## Ihre Rechte\n\n"
    "- Auskunft\n"
    "- Löschung\n\n"
    "Beschwerden richten Sie an eine Datenschutz-Aufsichtsbehörde."
)
MEMBER_NOTICE = (
    "## Speicherung auf deinem Gerät\n\n"
    "Die Akquise-App speichert Kontaktdaten deiner eigenen Sponsoren "
    "verschlüsselt auf deinem Gerät, höchstens 14 Tage."
)
IMPRINT = {
    "legalForm": "registered_association",
    "imprintRepresentatives": "Vorstand: Paula Golden (Präsidentin)",
    "imprintPhone": "+49 30 23125 044",
    "imprintRegisterCourt": "Amtsgericht Augsburg",
    "imprintRegisterNumber": "VR 0044",
    "imprintVatId": "de 999 999 999",
    "imprintContentResponsibleName": "Paula Golden",
    "imprintContentResponsibleAddress": "Testweg 44, 86150 Augsburg",
}


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def token_for(label: str, user_id: UUID) -> str:
    return f"pilot044-{label}-{user_id}-real-session-token-value"


def session_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def error_code(response: httpx.Response) -> str:
    value = response.json()
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise ContractFailure("Error response has no stable contract")
    return str(value["error"].get("code"))


def draft_payload(*, revision: int) -> dict[str, object]:
    return {
        "expectedRevision": revision,
        "issuer": {
            "legalName": "Golden Förderverein e. V.",
            "streetLine1": "Testweg 44",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "taxIdentifier": "103/123/45678",
            "email": "rechnung@leonaid.invalid",
        },
        "bankAccountHolder": "Golden Förderverein e. V.",
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "taxTreatment": "tax_exempt",
        "taxRateBasisPoints": 0,
        "taxNote": "Steuerbefreiung laut dokumentierter fachlicher Prüfung.",
        "numberPrefix": "KT",
        "numberWidth": 5,
        "paymentTermsDays": 14,
        "publicOrderLegalBasis": "Vertragserfüllung für die öffentliche Bestellung.",
        "publicOrderNoticeText": (
            "Wir verarbeiten die angegebenen Daten ausschließlich zur "
            "Durchführung und Abrechnung der Krapfentaxi-Bestellung."
        ),
        "consentTextVersion": "public-order-v1",
        "privacyContactEmail": "datenschutz@leonaid.invalid",
        "retention": {
            "invoiceDays": 3650,
            "commitmentDays": 3650,
            "contactDays": 730,
            "consentEvidenceDays": 3650,
            "auditDays": 3650,
        },
        "eInvoiceDecision": "pending",
        "taxEvidenceId": "STEUER-PILOT-044",
        "privacyEvidenceId": "DATENSCHUTZ-PILOT-044",
        "eInvoiceEvidenceId": None,
        **IMPRINT,
        "privacyPolicyText": PRIVACY_POLICY,
        "memberPrivacyNoticeText": MEMBER_NOTICE,
    }


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    await connection.execute(
        """
        INSERT INTO user_global_role (user_id, role)
        VALUES ($1, 'system_admin')
        ON CONFLICT DO NOTHING
        """,
        KLARA_ID,
    )
    sessions = (
        ("simone", SIMONE_ID),
        ("klara", KLARA_ID),
        ("anna", ANNA_ID),
    )
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        [SIMONE_ID, KLARA_ID, ANNA_ID],
    )
    tokens: dict[str, str] = {}
    for label, user_id in sessions:
        token = token_for(label, user_id)
        tokens[label] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, device_hint,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, 'PILOT-044 legal', $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, label),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    return tokens


async def prepare(connection: asyncpg.Connection[Any]) -> None:
    await connection.execute(
        """
        UPDATE legal_configuration_state
        SET revision = 1,
            draft_version_id = NULL,
            active_version_id = NULL,
            updated_by_user_id = NULL,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    await connection.execute(
        """
        UPDATE invoice_profile
        SET legal_configuration_version_id = NULL
        WHERE legal_configuration_version_id IS NOT NULL
        """
    )
    await connection.execute("DELETE FROM legal_configuration_approval")
    await connection.execute("DELETE FROM legal_configuration_version")
    await connection.execute(
        "DELETE FROM audit_event WHERE entity_type = 'legal_configuration'"
    )
    # An action with invoicing that has no profile yet, as every action
    # created before a legal configuration was active: the activation must
    # give it one (spec mails-documents-donations-push §5.3).
    await connection.execute(
        "DELETE FROM invoice_profile WHERE action_id = $1", PROFILELESS_ACTION_ID
    )
    await connection.execute(
        """
        INSERT INTO charity_action (
            id, carrier_name, name, purpose, status, starts_on, ends_on,
            archive_slug
        )
        VALUES ($1, 'Legal proof', 'Aktion ohne Rechnungsprofil', 'Proof',
                'draft', '2026-01-01', '2099-12-31', 'legal-proof-profileless')
        ON CONFLICT (id) DO NOTHING
        """,
        PROFILELESS_ACTION_ID,
    )
    await connection.execute(
        """
        INSERT INTO charity_action_capability (action_id, capability)
        VALUES ($1, 'invoicing')
        ON CONFLICT DO NOTHING
        """,
        PROFILELESS_ACTION_ID,
    )
    tokens = await seed_sessions(connection)
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        initial = await api.get(
            "/api/v1/admin/legal/configuration",
            headers=session_headers(tokens["simone"]),
        )
        initial.raise_for_status()
        if initial.json() != {
            "revision": 1,
            "production": False,
            "draft": None,
            "active": None,
            "draftApproval": None,
        }:
            raise ContractFailure("Initial state is not deterministic")

        forbidden = await api.get(
            "/api/v1/admin/legal/configuration",
            headers=session_headers(tokens["anna"]),
        )
        if (
            forbidden.status_code != 403
            or error_code(forbidden) != "system_admin_required"
        ):
            raise ContractFailure("Acquirer could read the legal basis")

        created = await api.put(
            "/api/v1/admin/legal/configuration/draft",
            headers=session_headers(tokens["simone"]),
            json=draft_payload(revision=1),
        )
        created.raise_for_status()
        state = created.json()
        if (
            state.get("revision") != 2
            or not isinstance(state.get("draft"), dict)
            or state["draft"].get("version") != 1
        ):
            raise ContractFailure("First immutable version was not created")
        stored = state["draft"]["values"]
        expected_imprint = {**IMPRINT, "imprintVatId": "DE999999999"}
        if any(stored.get(key) != value for key, value in expected_imprint.items()):
            raise ContractFailure(f"Impressum fields were not stored: {stored}")
        if (
            stored.get("privacyPolicyText") != PRIVACY_POLICY
            or stored.get("memberPrivacyNoticeText") != MEMBER_NOTICE
        ):
            raise ContractFailure("Privacy texts were not stored unchanged")

        incomplete = await api.put(
            "/api/v1/admin/legal/configuration/draft",
            headers=session_headers(tokens["simone"]),
            json={
                **draft_payload(revision=2),
                "imprintRegisterNumber": None,
            },
        )
        if (
            incomplete.status_code != 422
            or error_code(incomplete) != "legal_imprint_register_incomplete"
        ):
            raise ContractFailure(
                "A register court without number was accepted: "
                f"{incomplete.status_code} {incomplete.text[:200]}"
            )

        version_id = str(state["draft"]["id"])
        unapproved = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/activation",
            headers=session_headers(tokens["klara"]),
            json={"expectedRevision": 2},
        )
        if (
            unapproved.status_code != 409
            or error_code(unapproved) != "legal_configuration_approval_required"
        ):
            raise ContractFailure("A draft without approval was activated")

        own_approval = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/approval",
            headers=session_headers(tokens["simone"]),
            json={
                "evidenceId": "FREIGABE-PILOT-044",
                "expectedRevision": 2,
            },
        )
        if (
            own_approval.status_code != 409
            or error_code(own_approval) != "legal_configuration_four_eyes_required"
        ):
            raise ContractFailure("Four-eyes rule allowed self-approval")

        approved = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/approval",
            headers=session_headers(tokens["klara"]),
            json={
                "evidenceId": "FREIGABE-PILOT-044",
                "expectedRevision": 2,
            },
        )
        approved.raise_for_status()
        if approved.json().get("revision") != 3:
            raise ContractFailure("Approval did not increase the revision")

        blocked = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/activation",
            headers=session_headers(tokens["simone"]),
            json={"expectedRevision": 3},
        )
        if (
            blocked.status_code != 409
            or error_code(blocked) != "legal_configuration_activation_blocked"
        ):
            raise ContractFailure("Pending e-invoice decision was activated")

        stale = await api.put(
            "/api/v1/admin/legal/configuration/draft",
            headers=session_headers(tokens["simone"]),
            json=draft_payload(revision=1),
        )
        if (
            stale.status_code != 409
            or error_code(stale) != "legal_configuration_revision_conflict"
        ):
            raise ContractFailure("Optimistic revision did not prevent a lost update")


async def act() -> None:
    """The admins' UI steps through the API (the UI is proven in vitest).

    Klara records the e-invoice decision as a new draft and may not approve
    it herself; Simone approves and activates. Only then does the public
    Impressum name a provider.
    """
    klara = session_headers(token_for("klara", KLARA_ID))
    simone = session_headers(token_for("simone", SIMONE_ID))
    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        before = await api.get("/api/v1/public/legal-notice")
        before.raise_for_status()
        if before.json().get("provider") is not None:
            raise ContractFailure("Public Impressum names a provider before activation")

        saved = await api.put(
            "/api/v1/admin/legal/configuration/draft",
            headers=klara,
            json={
                **draft_payload(revision=3),
                "eInvoiceDecision": "not_required",
                "eInvoiceEvidenceId": "ERECHNUNG-PILOT-044",
            },
        )
        saved.raise_for_status()
        state = saved.json()
        if state.get("revision") != 4 or state["draft"].get("version") != 2:
            raise ContractFailure(f"Second draft was not created: {state}")
        version_id = str(state["draft"]["id"])

        own_approval = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/approval",
            headers=klara,
            json={"evidenceId": "UI-FREIGABE-PILOT-044", "expectedRevision": 4},
        )
        if (
            own_approval.status_code != 409
            or error_code(own_approval) != "legal_configuration_four_eyes_required"
        ):
            raise ContractFailure("The draft author approved her own draft")

        approved = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/approval",
            headers=simone,
            json={"evidenceId": "UI-FREIGABE-PILOT-044", "expectedRevision": 4},
        )
        approved.raise_for_status()
        activated = await api.post(
            f"/api/v1/admin/legal/configuration/draft/{version_id}/activation",
            headers=simone,
            json={"expectedRevision": approved.json()["revision"]},
        )
        activated.raise_for_status()
        final = activated.json()
        if (
            final.get("draft") is not None
            or final.get("active", {}).get("version") != 2
        ):
            raise ContractFailure(f"Version 2 is not active: {final}")


async def assert_result(connection: asyncpg.Connection[Any]) -> None:
    state = await connection.fetchrow(
        """
        SELECT revision, draft_version_id, active_version_id
        FROM legal_configuration_state
        """
    )
    if (
        state is None
        or int(state["revision"]) != 6
        or state["draft_version_id"] is not None
        or state["active_version_id"] is None
    ):
        raise ContractFailure(f"Final active state is invalid: {state}")

    versions = await connection.fetch(
        """
        SELECT version, e_invoice_decision, e_invoice_evidence_id
        FROM legal_configuration_version
        ORDER BY version
        """
    )
    if [
        (
            int(row["version"]),
            str(row["e_invoice_decision"]),
            row["e_invoice_evidence_id"],
        )
        for row in versions
    ] != [
        (1, "pending", None),
        (2, "not_required", "ERECHNUNG-PILOT-044"),
    ]:
        raise ContractFailure("Versions are incomplete or were changed")

    rows = await connection.fetch(
        """
        SELECT event_type, actor_user_id, payload::text
        FROM audit_event
        WHERE entity_type = 'legal_configuration'
        ORDER BY occurred_at, id
        """
    )
    if [str(row["event_type"]) for row in rows] != [
        "legal_configuration_draft_saved",
        "legal_configuration_approved",
        "legal_configuration_draft_saved",
        "legal_configuration_approved",
        "legal_configuration_activated",
    ]:
        raise ContractFailure("Audit sequence is incomplete")
    if [row["actor_user_id"] for row in rows] != [
        SIMONE_ID,
        KLARA_ID,
        KLARA_ID,
        SIMONE_ID,
        SIMONE_ID,
    ]:
        raise ContractFailure("Audit names the wrong actor")
    forbidden_fragments = (
        "DE89370400440532013000",
        "@leonaid.invalid",
        "Testweg",
        "Datenschutz",
    )
    audit_payload = json.dumps([str(row["payload"]) for row in rows])
    if any(fragment in audit_payload for fragment in forbidden_fragments):
        raise ContractFailure("Audit contains confidential configuration values")

    active_version_id = state["active_version_id"]
    profile = await connection.fetchrow(
        """
        SELECT legal_configuration_version_id, legal_name, tax_treatment,
               number_prefix, next_number, number_width, payment_terms_days
        FROM invoice_profile
        WHERE action_id = $1
        """,
        UUID("20000000-0000-4000-8000-000000000001"),
    )
    if (
        profile is None
        or profile["legal_configuration_version_id"] != active_version_id
        or profile["legal_name"] != "Golden Förderverein e. V."
        or profile["tax_treatment"] != "tax_exempt"
        or profile["number_prefix"] != "KT"
        or int(profile["next_number"]) != 4
        or int(profile["number_width"]) != 5
        or int(profile["payment_terms_days"]) != 14
    ):
        raise ContractFailure(
            "Invoice profile was not bound atomically to the active version"
        )
    # ADR-0015: the activated prefix has its series for the installation.
    # No number with the prefix "KT" exists yet (the golden invoices carry
    # "KT26-"), so it starts at 1 with the configured width.
    series = await connection.fetchrow(
        """
        SELECT next_number, width FROM document_series
        WHERE kind = 'invoice' AND prefix = 'KT'
        """
    )
    if series is None or (int(series["next_number"]), int(series["width"])) != (1, 5):
        raise ContractFailure("The activated prefix has no invoice series")
    created = await connection.fetchrow(
        """
        SELECT legal_configuration_version_id, legal_name, number_prefix,
               confirmed_at, iban
        FROM invoice_profile
        WHERE action_id = $1
        """,
        PROFILELESS_ACTION_ID,
    )
    if (
        created is None
        or created["legal_configuration_version_id"] != active_version_id
        or created["legal_name"] != "Golden Förderverein e. V."
        or created["number_prefix"] != "KT"
        or created["confirmed_at"] is None
        or created["iban"] is None
    ):
        raise ContractFailure(
            "An action with invoicing got no invoice profile on activation"
        )
    approval = await connection.fetchrow(
        """
        SELECT approved_by_user_id, evidence_id
        FROM legal_configuration_approval
        WHERE version_id = $1
        """,
        active_version_id,
    )
    if (
        approval is None
        or approval["approved_by_user_id"] != SIMONE_ID
        or approval["evidence_id"] != "UI-FREIGABE-PILOT-044"
    ):
        raise ContractFailure("Active version has no independent UI approval")

    imprint = await connection.fetchrow(
        """
        SELECT legal_form, imprint_representatives, imprint_phone,
               imprint_register_court,
               imprint_register_number, imprint_vat_id,
               imprint_content_responsible_name,
               imprint_content_responsible_address,
               privacy_policy_text, member_privacy_notice_text
        FROM legal_configuration_version
        WHERE id = $1
        """,
        active_version_id,
    )
    if imprint is None or dict(imprint) != {
        "legal_form": "registered_association",
        "imprint_representatives": IMPRINT["imprintRepresentatives"],
        "imprint_phone": IMPRINT["imprintPhone"],
        "imprint_register_court": IMPRINT["imprintRegisterCourt"],
        "imprint_register_number": IMPRINT["imprintRegisterNumber"],
        "imprint_vat_id": "DE999999999",
        "imprint_content_responsible_name": IMPRINT["imprintContentResponsibleName"],
        "imprint_content_responsible_address": IMPRINT[
            "imprintContentResponsibleAddress"
        ],
        "privacy_policy_text": PRIVACY_POLICY,
        "member_privacy_notice_text": MEMBER_NOTICE,
    }:
        raise ContractFailure(
            "The UI draft did not carry the Impressum and privacy texts over"
        )

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        notice = await api.get("/api/v1/public/legal-notice")
        notice.raise_for_status()
        provider = notice.json()["provider"]
        if provider is None or provider.get("registerNumber") != "VR 0044":
            raise ContractFailure(f"Public Impressum is incomplete: {provider}")
        policy = await api.get("/api/v1/public/privacy-policy")
        policy.raise_for_status()
        content = policy.json()["policy"]
        if (
            content is None
            or content.get("policyText") != PRIVACY_POLICY
            or content.get("memberNoticeText") != MEMBER_NOTICE
            or content.get("privacyContactEmail") != "datenschutz@leonaid.invalid"
        ):
            raise ContractFailure(f"Public privacy policy is incomplete: {content}")
        public_text = notice.text + policy.text
        if any(
            secret in public_text
            for secret in ("DE89370400440532013000", "103/123/45678", "STEUER-")
        ):
            raise ContractFailure("Public legal pages leak internal data")

    print(
        "legal-configuration-contract: OK: versioning, four-eyes rule, "
        "activation block, Impressum and privacy texts, public pages and "
        "PII-free audit proven"
    )


async def run(command: str) -> None:
    if command == "act":
        await act()
        return
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        if command == "prepare":
            await prepare(connection)
        else:
            await assert_result(connection)
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "act", "assert"))
    arguments = parser.parse_args()
    asyncio.run(run(arguments.command))


if __name__ == "__main__":
    main()
