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


PRIVACY_POLICY = (
    "## Verantwortlicher\n\n"
    "Verantwortlich für die Verarbeitung ist der im Impressum genannte "
    "Verein. Wir verarbeiten Daten nur für die beschriebenen Zwecke.\n\n"
    "## Ihre Rechte\n\n"
    "Sie haben das Recht auf Auskunft, Berichtigung, Löschung und "
    "Einschränkung der Verarbeitung."
)
MEMBER_NOTICE = (
    "Die Akquise-App speichert die Kontaktdaten deiner eigenen Sponsoren "
    "verschlüsselt auf deinem Gerät, höchstens 14 Tage."
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
        imprint_representatives="Vorstand: Erika Muster (Präsidentin)",
        imprint_phone="+49 821 123456",
        imprint_register_court="Amtsgericht Augsburg",
        imprint_register_number="VR 1234",
        privacy_policy_text=PRIVACY_POLICY,
        member_privacy_notice_text=MEMBER_NOTICE,
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


def production_draft() -> LegalConfigurationDraft:
    """valid_draft() without the synthetic .test addresses."""
    draft = valid_draft()
    return replace(
        draft,
        issuer=replace(draft.issuer, email="rechnung@lions-hilfswerk-augsburg.de"),
        privacy_contact_email="datenschutz@lions-hilfswerk-augsburg.de",
    )


def test_production_draft_has_no_blockers() -> None:
    assert production_draft().activation_blockers(production=True) == ()


def test_production_lists_missing_imprint_and_privacy_fields() -> None:
    draft = replace(
        production_draft(),
        imprint_representatives=None,
        imprint_phone="  ",
        imprint_register_court=None,
        imprint_register_number=None,
        privacy_policy_text="",
        member_privacy_notice_text=None,
    )

    assert draft.imprint_phone is None
    assert draft.privacy_policy_text is None
    assert draft.activation_blockers(production=False) == ()
    assert draft.activation_blockers(production=True) == (
        "imprint_representatives_missing",
        "imprint_phone_missing",
        "imprint_register_missing",
        "privacy_policy_missing",
        "member_privacy_notice_missing",
    )


def test_register_is_required_only_for_a_registered_association() -> None:
    for legal_name in (
        "Lions Club Augsburg Förderverein e. V.",
        "Förderverein e.V., Augsburg",
        "Lions Hilfswerk eingetragener Verein",
    ):
        draft = replace(
            production_draft(),
            issuer=replace(production_draft().issuer, legal_name=legal_name),
            imprint_register_court=None,
            imprint_register_number=None,
        )
        assert draft.activation_blockers(production=True) == (
            "imprint_register_missing",
        ), legal_name

    unregistered = replace(
        production_draft(),
        issuer=replace(production_draft().issuer, legal_name="Lions Club Augsburg"),
        bank_account_holder="Lions Club Augsburg",
        imprint_register_court=None,
        imprint_register_number=None,
    )
    assert unregistered.activation_blockers(production=True) == ()


def test_template_placeholders_block_production() -> None:
    draft = replace(
        production_draft(),
        member_privacy_notice_text=MEMBER_NOTICE + " [[Rechtsgrundlage ergänzen]]",
    )

    assert draft.activation_blockers(production=False) == ()
    assert draft.activation_blockers(production=True) == ("template_placeholder_open",)


def test_imprint_fields_are_normalized() -> None:
    draft = replace(
        valid_draft(),
        imprint_representatives="  Vorstand:\n Erika   Muster ",
        imprint_vat_id=" de 123 456 789 ",
        imprint_content_responsible_name=" Max Muster ",
        imprint_content_responsible_address=" Löwenweg 12,  86150 Augsburg ",
        privacy_policy_text="\r\n"
        + PRIVACY_POLICY.replace("\n\n", "\n\n\n\n")
        + "  \n",
    )

    assert draft.imprint_representatives == "Vorstand: Erika Muster"
    assert draft.imprint_vat_id == "DE123456789"
    assert draft.imprint_content_responsible_name == "Max Muster"
    assert draft.imprint_content_responsible_address == ("Löwenweg 12, 86150 Augsburg")
    # Paragraphs survive; extra blank lines and trailing spaces do not.
    assert draft.privacy_policy_text == PRIVACY_POLICY


def test_invalid_imprint_and_privacy_values_are_rejected() -> None:
    cases = (
        ({"imprint_phone": "bitte anrufen"}, "legal_imprint_phone_invalid"),
        ({"imprint_vat_id": "123"}, "legal_imprint_vat_id_invalid"),
        (
            {"imprint_register_number": None},
            "legal_imprint_register_incomplete",
        ),
        (
            {"imprint_content_responsible_name": "Max Muster"},
            "legal_imprint_content_responsible_incomplete",
        ),
        ({"privacy_policy_text": "Zu kurz."}, "legal_privacy_policy_text_invalid"),
        (
            {"member_privacy_notice_text": "Zu kurz."},
            "legal_member_privacy_notice_text_invalid",
        ),
        ({"imprint_representatives": "Xy"}, "legal_imprint_representatives_invalid"),
    )
    for overrides, code in cases:
        with raises(DomainInvariantError) as error:
            replace(valid_draft(), **overrides)  # type: ignore[arg-type]
        assert error.value.code == code, overrides
