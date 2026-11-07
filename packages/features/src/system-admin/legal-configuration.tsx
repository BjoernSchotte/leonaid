import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CircleAlert,
  Clock,
  FilePen,
  History,
  Info,
  Lock,
  Save,
  ShieldCheck,
} from "lucide-react";
import {
  useCallback,
  useId,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LegalConfigurationStateResponse,
  type LegalConfigurationValuesResponse,
  type LeonAidApiClient,
  type SaveLegalConfigurationDraftRequest,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  ConfirmDialog,
  DetailProps,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  Input,
  NextStep,
  Select,
  SkeletonRows,
  StatusIcon,
  StatusMessage,
  Textarea,
  useDiscardDialog,
  useHotkeys,
  useLeaveGuard,
  useOptionalToast,
} from "@leonaid/ui";

import {
  actionErrorMessage,
  type ActionErrorMessage,
} from "../action-admin/errors";
import { useActionErrorMessage } from "../action-admin/use-action-error";
import { useContextCommands } from "../command-palette/store";
import { navigateInPage, useLocationHref } from "../shared/location";
import { formatDateTime } from "../shared/dates";
import {
  MEMBER_PRIVACY_NOTICE_TEMPLATE,
  PRIVACY_POLICY_TEMPLATE,
} from "./legal-templates";

interface LegalForm {
  legalName: string;
  legalForm: string;
  streetLine1: string;
  postalCode: string;
  city: string;
  countryCode: string;
  taxIdentifier: string;
  issuerEmail: string;
  bankAccountHolder: string;
  iban: string;
  bic: string;
  taxTreatment: SaveLegalConfigurationDraftRequest["taxTreatment"];
  taxRatePercent: string;
  taxNote: string;
  numberPrefix: string;
  numberWidth: string;
  paymentTermsDays: string;
  publicOrderLegalBasis: string;
  publicOrderNoticeText: string;
  consentTextVersion: string;
  privacyContactEmail: string;
  invoiceRetentionDays: string;
  commitmentRetentionDays: string;
  contactRetentionDays: string;
  consentEvidenceRetentionDays: string;
  auditRetentionDays: string;
  eInvoiceDecision: SaveLegalConfigurationDraftRequest["eInvoiceDecision"];
  taxEvidenceId: string;
  privacyEvidenceId: string;
  eInvoiceEvidenceId: string;
  imprintRepresentatives: string;
  imprintPhone: string;
  imprintRegisterCourt: string;
  imprintRegisterNumber: string;
  imprintVatId: string;
  imprintContentResponsibleName: string;
  imprintContentResponsibleAddress: string;
  privacyPolicyText: string;
  memberPrivacyNoticeText: string;
}

type FieldKey = keyof LegalForm;

const emptyForm: LegalForm = {
  auditRetentionDays: "3650",
  bankAccountHolder: "",
  bic: "",
  city: "",
  commitmentRetentionDays: "3650",
  consentEvidenceRetentionDays: "3650",
  consentTextVersion: "public-order-v1",
  contactRetentionDays: "730",
  countryCode: "DE",
  eInvoiceDecision: "pending",
  eInvoiceEvidenceId: "",
  iban: "",
  imprintContentResponsibleAddress: "",
  imprintContentResponsibleName: "",
  imprintPhone: "",
  imprintRegisterCourt: "",
  imprintRegisterNumber: "",
  imprintRepresentatives: "",
  imprintVatId: "",
  invoiceRetentionDays: "3650",
  issuerEmail: "",
  legalForm: "",
  legalName: "",
  memberPrivacyNoticeText: MEMBER_PRIVACY_NOTICE_TEMPLATE,
  numberPrefix: "KT",
  numberWidth: "5",
  paymentTermsDays: "14",
  postalCode: "",
  privacyContactEmail: "",
  privacyEvidenceId: "",
  privacyPolicyText: PRIVACY_POLICY_TEMPLATE,
  publicOrderLegalBasis: "",
  publicOrderNoticeText: "",
  streetLine1: "",
  taxEvidenceId: "",
  taxIdentifier: "",
  taxNote: "",
  taxRatePercent: "0",
  taxTreatment: "tax_exempt",
};

const blockerLabels: Record<string, string> = {
  e_invoice_decision_pending:
    "Die E-Rechnungs-Pflicht ist noch nicht entschieden.",
  e_invoice_evidence_missing: "Der Nachweis zur E-Rechnungsentscheidung fehlt.",
  e_invoice_scope_required:
    "E-Rechnungen sind erforderlich; das liegt außerhalb des ERP-light-Piloten.",
  synthetic_or_placeholder_value:
    "Produktive Angaben enthalten noch Test- oder Platzhalterwerte.",
  legal_form_missing: "Die Rechtsform des Trägers ist nicht gewählt.",
  imprint_representatives_missing:
    "Im Impressum fehlen die vertretungsberechtigten Personen.",
  imprint_phone_missing: "Im Impressum fehlt die Telefonnummer.",
  imprint_register_missing:
    "Im Impressum fehlt der Registereintrag (Gericht und Nummer), den die gewählte Rechtsform verlangt.",
  imprint_vat_id_missing:
    "Die Steuerkennung ist eine Umsatzsteuer-ID; sie gehört auch ins Impressum.",
  privacy_policy_missing: "Die Datenschutzerklärung fehlt.",
  member_privacy_notice_missing: "Der Datenschutzhinweis für Mitglieder fehlt.",
  template_placeholder_open:
    "Ein Text enthält noch offene Vorlagen-Platzhalter in [[ ]].",
};

function formFromValues(values: LegalConfigurationValuesResponse): LegalForm {
  return {
    auditRetentionDays: String(values.retention.auditDays),
    bankAccountHolder: values.bankAccountHolder,
    bic: values.bic ?? "",
    city: values.issuer.city,
    commitmentRetentionDays: String(values.retention.commitmentDays),
    consentEvidenceRetentionDays: String(values.retention.consentEvidenceDays),
    consentTextVersion: values.consentTextVersion,
    contactRetentionDays: String(values.retention.contactDays),
    countryCode: values.issuer.countryCode,
    eInvoiceDecision: values.eInvoiceDecision,
    eInvoiceEvidenceId: values.eInvoiceEvidenceId ?? "",
    iban: values.iban,
    imprintContentResponsibleAddress:
      values.imprintContentResponsibleAddress ?? "",
    imprintContentResponsibleName: values.imprintContentResponsibleName ?? "",
    imprintPhone: values.imprintPhone ?? "",
    imprintRegisterCourt: values.imprintRegisterCourt ?? "",
    imprintRegisterNumber: values.imprintRegisterNumber ?? "",
    imprintRepresentatives: values.imprintRepresentatives ?? "",
    imprintVatId: values.imprintVatId ?? "",
    invoiceRetentionDays: String(values.retention.invoiceDays),
    issuerEmail: values.issuer.email,
    legalForm: values.legalForm ?? "",
    legalName: values.issuer.legalName,
    // Shows what is stored: an empty text stays empty (four-eyes review).
    memberPrivacyNoticeText: values.memberPrivacyNoticeText ?? "",
    numberPrefix: values.numberPrefix,
    numberWidth: String(values.numberWidth),
    paymentTermsDays: String(values.paymentTermsDays),
    postalCode: values.issuer.postalCode,
    privacyContactEmail: values.privacyContactEmail,
    privacyEvidenceId: values.privacyEvidenceId,
    privacyPolicyText: values.privacyPolicyText ?? "",
    publicOrderLegalBasis: values.publicOrderLegalBasis,
    publicOrderNoticeText: values.publicOrderNoticeText,
    streetLine1: values.issuer.streetLine1,
    taxEvidenceId: values.taxEvidenceId,
    taxIdentifier: values.issuer.taxIdentifier,
    taxNote: values.taxNote,
    taxRatePercent: String(values.taxRateBasisPoints / 100),
    taxTreatment: values.taxTreatment,
  };
}

/**
 * The form a new edit starts from: empty privacy texts get the templates.
 * Only an edit seeds them; stored versions are always shown as stored, so
 * the reviewer sees a new policy as new.
 */
function seedForEditing(form: LegalForm): LegalForm {
  return {
    ...form,
    memberPrivacyNoticeText:
      form.memberPrivacyNoticeText || MEMBER_PRIVACY_NOTICE_TEMPLATE,
    privacyPolicyText: form.privacyPolicyText || PRIVACY_POLICY_TEMPLATE,
  };
}

/** Evidence IDs: the server accepts upper case without surrounding spaces. */
function evidenceId(value: string) {
  return value.trim().toUpperCase();
}

/** Optional text: empty means "not applicable" (null on the wire). */
function optionalText(value: string) {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function toInteger(value: string) {
  return Number.parseInt(value, 10);
}

function requestFromForm(
  form: LegalForm,
  revision: number,
): SaveLegalConfigurationDraftRequest {
  return {
    bankAccountHolder: form.bankAccountHolder,
    bic: form.bic || null,
    consentTextVersion: form.consentTextVersion,
    eInvoiceDecision: form.eInvoiceDecision,
    eInvoiceEvidenceId: evidenceId(form.eInvoiceEvidenceId) || null,
    expectedRevision: revision,
    iban: form.iban,
    imprintContentResponsibleAddress: optionalText(
      form.imprintContentResponsibleAddress,
    ),
    imprintContentResponsibleName: optionalText(
      form.imprintContentResponsibleName,
    ),
    imprintPhone: optionalText(form.imprintPhone),
    imprintRegisterCourt: optionalText(form.imprintRegisterCourt),
    imprintRegisterNumber: optionalText(form.imprintRegisterNumber),
    imprintRepresentatives: optionalText(form.imprintRepresentatives),
    imprintVatId: optionalText(form.imprintVatId.toUpperCase()),
    issuer: {
      city: form.city,
      countryCode: form.countryCode.toUpperCase(),
      email: form.issuerEmail,
      legalName: form.legalName,
      postalCode: form.postalCode,
      streetLine1: form.streetLine1,
      taxIdentifier: form.taxIdentifier.toUpperCase(),
    },
    legalForm: (form.legalForm ||
      null) as SaveLegalConfigurationDraftRequest["legalForm"],
    memberPrivacyNoticeText: optionalText(form.memberPrivacyNoticeText),
    numberPrefix: form.numberPrefix.toUpperCase(),
    numberWidth: toInteger(form.numberWidth),
    paymentTermsDays: toInteger(form.paymentTermsDays),
    privacyContactEmail: form.privacyContactEmail,
    privacyEvidenceId: evidenceId(form.privacyEvidenceId),
    privacyPolicyText: optionalText(form.privacyPolicyText),
    publicOrderLegalBasis: form.publicOrderLegalBasis,
    publicOrderNoticeText: form.publicOrderNoticeText,
    retention: {
      auditDays: toInteger(form.auditRetentionDays),
      commitmentDays: toInteger(form.commitmentRetentionDays),
      consentEvidenceDays: toInteger(form.consentEvidenceRetentionDays),
      contactDays: toInteger(form.contactRetentionDays),
      invoiceDays: toInteger(form.invoiceRetentionDays),
    },
    taxEvidenceId: evidenceId(form.taxEvidenceId),
    taxNote: form.taxNote,
    taxRateBasisPoints: Math.round(Number(form.taxRatePercent) * 100),
    taxTreatment: form.taxTreatment,
  };
}

/* ---------- the parts of the configuration ---------- */

interface FieldSpec {
  readonly key: FieldKey;
  readonly label: string;
  readonly hint: string;
  readonly kind?: "email" | "number" | "select" | "tel" | "textarea";
  readonly options?: readonly (readonly [string, string])[];
  readonly placeholder?: string;
  readonly min?: number;
  readonly max?: number;
  readonly step?: string;
  readonly rows?: number;
  readonly wide?: boolean;
  readonly unit?: string;
  readonly optional?: boolean;
}

const retentionField = (
  key: FieldKey,
  label: string,
  hint: string,
): FieldSpec => ({
  hint,
  key,
  kind: "number",
  label,
  max: 36500,
  min: 1,
  unit: "Tage",
});

const PARTS = [
  {
    id: "carrier",
    name: "Träger & Anschrift",
    intro:
      "Diese Angaben erscheinen im unveränderlichen Rechnungssnapshot und gelten für die ganze Installation.",
    fields: [
      {
        key: "legalName",
        label: "Name des Trägers",
        hint: "Der vollständige juristische Name des Vereins oder Trägers, genau wie auf Rechnungen.",
        placeholder: "z. B. Förderverein Lions Club Musterstadt e. V.",
        wide: true,
      },
      {
        key: "legalForm",
        label: "Rechtsform",
        hint: "Bestimmt, welcher Registereintrag ins Impressum gehört. LeonAid liest die Rechtsform nicht aus dem Namen.",
        kind: "select",
        options: [
          ["", "Bitte wählen"],
          ["registered_association", "Eingetragener Verein (e. V.)"],
          ["unregistered_association", "Nicht eingetragener Verein"],
          ["ggmbh", "Gemeinnützige GmbH (gGmbH)"],
          ["gmbh", "GmbH"],
          ["cooperative", "Eingetragene Genossenschaft (eG)"],
          ["foundation", "Stiftung"],
          ["other", "Sonstige"],
        ],
      },
      {
        key: "issuerEmail",
        label: "Rechnungs-E-Mail",
        hint: "Zentrale Kontaktadresse für Rückfragen zu ausgestellten Rechnungen.",
        kind: "email",
        placeholder: "rechnung@verein.de",
      },
      {
        key: "streetLine1",
        label: "Anschrift",
        hint: "Straße und Hausnummer der ladungsfähigen Anschrift.",
        placeholder: "Musterstraße 12",
      },
      {
        key: "postalCode",
        label: "Postleitzahl",
        hint: "Postleitzahl der Trägeranschrift.",
        placeholder: "86150",
      },
      {
        key: "city",
        label: "Ort",
        hint: "Ort der Trägeranschrift.",
        placeholder: "Augsburg",
      },
      {
        key: "countryCode",
        label: "Land",
        hint: "Zweistelliger Ländercode; für Deutschland DE.",
        placeholder: "DE",
      },
      {
        key: "taxIdentifier",
        label: "Steuerkennung",
        hint: "Steuernummer oder Umsatzsteuer-ID, wie von der Steuerberatung bestätigt.",
        placeholder: "z. B. 103/123/45678",
      },
    ],
  },
  {
    id: "imprint",
    name: "Impressum",
    intro:
      "Pflichtangaben nach § 5 DDG für alle öffentlichen Seiten der Installation. Name, Anschrift und E-Mail kommen aus „Träger & Anschrift“.",
    fields: [
      {
        key: "imprintRepresentatives",
        label: "Vertretungsberechtigte",
        hint: "Wer den Verein vertritt, mit Funktion, z. B. der Vorstand nach § 26 BGB.",
        kind: "textarea",
        rows: 2,
        wide: true,
        placeholder:
          "z. B. Vorstand: Erika Muster (Präsidentin), Max Muster (Schatzmeister)",
      },
      {
        key: "imprintPhone",
        label: "Telefon",
        hint: "Zweiter schneller Kontaktweg neben der E-Mail-Adresse.",
        kind: "tel",
        placeholder: "+49 821 123456",
      },
      {
        key: "imprintVatId",
        label: "Umsatzsteuer-ID",
        hint: "Angeben, wenn der Verein eine USt-IdNr. nach § 27a UStG hat; Pflicht, wenn sie als Steuerkennung auf Rechnungen steht.",
        placeholder: "DE123456789",
        optional: true,
      },
      {
        key: "imprintRegisterCourt",
        label: "Registergericht",
        hint: "Pflicht, wenn die Rechtsform ein Register hat (e. V., GmbH, gGmbH, eG): das Registergericht. Zusammen mit der Registernummer angeben.",
        placeholder: "Amtsgericht Augsburg",
        optional: true,
      },
      {
        key: "imprintRegisterNumber",
        label: "Registernummer",
        hint: "Nummer im Register, z. B. VR 1234 (Vereinsregister) oder HRB 5678 (Handelsregister).",
        placeholder: "VR 1234",
        optional: true,
      },
      {
        key: "imprintContentResponsibleName",
        label: "Inhaltlich verantwortlich",
        hint: "Für redaktionelle Inhalte wie Kampagnenseiten und Neuigkeiten (§ 18 Abs. 2 MStV). Zusammen mit der Anschrift angeben.",
        placeholder: "Erika Muster",
        optional: true,
      },
      {
        key: "imprintContentResponsibleAddress",
        label: "Anschrift der verantwortlichen Person",
        hint: "Ladungsfähige Anschrift der inhaltlich verantwortlichen Person.",
        placeholder: "Musterstraße 12, 86150 Augsburg",
        optional: true,
        wide: true,
      },
    ],
  },
  {
    id: "payment",
    name: "Zahlung & Nummernkreis",
    intro: "Konto, Rechnungsnummern und Zahlungsziel auf jeder Rechnung.",
    fields: [
      {
        key: "bankAccountHolder",
        label: "Kontoinhaber",
        hint: "Name, unter dem das Vereinskonto geführt wird.",
        wide: true,
      },
      {
        key: "iban",
        label: "IBAN",
        hint: "Leerzeichen sind erlaubt; LeonAid speichert die IBAN normalisiert.",
        placeholder: "DE12 3456 7890 1234 5678 90",
      },
      {
        key: "bic",
        label: "BIC",
        hint: "Optional bei inländischen Zahlungen; acht oder elf Zeichen.",
        placeholder: "GENODEF1XXX",
        optional: true,
      },
      {
        key: "numberPrefix",
        label: "Rechnungspräfix",
        hint: "Kurzes Kürzel am Anfang jeder Rechnungsnummer.",
        placeholder: "KT",
      },
      {
        key: "numberWidth",
        label: "Nummernlänge",
        hint: "Anzahl der Ziffern nach dem Präfix, zum Beispiel 00001.",
        kind: "number",
        min: 3,
        max: 8,
      },
      {
        key: "paymentTermsDays",
        label: "Zahlungsziel",
        hint: "Zeit zwischen Rechnungsdatum und gewünschtem Zahlungseingang.",
        kind: "number",
        min: 1,
        max: 120,
        unit: "Tage",
      },
    ],
  },
  {
    id: "tax",
    name: "Steuern",
    intro:
      "Nur entsprechend der schriftlichen steuerlichen Einordnung ausfüllen.",
    fields: [
      {
        key: "taxTreatment",
        label: "Umsatzsteuer",
        hint: "Die bestätigte steuerliche Behandlung.",
        kind: "select",
        options: [
          ["tax_exempt", "Steuerbefreit"],
          ["small_business", "Kein Ausweis nach § 19 UStG"],
          ["standard_vat", "Regelbesteuerung"],
        ],
      },
      {
        key: "taxRatePercent",
        label: "Steuersatz",
        hint: "Nur bei Regelbesteuerung größer als 0; sonst 0.",
        kind: "number",
        min: 0,
        max: 100,
        step: "0.01",
        unit: "%",
      },
      {
        key: "taxNote",
        label: "Steuerhinweis",
        hint: "Der bestätigte Hinweis, der auf jeder Rechnung zur steuerlichen Behandlung erscheint.",
        kind: "textarea",
        rows: 3,
        wide: true,
        placeholder: "z. B. Kein Ausweis von Umsatzsteuer aufgrund …",
      },
      {
        key: "taxEvidenceId",
        label: "Nachweis der Steuerfreigabe",
        hint: "Referenz auf Protokoll, Datei oder Ticket der fachlichen Steuerfreigabe; keine vertraulichen Inhalte.",
        placeholder: "z. B. STEUER-2026-01",
        wide: true,
      },
    ],
  },
  {
    id: "privacy",
    name: "Datenschutz",
    intro:
      "Die installationsweite Grundlage. Auskunft, Sperre und Anonymisierung einzelner Personen finden Sie unter System › Datenschutz.",
    fields: [
      {
        key: "publicOrderLegalBasis",
        label: "Rechtsgrundlage für öffentliche Bestellungen",
        hint: "Beschreibt knapp, auf welcher Rechtsgrundlage öffentliche Bestellungen verarbeitet werden.",
        kind: "textarea",
        rows: 2,
        wide: true,
        placeholder: "z. B. Vertragserfüllung nach Art. 6 Abs. 1 lit. b DSGVO",
      },
      {
        key: "publicOrderNoticeText",
        label: "Datenschutzhinweis im Bestellformular",
        hint: "Dieser Text wird im öffentlichen Bestellformular angezeigt und mit der Bestellung nachweisbar versioniert.",
        kind: "textarea",
        rows: 6,
        wide: true,
        placeholder:
          "Zweck, Empfänger, Speicherdauer und Kontaktmöglichkeit in klarer Sprache.",
      },
      {
        key: "consentTextVersion",
        label: "Textversion",
        hint: "Stabile Kennung des angezeigten Textes, zum Beispiel public-order-v1.",
        placeholder: "public-order-v1",
      },
      {
        key: "privacyContactEmail",
        label: "Datenschutz-Kontakt",
        hint: "Kontaktadresse für Datenschutzanfragen betroffener Personen.",
        kind: "email",
        placeholder: "datenschutz@verein.de",
      },
      {
        key: "privacyEvidenceId",
        label: "Nachweis der Datenschutzfreigabe",
        hint: "Referenz auf die dokumentierte Datenschutzprüfung; keine personenbezogenen oder vertraulichen Inhalte.",
        placeholder: "z. B. DATENSCHUTZ-2026-01",
        wide: true,
      },
    ],
  },
  {
    id: "privacy-page",
    name: "Datenschutzerklärung",
    intro:
      "Die öffentliche Seite /datenschutz für alle Besucher und Mitglieder. Die Vorlagen beschreiben nur, was LeonAid selbst tut; Angaben in [[ ]] muss der Verein ergänzen, sonst lässt sich die Version produktiv nicht aktivieren.",
    fields: [
      {
        key: "privacyPolicyText",
        label: "Datenschutzerklärung",
        hint: "Absätze durch eine Leerzeile trennen. „## “ am Zeilenanfang beginnt eine Überschrift, „- “ einen Listenpunkt.",
        kind: "textarea",
        rows: 18,
        wide: true,
      },
      {
        key: "memberPrivacyNoticeText",
        label: "Datenschutzhinweis für Mitglieder",
        hint: "Erscheint auf /datenschutz im Abschnitt für Mitglieder, verlinkt aus Verwaltung und Akquise-App. Er nennt auch, was die Akquise-App auf dem Gerät speichert.",
        kind: "textarea",
        rows: 14,
        wide: true,
      },
    ],
  },
  {
    id: "retention",
    name: "Aufbewahrungsfristen",
    intro:
      "Die Werte sind Tage. Vorbefüllte Vorschläge sind nicht automatisch rechtlich freigegeben.",
    fields: [
      retentionField(
        "invoiceRetentionDays",
        "Rechnungen",
        "Aufbewahrung ausgestellter Rechnungen und ihrer Dokumente.",
      ),
      retentionField(
        "commitmentRetentionDays",
        "Bestellungen & Zusagen",
        "Bestell- und Zusagedaten ohne Rechnungsbindung.",
      ),
      retentionField(
        "contactRetentionDays",
        "Kontakte",
        "Kontaktdaten nach Ende des aktiven Akquisezwecks.",
      ),
      retentionField(
        "consentEvidenceRetentionDays",
        "Einwilligungsnachweise",
        "Nachweise zu Hinweistexten, Einwilligungen und Sperren.",
      ),
      retentionField(
        "auditRetentionDays",
        "Protokoll",
        "Nachvollziehbarkeit sicherheitsrelevanter Änderungen.",
      ),
    ],
  },
  {
    id: "e-invoice",
    name: "E-Rechnung",
    intro:
      "LeonAid aktiviert ERP light nur, wenn fachlich bestätigt ist, dass keine E-Rechnung erforderlich ist. Eine Pflicht führt zu einem sichtbaren Stopp statt zu einer stillen Teillösung.",
    fields: [
      {
        key: "eInvoiceDecision",
        label: "E-Rechnung",
        hint: "Entscheidung aus der fachlichen Prüfung.",
        kind: "select",
        options: [
          ["pending", "Noch zu prüfen"],
          ["not_required", "Nicht erforderlich"],
          ["required", "Erforderlich"],
        ],
      },
      {
        key: "eInvoiceEvidenceId",
        label: "Nachweis-ID der Entscheidung",
        hint: "Referenz auf die dokumentierte Entscheidung. Solange die Entscheidung offen ist, bleibt das Feld leer; aktivieren lässt sich die Version erst mit Nachweis.",
        placeholder: "z. B. ERECHNUNG-2026-01",
        optional: true,
      },
    ],
  },
] as const satisfies readonly {
  readonly id: string;
  readonly name: string;
  readonly intro: string;
  readonly fields: readonly FieldSpec[];
}[];

type Part = (typeof PARTS)[number];
export type LegalPartId = Part["id"];

/** `/admin/legal[/<part>]` → the part shown; unknown parts fall back. */
export function legalPart(pathname: string): LegalPartId {
  const id = pathname.replace(/\/+$/, "").split("/admin/legal/")[1];
  return PARTS.find((part) => part.id === id)?.id ?? PARTS[0].id;
}

function earlierVersions(newest: number): string {
  return newest === 2 ? "Version 1" : `Version 1 bis ${newest - 1}`;
}

function shown(spec: FieldSpec, form: LegalForm): string {
  const raw = form[spec.key];
  if (raw === "") return "–";
  const option = spec.options?.find(([value]) => value === raw);
  if (option) return option[1];
  return spec.unit ? `${raw} ${spec.unit}` : raw;
}

function changedFields(
  part: Part,
  before: LegalForm | null,
  after: LegalForm | null,
): readonly FieldSpec[] {
  if (!after) return [];
  return part.fields.filter(
    (spec: FieldSpec) => !before || before[spec.key] !== after[spec.key],
  );
}

/** The first required field left empty, in list order. */
export function firstMissingField(
  form: LegalForm,
): { readonly part: Part; readonly spec: FieldSpec } | null {
  for (const part of PARTS) {
    for (const spec of part.fields as readonly FieldSpec[]) {
      if (!spec.optional && form[spec.key].trim() === "") return { part, spec };
    }
  }
  return null;
}

const fieldId = (key: FieldKey) => `legal-field-${key}`;

export interface LegalConfigurationPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

/**
 * Rechtliches (prototype pages/Legal.tsx): the installation's legal basis,
 * shown part by part. Changes start as a draft and become effective only
 * after a second system admin approves them (four eyes). The server
 * enforces that rule; this page only explains it and hides the approval
 * from the author.
 */
export function LegalConfigurationPage({
  client,
  identity,
}: LegalConfigurationPageProps) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const discard = useDiscardDialog("Sie");
  const approveFormId = useId();
  const href = useLocationHref();
  const partId = legalPart(href.split("?")[0] ?? "");
  const part = PARTS.find((item) => item.id === partId)!;

  const [form, setForm] = useState<LegalForm | null>(null);
  const [baseline, setBaseline] = useState<LegalForm | null>(null);
  const [approvalEvidence, setApprovalEvidence] = useState("");
  const [confirmActivate, setConfirmActivate] = useState(false);
  const [error, setError] = useState<ActionErrorMessage>();

  const configuration = useQuery({
    queryFn: () => client.getLegalConfiguration(),
    queryKey: ["legal-configuration"],
  });
  const loadError = useActionErrorMessage(configuration.error);

  const editing = form !== null;
  const dirty = editing && JSON.stringify(form) !== JSON.stringify(baseline);
  useLeaveGuard(dirty);

  const applyState = (state: LegalConfigurationStateResponse) =>
    queryClient.setQueryData(["legal-configuration"], state);
  const failed = (cause: unknown) => setError(actionErrorMessage(cause));

  const save = useMutation({
    mutationFn: (values: LegalForm) => {
      if (!configuration.data) throw new Error("Konfiguration fehlt.");
      return client.saveLegalConfigurationDraft(
        requestFromForm(values, configuration.data.revision),
      );
    },
    onSuccess: (state) => {
      applyState(state);
      setForm(null);
      setBaseline(null);
      setError(undefined);
      toast?.show({
        title: `Entwurf Version ${state.draft?.version ?? ""} gespeichert. Eine zweite Person muss ihn freigeben.`,
        tone: "success",
      });
    },
    onError: failed,
  });
  const approve = useMutation({
    mutationFn: () => {
      const state = configuration.data;
      if (!state?.draft) throw new Error("Entwurf fehlt.");
      return client.approveLegalConfigurationDraft(state.draft.id, {
        evidenceId: evidenceId(approvalEvidence),
        expectedRevision: state.revision,
      });
    },
    onSuccess: (state) => {
      applyState(state);
      setApprovalEvidence("");
      setError(undefined);
      toast?.show({ title: "Entwurf freigegeben.", tone: "success" });
    },
    onError: failed,
  });
  const activate = useMutation({
    mutationFn: () => {
      const state = configuration.data;
      if (!state?.draft) throw new Error("Entwurf fehlt.");
      return client.activateLegalConfigurationDraft(state.draft.id, {
        expectedRevision: state.revision,
      });
    },
    onSuccess: (state) => {
      applyState(state);
      setConfirmActivate(false);
      setError(undefined);
      toast?.show({
        title: `Version ${state.active?.version ?? ""} ist aktiv.`,
        tone: "success",
      });
    },
    onError: async (cause) => {
      setConfirmActivate(false);
      if (
        cause instanceof ApiError &&
        cause.detail.code === "legal_configuration_activation_blocked"
      ) {
        // The server lists codes; show the labelled blockers of the
        // current draft instead.
        const refreshed = await configuration.refetch();
        const blockers = refreshed.data?.draft?.values.activationBlockers ?? [];
        setError({
          code: cause.detail.code,
          conflict: true,
          message: blockers.length
            ? `Noch nicht aktivierbar: ${blockers
                .map((blocker) => blockerLabels[blocker] ?? blocker)
                .join(" ")}`
            : "Die Version ist noch nicht aktivierbar. Bitte laden Sie die Seite neu.",
          requestId: cause.detail.requestId,
        });
        return;
      }
      failed(cause);
    },
  });

  const go = useCallback((next: LegalPartId) => {
    const path = `/admin/legal/${next}`;
    if (window.location.pathname !== path) {
      navigateInPage(`${path}${window.location.search}`, { replace: true });
    }
  }, []);
  const index = PARTS.findIndex((item) => item.id === partId);
  useHotkeys(
    [
      {
        keys: "j",
        label: "Nächster Bereich",
        group: "Rechtliches",
        run: () => go(PARTS[Math.min(PARTS.length - 1, index + 1)]!.id),
      },
      {
        keys: "k",
        label: "Vorheriger Bereich",
        group: "Rechtliches",
        run: () => go(PARTS[Math.max(0, index - 1)]!.id),
      },
    ],
    [go, index],
  );

  const state = configuration.data;
  const startEditing = useCallback(() => {
    if (!state) return;
    const source = state.draft ?? state.active;
    const values = seedForEditing(
      source ? formFromValues(source.values) : emptyForm,
    );
    setForm(values);
    setBaseline(values);
    setError(undefined);
  }, [state]);
  useContextCommands(
    useMemo(
      () =>
        state && !editing
          ? [
              {
                id: "legal:edit",
                label: state.draft
                  ? "Rechtliches: Entwurf bearbeiten"
                  : "Rechtliches: Neuen Entwurf beginnen",
                group: "Rechtliches",
                run: startEditing,
              },
            ]
          : [],
      [editing, startEditing, state],
    ),
  );

  async function cancelEditing() {
    if (dirty && !(await discard.confirmDiscard())) return;
    setForm(null);
    setBaseline(null);
  }

  function submitDraft(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    // Only the shown part's fields are in the page, so the browser cannot
    // check the others; open the part with the first empty field instead.
    const missing = firstMissingField(form);
    if (missing) {
      setError({
        code: null,
        conflict: false,
        message: `Bitte füllen Sie „${missing.spec.label}“ im Bereich ${missing.part.name} aus.`,
        requestId: null,
      });
      go(missing.part.id);
      window.requestAnimationFrame(() =>
        document.getElementById(fieldId(missing.spec.key))?.focus(),
      );
      return;
    }
    save.mutate(form);
  }

  if (configuration.isPending) {
    return (
      <div className="legal">
        <LegalHeader count="Wird geladen …" />
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (configuration.isError || !state) {
    const forbidden =
      configuration.error instanceof ApiError &&
      configuration.error.status === 403;
    return (
      <div className="legal">
        <LegalHeader count="" />
        <ErrorState
          onRetry={forbidden ? undefined : () => void configuration.refetch()}
          title={
            forbidden
              ? "Nur für System-Admins"
              : "Rechtliche Angaben nicht erreichbar"
          }
        >
          {forbidden
            ? "Diese Angaben gelten für die gesamte LeonAid-Installation."
            : (loadError?.message ??
              "Die Konfiguration konnte gerade nicht geladen werden.")}
        </ErrorState>
      </div>
    );
  }

  const { active, draft, draftApproval } = state;
  const activeForm = active ? formFromValues(active.values) : null;
  const draftForm = draft ? formFromValues(draft.values) : null;
  const authoredByViewer = draft?.createdByUserId === identity.userId;
  const blockers = draft?.values.activationBlockers ?? [];
  // A version activated before newer requirements (e.g. the Impressum fields
  // of migration 0052) can be incomplete now; say so instead of hiding it.
  const activeBlockers = active?.values.activationBlockers ?? [];
  const changedParts = new Set(
    PARTS.filter(
      (item) => changedFields(item, activeForm, draftForm).length,
    ).map((item) => item.id),
  );
  const changes = changedFields(part, activeForm, draftForm);
  const current = activeForm ?? emptyForm;

  const headerCount = draft
    ? draftApproval
      ? `Entwurf Version ${draft.version} freigegeben, Aktivierung offen`
      : `Entwurf Version ${draft.version} wartet auf Freigabe`
    : "Keine offenen Entwürfe";

  return (
    <div className="legal" data-testid="legal-page">
      <LegalHeader count={headerCount} />
      <p className="small muted legal-intro">
        Angaben, die rechtlich wirken, ändern sich nur nach dem
        Vier-Augen-Prinzip: Eine Person entwirft, eine zweite gibt frei. Jede
        Version bleibt nachvollziehbar.
      </p>

      {active && activeBlockers.length ? (
        <div
          className="callout tone-warn legal-active-blockers"
          data-testid="legal-active-blockers"
          role="status"
        >
          <Icon icon={CircleAlert} size={16} />
          <span>
            <strong>
              Die aktive Version {active.version} ist unvollständig:
            </strong>{" "}
            {activeBlockers
              .map((blocker) => blockerLabels[blocker] ?? blocker)
              .join(" ")}{" "}
            Legen Sie einen neuen Entwurf an, lassen Sie ihn freigeben und
            aktivieren Sie ihn.
          </span>
        </div>
      ) : null}

      {error ? (
        <StatusMessage className="legal-error" tone="error">
          <strong>Änderung nicht abgeschlossen</strong>
          <p>{error.message}</p>
        </StatusMessage>
      ) : null}

      <div className="legal-layout">
        <nav
          aria-label="Bereiche der rechtlichen Angaben"
          className="legal-list"
        >
          <ul>
            {PARTS.map((item) => {
              const changed = changedParts.has(item.id);
              return (
                <li key={item.id}>
                  <a
                    aria-current={item.id === partId ? "page" : undefined}
                    className={
                      item.id === partId ? "legal-item is-active" : "legal-item"
                    }
                    href={`/admin/legal/${item.id}`}
                    onClick={(event) => {
                      event.preventDefault();
                      go(item.id);
                    }}
                  >
                    <StatusIcon
                      label={
                        changed ? "Entwurf wartet" : active ? "Aktiv" : "Offen"
                      }
                      status={changed ? "review" : active ? "done" : "open"}
                    />
                    <span className="legal-item-name">{item.name}</span>
                    <span className="legal-item-meta small muted">
                      {active ? `v${active.version}` : "noch nicht aktiv"}
                      {changed && draft ? ` · Entwurf v${draft.version}` : ""}
                    </span>
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>

        <section aria-labelledby="legal-title" className="legal-detail">
          <header className="legal-detail-header">
            <h2 id="legal-title">{part.name}</h2>
            {active ? (
              <Badge icon={CheckCircle2} tone="ok">
                Version {active.version} aktiv
              </Badge>
            ) : (
              <Badge icon={CircleAlert} tone="warn">
                Noch keine aktive Version
              </Badge>
            )}
          </header>
          <p className="small muted">{part.intro}</p>

          {editing ? (
            <form
              aria-labelledby="legal-edit-title"
              className="panel"
              data-testid="legal-editor"
              onSubmit={submitDraft}
            >
              <header className="panel-header">
                <h3 className="cluster" id="legal-edit-title">
                  <Icon icon={FilePen} size={16} />
                  {draft
                    ? `Entwurf Version ${draft.version} bearbeiten`
                    : "Neuer Entwurf"}
                </h3>
                {dirty ? <Badge tone="warn">Nicht gespeichert</Badge> : null}
              </header>
              <div className="panel-pad legal-fields">
                {part.fields.map((spec: FieldSpec) => (
                  <LegalField
                    disabled={
                      spec.key === "taxRatePercent" &&
                      form.taxTreatment !== "standard_vat"
                    }
                    key={spec.key}
                    onChange={(value) =>
                      setForm((prev) =>
                        prev ? { ...prev, [spec.key]: value } : prev,
                      )
                    }
                    spec={spec}
                    value={form[spec.key]}
                  />
                ))}
              </div>
              <footer className="panel-pad legal-edit-footer">
                <p className="small muted">
                  Gespeichert wird der ganze Entwurf mit allen Bereichen. Die
                  aktive Version bleibt unverändert, bis eine zweite Person
                  freigibt und die Version aktiviert wird.
                </p>
                <div className="cluster">
                  <Button
                    disabled={save.isPending}
                    onClick={() => void cancelEditing()}
                    variant="ghost"
                  >
                    Abbrechen
                  </Button>
                  <Button
                    icon={Save}
                    loading={save.isPending}
                    type="submit"
                    variant="primary"
                  >
                    Als Entwurf speichern
                  </Button>
                </div>
              </footer>
            </form>
          ) : draft ? (
            <div className="panel legal-draft" data-testid="legal-draft">
              <header className="panel-header">
                <h3 className="cluster">
                  <Icon icon={FilePen} size={16} />
                  Entwurf Version {draft.version}
                </h3>
                {draftApproval ? (
                  <Badge icon={ShieldCheck} tone="ok">
                    Freigegeben
                  </Badge>
                ) : (
                  <Badge icon={Clock} tone="warn">
                    Wartet auf zweite Freigabe
                  </Badge>
                )}
              </header>
              <div className="panel-pad stack">
                <DetailProps
                  items={[
                    {
                      label: "Geändert von",
                      value: draft.createdByDisplayName,
                    },
                    { label: "Am", value: formatDateTime(draft.createdAt) },
                    {
                      label: "Geänderte Bereiche",
                      value: changedParts.size
                        ? PARTS.filter((item) => changedParts.has(item.id))
                            .map((item) => item.name)
                            .join(", ")
                        : "Keine Abweichung zur aktiven Version",
                    },
                  ]}
                />
                <div>
                  <h4 className="legal-sub">Änderungen in diesem Bereich</h4>
                  {changes.length ? (
                    <div aria-label="Änderungen" className="diff" role="group">
                      {changes.map((spec) => (
                        <div className="diff-pair" key={spec.key}>
                          <p className="diff-label small muted">{spec.label}</p>
                          {activeForm ? (
                            <p className="diff-line is-removed">
                              <span className="sr-only">Bisher: </span>
                              <span aria-hidden="true">−</span>{" "}
                              {shown(spec, activeForm)}
                            </p>
                          ) : null}
                          <p className="diff-line is-added">
                            <span className="sr-only">Neu: </span>
                            <span aria-hidden="true">+</span>{" "}
                            {shown(spec, draftForm!)}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="small muted">
                      In diesem Bereich übernimmt der Entwurf die aktiven
                      Angaben.
                    </p>
                  )}
                </div>
                <div>
                  <h4 className="legal-sub">Freigaben</h4>
                  <ol className="approvals" data-testid="legal-approvals">
                    <li className="approval">
                      <StatusIcon label="Erledigt" status="done" />
                      <span>
                        1. Entwurf erstellt von {draft.createdByDisplayName}
                      </span>
                    </li>
                    <li className="approval">
                      <StatusIcon
                        label={draftApproval ? "Erledigt" : "Offen"}
                        status={draftApproval ? "done" : "open"}
                      />
                      <span>
                        {draftApproval
                          ? `2. Freigegeben von ${draftApproval.approvedByDisplayName} am ${formatDateTime(draftApproval.approvedAt)} · Nachweis ${draftApproval.evidenceId}`
                          : "2. Freigabe durch eine zweite Person mit Systemverwaltung"}
                      </span>
                    </li>
                    <li className="approval">
                      <StatusIcon label="Offen" status="open" />
                      <span>
                        3. Aktivierung: erst dann gilt die neue Version
                      </span>
                    </li>
                  </ol>
                </div>
                {blockers.length ? (
                  <div
                    className="callout tone-warn"
                    data-testid="legal-blockers"
                  >
                    <Icon icon={CircleAlert} size={16} />
                    <span>
                      <strong>Noch nicht aktivierbar:</strong>{" "}
                      {blockers
                        .map((blocker) => blockerLabels[blocker] ?? blocker)
                        .join(" ")}
                    </span>
                  </div>
                ) : null}
                {authoredByViewer && !draftApproval ? (
                  <div
                    className="callout tone-warn"
                    data-testid="legal-author-lock"
                  >
                    <Icon icon={Lock} size={16} />
                    <span>
                      {identity.displayName}, Sie haben diesen Entwurf erstellt.
                      Freigeben muss eine andere Person mit Systemverwaltung.
                    </span>
                  </div>
                ) : null}

                {!draftApproval && !authoredByViewer ? (
                  <form
                    className="stack"
                    id={approveFormId}
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (approvalEvidence.trim().length >= 3) approve.mutate();
                    }}
                  >
                    <Field
                      hint="Nur eine Referenz auf die fachliche Prüfung eintragen, keine vertraulichen Inhalte. Großbuchstaben, Ziffern und . _ : -"
                      label="Nachweis-ID der Freigabe"
                      required
                    >
                      <Input
                        autoComplete="off"
                        onChange={(event) =>
                          setApprovalEvidence(event.target.value)
                        }
                        placeholder="z. B. FREIGABE-2026-01"
                        value={approvalEvidence}
                      />
                    </Field>
                    <NextStep
                      action={
                        <Button
                          disabled={approvalEvidence.trim().length < 3}
                          form={approveFormId}
                          icon={ShieldCheck}
                          loading={approve.isPending}
                          type="submit"
                          variant="primary"
                        >
                          Entwurf freigeben
                        </Button>
                      }
                      alternatives={
                        <Button onClick={startEditing} variant="ghost">
                          Entwurf bearbeiten
                        </Button>
                      }
                      consequence={`Sie bestätigen als zweite Person die Änderungen von ${draft.createdByDisplayName}. Danach kann Version ${draft.version} aktiviert werden.`}
                      data-testid="legal-next-step"
                    />
                  </form>
                ) : draftApproval && blockers.length === 0 ? (
                  <NextStep
                    action={
                      <Button
                        icon={CheckCircle2}
                        loading={activate.isPending}
                        onClick={() => setConfirmActivate(true)}
                        variant="primary"
                      >
                        Version {draft.version} aktivieren
                      </Button>
                    }
                    consequence={`Version ${draft.version} gilt danach für alle neuen Rechnungen und Bestellungen.`}
                    data-testid="legal-next-step"
                  />
                ) : draftApproval ? (
                  <NextStep
                    action={
                      <Button
                        icon={FilePen}
                        onClick={startEditing}
                        variant="primary"
                      >
                        Entwurf bearbeiten
                      </Button>
                    }
                    consequence="Beheben Sie die offenen Punkte im Entwurf. Ein neuer Entwurf braucht wieder eine zweite Freigabe."
                    data-testid="legal-next-step"
                  />
                ) : (
                  <div className="cluster">
                    <Button
                      icon={FilePen}
                      onClick={startEditing}
                      variant="secondary"
                    >
                      Entwurf bearbeiten
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="panel panel-pad">
              <EmptyState
                action={
                  <Button
                    icon={FilePen}
                    onClick={startEditing}
                    variant="primary"
                  >
                    Neuen Entwurf beginnen
                  </Button>
                }
                description={
                  active
                    ? `Version ${active.version} ist aktiv. Änderungen beginnen als Entwurf und werden erst nach zweiter Freigabe wirksam.`
                    : "Es gibt noch keine aktive Grundlage. Legen Sie einen Entwurf an; eine zweite Person gibt ihn frei."
                }
                icon={FilePen}
                title="Kein offener Entwurf"
              />
            </div>
          )}

          {!editing ? (
            <section aria-labelledby="legal-current-title" className="panel">
              <header className="panel-header">
                <h3 id="legal-current-title">
                  {active
                    ? `Geltende Angaben · Version ${active.version}`
                    : "Geltende Angaben"}
                </h3>
              </header>
              <div className="panel-pad">
                {active ? (
                  <DetailProps
                    items={part.fields.map((spec: FieldSpec) => ({
                      label: spec.label,
                      value: shown(spec, current),
                    }))}
                  />
                ) : (
                  <p className="small muted">Noch keine Version aktiv.</p>
                )}
              </div>
            </section>
          ) : null}

          <section
            aria-labelledby="legal-history-title"
            className="legal-history"
          >
            <h3 className="cluster legal-sub" id="legal-history-title">
              <Icon icon={History} size={16} /> Versionen
            </h3>
            <ol className="timeline" data-testid="legal-versions">
              {draft ? (
                <li>
                  <span>
                    Version {draft.version} · Entwurf
                    <time dateTime={draft.createdAt}>
                      {formatDateTime(draft.createdAt)} ·{" "}
                      {draft.createdByDisplayName}
                    </time>
                  </span>
                </li>
              ) : null}
              {active ? (
                <li>
                  <span>
                    Version {active.version} · aktiv
                    <time dateTime={active.createdAt}>
                      erstellt {formatDateTime(active.createdAt)} ·{" "}
                      {active.createdByDisplayName}
                    </time>
                  </span>
                </li>
              ) : null}
              {/* Older numbers include drafts that were never in force, so
                  they are named neutrally; there is no history API yet. */}
              {(active?.version ?? draft?.version ?? 1) > 1 ? (
                <li>
                  <span>
                    {earlierVersions(active?.version ?? draft!.version)}
                    <time>
                      frühere Versionen, ohne Verlauf in dieser Ansicht
                    </time>
                  </span>
                </li>
              ) : null}
            </ol>
          </section>
          <p className="callout small">
            <Icon icon={Info} size={16} />
            <span>
              Bereits ausgestellte Rechnungen behalten die Angaben der Version,
              die beim Ausstellen galt.
            </span>
          </p>
        </section>
      </div>

      <ConfirmDialog
        confirmLabel="Jetzt aktivieren"
        description={`Version ${draft?.version ?? ""} wird sofort wirksam und gilt für alle neuen Rechnungen und Bestellungen. Die bisherige Version bleibt im Verlauf erhalten.`}
        onConfirm={() => activate.mutate()}
        onOpenChange={(open) => {
          if (!open && !activate.isPending) setConfirmActivate(false);
        }}
        open={confirmActivate}
        pending={activate.isPending}
        title={`Version ${draft?.version ?? ""} aktivieren?`}
      />
      {discard.dialog}
    </div>
  );
}

function LegalHeader({ count }: { readonly count: string }) {
  return (
    <header className="page-header">
      <div className="page-heading">
        <h1>Rechtliches</h1>
        {count ? <span className="page-count">{count}</span> : null}
      </div>
    </header>
  );
}

function LegalField({
  disabled,
  onChange,
  spec,
  value,
}: {
  readonly disabled?: boolean;
  readonly onChange: (value: string) => void;
  readonly spec: FieldSpec;
  readonly value: string;
}) {
  const common = {
    disabled,
    onChange: (
      event: ChangeEvent<
        HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
      >,
    ) => onChange(event.target.value),
    value,
  };
  return (
    <Field
      className={spec.wide ? "legal-field is-wide" : "legal-field"}
      hint={spec.hint}
      id={fieldId(spec.key)}
      label={spec.unit ? `${spec.label} (${spec.unit})` : spec.label}
      optional={spec.optional}
      required={!spec.optional}
    >
      {spec.kind === "select" ? (
        <Select {...common}>
          {spec.options!.map(([option, label]) => (
            <option key={option} value={option}>
              {label}
            </option>
          ))}
        </Select>
      ) : spec.kind === "textarea" ? (
        <Textarea {...common} placeholder={spec.placeholder} rows={spec.rows} />
      ) : (
        <Input
          {...common}
          autoComplete="off"
          max={spec.max}
          min={spec.min}
          placeholder={spec.placeholder}
          step={spec.step}
          type={spec.kind ?? "text"}
        />
      )}
    </Field>
  );
}
