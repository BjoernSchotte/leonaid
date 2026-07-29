from __future__ import annotations

from dataclasses import replace

from pytest import raises

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoices import InvoiceIssuerSnapshot, TaxTreatment
from leonaid.domain.legal_configuration import (
    EInvoiceDecision,
    LegalConfigurationDraft,
    RetentionSchedule,
)


def valid_draft() -> LegalConfigurationDraft:
    return LegalConfigurationDraft(
        issuer=InvoiceIssuerSnapshot(
            legal_name="Lions Hilfswerk Augsburg e.V.",
            street_line_1="Löwenweg 12",
            postal_code="86150",
            city="Augsburg",
            country_code="DE",
            tax_identifier="DE123456789",
            email="rechnung@hilfswerk.test",
        ),
        bank_account_holder="Lions Hilfswerk Augsburg e.V.",
        iban="DE89 3704 0044 0532 0130 00",
        bic="COBADEFFXXX",
        tax_treatment=TaxTreatment.TAX_EXEMPT,
        tax_rate_basis_points=0,
        tax_note="Umsatzsteuerbefreiung fachlich bestätigt.",
        number_prefix="KT26-",
        number_width=4,
        payment_terms_days=14,
        public_order_legal_basis=(
            "Verarbeitung zur Durchführung der öffentlich bestellten Leistung."
        ),
        public_order_notice_text=(
            "Die Daten werden ausschließlich zur Bearbeitung und Abwicklung "
            "der Bestellung verwendet."
        ),
        consent_text_version="krapfentaxi-privacy-v1",
        privacy_contact_email="datenschutz@hilfswerk.test",
        retention=RetentionSchedule(
            invoice_days=3650,
            commitment_days=1095,
            contact_days=730,
            consent_evidence_days=1095,
            audit_days=2190,
        ),
        e_invoice_decision=EInvoiceDecision.NOT_REQUIRED,
        tax_evidence_id="TAX-2026-001",
        privacy_evidence_id="PRIVACY-2026-001",
        e_invoice_evidence_id="EINVOICE-2026-001",
    )


def test_legal_configuration_normalizes_financial_fields() -> None:
    draft = valid_draft()

    assert draft.iban == "DE89370400440532013000"
    assert draft.bic == "COBADEFFXXX"
    assert draft.activation_blockers(production=False) == ()


def test_required_e_invoice_scope_blocks_activation() -> None:
    draft = replace(
        valid_draft(),
        e_invoice_decision=EInvoiceDecision.REQUIRED,
    )

    assert draft.activation_blockers(production=False) == ("e_invoice_scope_required",)


def test_pending_decision_and_synthetic_values_block_production() -> None:
    draft = replace(
        valid_draft(),
        issuer=replace(
            valid_draft().issuer,
            legal_name="LeonAid Golden e.V.",
            email="rechnung@leonaid.invalid",
        ),
        e_invoice_decision=EInvoiceDecision.PENDING,
        e_invoice_evidence_id=None,
    )

    assert draft.activation_blockers(production=True) == (
        "e_invoice_decision_pending",
        "e_invoice_evidence_missing",
        "synthetic_or_placeholder_value",
    )


def test_invalid_retention_and_tax_combinations_are_rejected() -> None:
    with raises(DomainInvariantError) as retention_error:
        replace(valid_draft().retention, invoice_days=0)
    assert retention_error.value.code == "legal_retention_invalid"

    with raises(DomainInvariantError) as tax_error:
        replace(valid_draft(), tax_rate_basis_points=1900)
    assert tax_error.value.code == "legal_tax_rate_forbidden"
