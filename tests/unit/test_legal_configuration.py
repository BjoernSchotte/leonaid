from __future__ import annotations

from dataclasses import replace

from pytest import raises

from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.invoices import InvoiceIssuerSnapshot, TaxTreatment
from leonaid.domain.legal_configuration import (
    EInvoiceDecision,
    LegalConfigurationDraft,
    LegalForm,
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
        legal_form=LegalForm.REGISTERED_ASSOCIATION,
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
        # The invoice tax identifier DE123456789 is a VAT ID.
        "imprint_vat_id_missing",
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
        imprint_vat_id="DE123456789",
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
        legal_form=None,
    )

    assert draft.imprint_phone is None
    assert draft.privacy_policy_text is None
    assert draft.activation_blockers(production=False) == ()
    assert draft.activation_blockers(production=True) == (
        # Without a chosen legal form no register can be required yet.
        "legal_form_missing",
        "imprint_representatives_missing",
        "imprint_phone_missing",
        "privacy_policy_missing",
        "member_privacy_notice_missing",
    )


def test_the_legal_form_is_chosen_not_read_from_the_name() -> None:
    # "AG" in the name is an Arbeitsgemeinschaft here, not a stock company.
    unregistered = replace(
        production_draft(),
        issuer=replace(
            production_draft().issuer, legal_name="Lions AG Jugendhilfe Augsburg"
        ),
        bank_account_holder="Lions AG Jugendhilfe Augsburg",
        legal_form=LegalForm.UNREGISTERED_ASSOCIATION,
        imprint_register_court=None,
        imprint_register_number=None,
    )
    assert unregistered.required_register() is None
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
            replace(valid_draft(), **overrides)
        assert error.value.code == code, overrides


def test_register_follows_the_legal_form() -> None:
    cases = (
        (LegalForm.REGISTERED_ASSOCIATION, "Vereinsregister"),
        (LegalForm.GGMBH, "Handelsregister"),
        (LegalForm.GMBH, "Handelsregister"),
        (LegalForm.COOPERATIVE, "Genossenschaftsregister"),
        (LegalForm.UNREGISTERED_ASSOCIATION, None),
        (LegalForm.FOUNDATION, None),
        (LegalForm.OTHER, None),
    )
    for legal_form, register in cases:
        draft = replace(
            production_draft(),
            legal_form=legal_form,
            imprint_register_court=None,
            imprint_register_number=None,
        )
        assert draft.required_register() == register, legal_form
        assert (
            "imprint_register_missing" in draft.activation_blockers(production=True)
        ) == (register is not None), legal_form


def test_a_missing_legal_form_blocks_production_only() -> None:
    draft = replace(production_draft(), legal_form=None)
    assert draft.activation_blockers(production=False) == ()
    assert draft.activation_blockers(production=True) == ("legal_form_missing",)


def test_register_label_prefers_the_number_prefix() -> None:
    draft = production_draft()
    assert draft.register_label() == "Vereinsregister"  # VR 1234
    assert replace(draft, imprint_register_number="HRB 5678").register_label() == (
        "Handelsregister"
    )
    assert replace(draft, imprint_register_number="GnR 12").register_label() == (
        "Genossenschaftsregister"
    )
    unknown = replace(
        draft,
        legal_form=LegalForm.OTHER,
        imprint_register_number="1234",
    )
    assert unknown.register_label() is None
    assert (
        replace(
            draft, imprint_register_court=None, imprint_register_number=None
        ).register_label()
        is None
    )


def test_a_vat_id_on_invoices_is_required_in_the_imprint() -> None:
    draft = replace(production_draft(), imprint_vat_id=None)
    assert draft.activation_blockers(production=True) == ("imprint_vat_id_missing",)
    tax_number = replace(
        draft, issuer=replace(draft.issuer, tax_identifier="103/123/45678")
    )
    assert tax_number.activation_blockers(production=True) == ()


def test_german_phone_formats_are_accepted() -> None:
    for phone in (
        "(0821) 123456",
        "0821 / 12 34 56",
        "+49 (0)821 123-456",
        "0821.123456",
    ):
        assert replace(valid_draft(), imprint_phone=phone).imprint_phone == phone


def test_synthetic_and_placeholder_checks_cover_the_new_fields() -> None:
    synthetic = replace(
        production_draft(),
        imprint_content_responsible_name="Paula Golden",
        imprint_content_responsible_address="Clubweg 1, 86150 Augsburg",
    )
    assert synthetic.activation_blockers(production=True) == (
        "synthetic_or_placeholder_value",
    )
    placeholder = replace(
        production_draft(), imprint_register_court="[[Registergericht]]"
    )
    assert placeholder.activation_blockers(production=True) == (
        "template_placeholder_open",
    )
