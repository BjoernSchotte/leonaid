import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  File02Icon,
  ShieldUserIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  type CurrentIdentityResponse,
  type LegalConfigurationValuesResponse,
  type LeonAidApiClient,
  type SaveLegalConfigurationDraftRequest,
} from "@leonaid/api-client";
import { Button, FormField, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

type Step = "carrier" | "privacy" | "release";

interface LegalForm {
  legalName: string;
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
}

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
  invoiceRetentionDays: "3650",
  issuerEmail: "",
  legalName: "",
  numberPrefix: "KT",
  numberWidth: "5",
  paymentTermsDays: "14",
  postalCode: "",
  privacyContactEmail: "",
  privacyEvidenceId: "",
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
  e_invoice_decision_pending: "E-Rechnungs-Pflicht ist noch nicht entschieden.",
  e_invoice_evidence_missing: "Der Nachweis zur E-Rechnungsentscheidung fehlt.",
  e_invoice_scope_required:
    "E-Rechnungen sind erforderlich; das liegt außerhalb des ERP-light-Piloten.",
  synthetic_or_placeholder_value:
    "Produktive Angaben enthalten noch Test- oder Platzhalterwerte.",
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
    invoiceRetentionDays: String(values.retention.invoiceDays),
    issuerEmail: values.issuer.email,
    legalName: values.issuer.legalName,
    numberPrefix: values.numberPrefix,
    numberWidth: String(values.numberWidth),
    paymentTermsDays: String(values.paymentTermsDays),
    postalCode: values.issuer.postalCode,
    privacyContactEmail: values.privacyContactEmail,
    privacyEvidenceId: values.privacyEvidenceId,
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
    eInvoiceEvidenceId: form.eInvoiceEvidenceId || null,
    expectedRevision: revision,
    iban: form.iban,
    issuer: {
      city: form.city,
      countryCode: form.countryCode.toUpperCase(),
      email: form.issuerEmail,
      legalName: form.legalName,
      postalCode: form.postalCode,
      streetLine1: form.streetLine1,
      taxIdentifier: form.taxIdentifier.toUpperCase(),
    },
    numberPrefix: form.numberPrefix.toUpperCase(),
    numberWidth: toInteger(form.numberWidth),
    paymentTermsDays: toInteger(form.paymentTermsDays),
    privacyContactEmail: form.privacyContactEmail,
    privacyEvidenceId: form.privacyEvidenceId.toUpperCase(),
    publicOrderLegalBasis: form.publicOrderLegalBasis,
    publicOrderNoticeText: form.publicOrderNoticeText,
    retention: {
      auditDays: toInteger(form.auditRetentionDays),
      commitmentDays: toInteger(form.commitmentRetentionDays),
      consentEvidenceDays: toInteger(form.consentEvidenceRetentionDays),
      contactDays: toInteger(form.contactRetentionDays),
      invoiceDays: toInteger(form.invoiceRetentionDays),
    },
    taxEvidenceId: form.taxEvidenceId.toUpperCase(),
    taxNote: form.taxNote,
    taxRateBasisPoints: Math.round(Number(form.taxRatePercent) * 100),
    taxTreatment: form.taxTreatment,
  };
}

function localDateTime(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export interface LegalConfigurationPageProps {
  readonly client: LeonAidApiClient;
  readonly identity: CurrentIdentityResponse;
}

export function LegalConfigurationPage({
  client,
  identity,
}: LegalConfigurationPageProps) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>("carrier");
  const [form, setForm] = useState<LegalForm>(emptyForm);
  const [loadedVersion, setLoadedVersion] = useState<string | null>(null);
  const [approvalEvidence, setApprovalEvidence] = useState("");

  const configuration = useQuery({
    queryFn: () => client.getLegalConfiguration(),
    queryKey: ["legal-configuration"],
  });

  useEffect(() => {
    if (!configuration.data) return;
    const source = configuration.data.draft ?? configuration.data.active;
    const versionKey = source?.id ?? "empty";
    if (loadedVersion === versionKey) return;
    setForm(source ? formFromValues(source.values) : emptyForm);
    setLoadedVersion(versionKey);
  }, [configuration.data, loadedVersion]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["legal-configuration"] });
  };
  const save = useMutation({
    mutationFn: (event: FormEvent) => {
      event.preventDefault();
      if (!configuration.data) throw new Error("Konfiguration fehlt.");
      return client.saveLegalConfigurationDraft(
        requestFromForm(form, configuration.data.revision),
      );
    },
    onSuccess: async (state) => {
      setLoadedVersion(state.draft?.id ?? null);
      setStep("release");
      await refresh();
    },
  });
  const approve = useMutation({
    mutationFn: () => {
      if (!configuration.data?.draft) throw new Error("Entwurf fehlt.");
      return client.approveLegalConfigurationDraft(
        configuration.data.draft.id,
        {
          evidenceId: approvalEvidence.toUpperCase(),
          expectedRevision: configuration.data.revision,
        },
      );
    },
    onSuccess: refresh,
  });
  const activate = useMutation({
    mutationFn: () => {
      if (!configuration.data?.draft) throw new Error("Entwurf fehlt.");
      return client.activateLegalConfigurationDraft(
        configuration.data.draft.id,
        { expectedRevision: configuration.data.revision },
      );
    },
    onSuccess: refresh,
  });

  const operationError = save.error ?? approve.error ?? activate.error;
  const error = operationError ? actionErrorMessage(operationError) : null;

  function update<K extends keyof LegalForm>(key: K, value: LegalForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  if (configuration.isPending) {
    return (
      <div aria-live="polite" className="action-loading" role="status">
        <span aria-hidden="true" />
        <h1>Organisationsdaten werden geladen</h1>
        <p>LeonAid prüft aktive Version und Freigabestatus.</p>
      </div>
    );
  }

  if (configuration.isError) {
    const forbidden =
      configuration.error instanceof ApiError &&
      configuration.error.status === 403;
    return (
      <main className="ui-main">
        <StatusMessage tone="error">
          <h1>
            {forbidden
              ? "Nur für System-Admins"
              : "Organisationsdaten nicht erreichbar"}
          </h1>
          <p>
            {forbidden
              ? "Diese Angaben gelten für die gesamte LeonAid-Installation."
              : "Die Konfiguration konnte gerade nicht geladen werden."}
          </p>
        </StatusMessage>
      </main>
    );
  }

  const state = configuration.data;
  const draftOwnedByCurrentUser =
    state.draft?.createdByUserId === identity.userId;
  const blockers = state.draft?.values.activationBlockers ?? [];

  return (
    <div className="legal-page">
      <header className="legal-header">
        <div className="legal-header__icon" aria-hidden="true">
          <HugeiconsIcon icon={File02Icon} size={25} strokeWidth={1.8} />
        </div>
        <div>
          <p className="legal-eyebrow">System · verbindliche Grundlage</p>
          <h1>Organisation & Recht</h1>
          <p>
            Lege Träger-, Rechnungs- und Datenschutzgrundlagen einmal sauber
            fest. Änderungen werden erst nach Vier-Augen-Freigabe wirksam.
          </p>
        </div>
        <div className="legal-version-badge">
          <span>
            {state.active ? `Version ${state.active.version}` : "Noch offen"}
          </span>
          <small>{state.active ? "aktiv" : "keine aktive Grundlage"}</small>
        </div>
      </header>

      <nav aria-label="Abschnitte" className="legal-steps">
        {(
          [
            ["carrier", "1", "Träger & Rechnung"],
            ["privacy", "2", "Datenschutz & Fristen"],
            ["release", "3", "Prüfen & freigeben"],
          ] as const
        ).map(([key, number, label]) => (
          <button
            aria-current={step === key ? "step" : undefined}
            key={key}
            onClick={() => setStep(key)}
            type="button"
          >
            <span>{number}</span>
            {label}
          </button>
        ))}
      </nav>

      {error ? (
        <StatusMessage tone="error">
          <strong>Änderung nicht abgeschlossen</strong>
          <p>{error.message}</p>
        </StatusMessage>
      ) : null}

      <form className="legal-form" onSubmit={(event) => save.mutate(event)}>
        {step === "carrier" ? (
          <section aria-labelledby="legal-carrier-title">
            <div className="legal-section-heading">
              <p className="legal-eyebrow">Schritt 1</p>
              <h2 id="legal-carrier-title">Wer stellt die Rechnung?</h2>
              <p>
                Diese Angaben erscheinen später im unveränderlichen
                Rechnungssnapshot. Sie gelten installationsweit.
              </p>
            </div>
            <div className="legal-field-grid">
              <FormField
                description="Der vollständige juristische Name des Vereins oder Trägers – genau wie auf Rechnungen."
                label="Name des Trägers"
                required
              >
                <input
                  onChange={(event) => update("legalName", event.target.value)}
                  placeholder="z. B. Förderverein Lions Club Musterstadt e. V."
                  value={form.legalName}
                />
              </FormField>
              <FormField
                description="Zentrale Kontaktadresse für Rückfragen zu ausgestellten Rechnungen."
                label="Rechnungs-E-Mail"
                required
              >
                <input
                  onChange={(event) =>
                    update("issuerEmail", event.target.value)
                  }
                  placeholder="rechnung@verein.de"
                  type="email"
                  value={form.issuerEmail}
                />
              </FormField>
              <FormField
                className="legal-field--wide"
                description="Straße und Hausnummer der ladungsfähigen Anschrift."
                label="Anschrift"
                required
              >
                <input
                  onChange={(event) =>
                    update("streetLine1", event.target.value)
                  }
                  placeholder="Musterstraße 12"
                  value={form.streetLine1}
                />
              </FormField>
              <FormField
                description="Postleitzahl der Trägeranschrift."
                label="Postleitzahl"
                required
              >
                <input
                  onChange={(event) => update("postalCode", event.target.value)}
                  placeholder="86150"
                  value={form.postalCode}
                />
              </FormField>
              <FormField
                description="Ort der Trägeranschrift."
                label="Ort"
                required
              >
                <input
                  onChange={(event) => update("city", event.target.value)}
                  placeholder="Augsburg"
                  value={form.city}
                />
              </FormField>
              <FormField
                description="Zweistelliger Ländercode; für Deutschland DE."
                label="Land"
                required
              >
                <input
                  maxLength={2}
                  onChange={(event) =>
                    update("countryCode", event.target.value)
                  }
                  placeholder="DE"
                  value={form.countryCode}
                />
              </FormField>
              <FormField
                description="Steuernummer oder Umsatzsteuer-ID, wie von der Steuerberatung bestätigt."
                label="Steuerkennung"
                required
              >
                <input
                  onChange={(event) =>
                    update("taxIdentifier", event.target.value)
                  }
                  placeholder="z. B. 103/123/45678"
                  value={form.taxIdentifier}
                />
              </FormField>
            </div>

            <div className="legal-subsection">
              <h3>Zahlung & Nummernkreis</h3>
              <div className="legal-field-grid">
                <FormField
                  description="Name, unter dem das Vereinskonto geführt wird."
                  label="Kontoinhaber"
                  required
                >
                  <input
                    onChange={(event) =>
                      update("bankAccountHolder", event.target.value)
                    }
                    placeholder="Förderverein Lions Club Musterstadt e. V."
                    value={form.bankAccountHolder}
                  />
                </FormField>
                <FormField
                  description="Leerzeichen sind erlaubt; LeonAid speichert die IBAN normalisiert."
                  label="IBAN"
                  required
                >
                  <input
                    autoComplete="off"
                    onChange={(event) => update("iban", event.target.value)}
                    placeholder="DE12 3456 7890 1234 5678 90"
                    value={form.iban}
                  />
                </FormField>
                <FormField
                  description="Optional bei inländischen Zahlungen; acht oder elf Zeichen."
                  label="BIC"
                >
                  <input
                    onChange={(event) => update("bic", event.target.value)}
                    placeholder="GENODEF1XXX"
                    value={form.bic}
                  />
                </FormField>
                <FormField
                  description="Kurzes Kürzel am Anfang jeder Rechnungsnummer."
                  label="Rechnungspräfix"
                  required
                >
                  <input
                    onChange={(event) =>
                      update("numberPrefix", event.target.value)
                    }
                    placeholder="KT"
                    value={form.numberPrefix}
                  />
                </FormField>
                <FormField
                  description="Anzahl der Ziffern nach dem Präfix, zum Beispiel 00001."
                  label="Nummernlänge"
                  required
                >
                  <input
                    max={8}
                    min={3}
                    onChange={(event) =>
                      update("numberWidth", event.target.value)
                    }
                    type="number"
                    value={form.numberWidth}
                  />
                </FormField>
                <FormField
                  description="Zeit zwischen Rechnungsdatum und gewünschtem Zahlungseingang."
                  label="Zahlungsziel in Tagen"
                  required
                >
                  <input
                    max={120}
                    min={1}
                    onChange={(event) =>
                      update("paymentTermsDays", event.target.value)
                    }
                    type="number"
                    value={form.paymentTermsDays}
                  />
                </FormField>
              </div>
            </div>

            <div className="legal-subsection">
              <h3>Steuerliche Behandlung</h3>
              <div className="legal-field-grid">
                <FormField
                  description="Nur entsprechend der schriftlichen steuerlichen Einordnung auswählen."
                  label="Umsatzsteuer"
                  required
                >
                  <select
                    onChange={(event) =>
                      update(
                        "taxTreatment",
                        event.target.value as LegalForm["taxTreatment"],
                      )
                    }
                    value={form.taxTreatment}
                  >
                    <option value="tax_exempt">Steuerbefreit</option>
                    <option value="small_business">
                      Kein Ausweis nach § 19 UStG
                    </option>
                    <option value="standard_vat">Regelbesteuerung</option>
                  </select>
                </FormField>
                <FormField
                  description="Nur bei Regelbesteuerung größer als 0; sonst 0."
                  label="Steuersatz in Prozent"
                  required
                >
                  <input
                    disabled={form.taxTreatment !== "standard_vat"}
                    max={100}
                    min={0}
                    onChange={(event) =>
                      update("taxRatePercent", event.target.value)
                    }
                    step="0.01"
                    type="number"
                    value={form.taxRatePercent}
                  />
                </FormField>
                <FormField
                  className="legal-field--wide"
                  description="Der bestätigte Hinweis, der auf jeder Rechnung zur steuerlichen Behandlung erscheint."
                  label="Steuerhinweis"
                  required
                >
                  <textarea
                    onChange={(event) => update("taxNote", event.target.value)}
                    placeholder="z. B. Kein Ausweis von Umsatzsteuer aufgrund …"
                    rows={3}
                    value={form.taxNote}
                  />
                </FormField>
                <FormField
                  className="legal-field--wide"
                  description="Referenz auf Protokoll, Datei oder Ticket der fachlichen Steuerfreigabe; keine vertraulichen Inhalte eintragen."
                  label="Nachweis der Steuerfreigabe"
                  required
                >
                  <input
                    onChange={(event) =>
                      update("taxEvidenceId", event.target.value)
                    }
                    placeholder="z. B. STEUER-2026-01"
                    value={form.taxEvidenceId}
                  />
                </FormField>
              </div>
            </div>
          </section>
        ) : null}

        {step === "privacy" ? (
          <section aria-labelledby="legal-privacy-title">
            <div className="legal-section-heading">
              <p className="legal-eyebrow">Schritt 2</p>
              <h2 id="legal-privacy-title">Welche Regeln gelten für Daten?</h2>
              <p>
                Hier wird die installationsweite Grundlage gepflegt. Auskunft,
                Sperre und Löschung einzelner Personen bleiben unter
                „Datenschutz“.
              </p>
            </div>
            <div className="legal-field-grid">
              <FormField
                className="legal-field--wide"
                description="Beschreibt knapp, auf welcher Rechtsgrundlage öffentliche Bestellungen verarbeitet werden."
                label="Rechtsgrundlage für öffentliche Bestellungen"
                required
              >
                <textarea
                  onChange={(event) =>
                    update("publicOrderLegalBasis", event.target.value)
                  }
                  placeholder="z. B. Vertragserfüllung nach Art. 6 Abs. 1 lit. b DSGVO"
                  rows={2}
                  value={form.publicOrderLegalBasis}
                />
              </FormField>
              <FormField
                className="legal-field--wide"
                description="Dieser verständliche Text wird im öffentlichen Bestellformular angezeigt und mit der Bestellung nachweisbar versioniert."
                label="Datenschutzhinweis im Bestellformular"
                required
              >
                <textarea
                  onChange={(event) =>
                    update("publicOrderNoticeText", event.target.value)
                  }
                  placeholder="Erkläre Zweck, Empfänger, Speicherdauer und Kontaktmöglichkeit in klarer Sprache."
                  rows={6}
                  value={form.publicOrderNoticeText}
                />
              </FormField>
              <FormField
                description="Stabile Kennung des angezeigten Textes, zum Beispiel public-order-v1."
                label="Textversion"
                required
              >
                <input
                  onChange={(event) =>
                    update("consentTextVersion", event.target.value)
                  }
                  placeholder="public-order-v1"
                  value={form.consentTextVersion}
                />
              </FormField>
              <FormField
                description="Kontaktadresse, die Betroffene für Datenschutzanfragen verwenden."
                label="Datenschutz-Kontakt"
                required
              >
                <input
                  onChange={(event) =>
                    update("privacyContactEmail", event.target.value)
                  }
                  placeholder="datenschutz@verein.de"
                  type="email"
                  value={form.privacyContactEmail}
                />
              </FormField>
              <FormField
                className="legal-field--wide"
                description="Referenz auf die dokumentierte Datenschutzprüfung; keine personenbezogenen oder vertraulichen Inhalte eintragen."
                label="Nachweis der Datenschutzfreigabe"
                required
              >
                <input
                  onChange={(event) =>
                    update("privacyEvidenceId", event.target.value)
                  }
                  placeholder="z. B. DATENSCHUTZ-2026-01"
                  value={form.privacyEvidenceId}
                />
              </FormField>
            </div>

            <div className="legal-subsection">
              <h3>Aufbewahrungsfristen</h3>
              <p className="legal-subsection__intro">
                Die Werte sind Tage. Die vorbefüllten Vorschläge sind nicht
                automatisch rechtlich freigegeben.
              </p>
              <div className="legal-field-grid legal-field-grid--retention">
                {(
                  [
                    [
                      "invoiceRetentionDays",
                      "Rechnungen",
                      "Aufbewahrung ausgestellter Rechnungen und ihrer Dokumente.",
                    ],
                    [
                      "commitmentRetentionDays",
                      "Bestellungen & Zusagen",
                      "Fachliche Bestell- und Zusagedaten ohne Rechnungsbindung.",
                    ],
                    [
                      "contactRetentionDays",
                      "Kontakte",
                      "Kontaktdaten nach Ende des aktiven Akquisezwecks.",
                    ],
                    [
                      "consentEvidenceRetentionDays",
                      "Einwilligungsnachweise",
                      "Nachweise zu Hinweistexten, Einwilligungen und Sperren.",
                    ],
                    [
                      "auditRetentionDays",
                      "Audit-Ereignisse",
                      "Technische Nachvollziehbarkeit sicherheitsrelevanter Änderungen.",
                    ],
                  ] as const
                ).map(([key, label, description]) => (
                  <FormField description={description} key={key} label={label}>
                    <input
                      max={36500}
                      min={1}
                      onChange={(event) => update(key, event.target.value)}
                      type="number"
                      value={form[key]}
                    />
                  </FormField>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        {step === "release" ? (
          <section aria-labelledby="legal-release-title">
            <div className="legal-section-heading">
              <p className="legal-eyebrow">Schritt 3</p>
              <h2 id="legal-release-title">Prüfen, freigeben, aktivieren</h2>
              <p>
                Speichern erzeugt eine neue, unveränderliche Version. Eine
                zweite Person muss sie fachlich freigeben.
              </p>
            </div>

            <div className="legal-release-grid">
              <article className="legal-release-panel">
                <div className="legal-release-panel__heading">
                  <span data-complete={Boolean(state.draft)}>1</span>
                  <div>
                    <h3>Entwurf</h3>
                    <p>
                      {state.draft
                        ? `Version ${state.draft.version}, gespeichert von ${state.draft.createdByDisplayName} am ${localDateTime(state.draft.createdAt)}`
                        : "Noch kein Entwurf gespeichert."}
                    </p>
                  </div>
                </div>
                <Button
                  disabled={save.isPending}
                  onClick={() => setStep("carrier")}
                  type="button"
                  variant="secondary"
                >
                  Angaben prüfen
                </Button>
              </article>

              <article className="legal-release-panel">
                <div className="legal-release-panel__heading">
                  <span data-complete={Boolean(state.draftApproval)}>2</span>
                  <div>
                    <h3>Vier-Augen-Freigabe</h3>
                    <p>
                      {state.draftApproval
                        ? `Freigegeben von ${state.draftApproval.approvedByDisplayName} · ${state.draftApproval.evidenceId}`
                        : draftOwnedByCurrentUser
                          ? "Eine andere System-Administration muss diesen Entwurf freigeben."
                          : "Bestätige die externe fachliche Prüfung mit einer Nachweis-ID."}
                    </p>
                  </div>
                </div>
                {!state.draftApproval &&
                state.draft &&
                !draftOwnedByCurrentUser ? (
                  <div className="legal-approval-control">
                    <FormField
                      description="Nur eine Referenz eintragen, keine vertraulichen Prüfinhalte."
                      label="Nachweis-ID der Freigabe"
                      required
                    >
                      <input
                        onChange={(event) =>
                          setApprovalEvidence(event.target.value)
                        }
                        placeholder="z. B. FREIGABE-2026-01"
                        value={approvalEvidence}
                      />
                    </FormField>
                    <Button
                      disabled={
                        approve.isPending || approvalEvidence.trim().length < 3
                      }
                      onClick={() => approve.mutate()}
                      type="button"
                      variant="secondary"
                    >
                      Entwurf freigeben
                    </Button>
                  </div>
                ) : null}
              </article>

              <article className="legal-release-panel">
                <div className="legal-release-panel__heading">
                  <span data-complete={Boolean(state.active)}>3</span>
                  <div>
                    <h3>Aktivierung</h3>
                    <p>
                      Erst die aktive Version darf später als Grundlage neuer
                      Aktions- und Rechnungskonfigurationen dienen.
                    </p>
                  </div>
                </div>
                {blockers.length ? (
                  <ul className="legal-blockers">
                    {blockers.map((blocker) => (
                      <li key={blocker}>
                        <HugeiconsIcon
                          aria-hidden="true"
                          icon={Alert02Icon}
                          size={17}
                        />
                        {blockerLabels[blocker] ?? blocker}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="legal-ready">
                    <HugeiconsIcon
                      aria-hidden="true"
                      icon={CheckmarkCircle02Icon}
                      size={18}
                    />
                    Keine technischen Aktivierungsblocker.
                  </p>
                )}
                <Button
                  disabled={
                    !state.draft ||
                    !state.draftApproval ||
                    blockers.length > 0 ||
                    activate.isPending
                  }
                  onClick={() => activate.mutate()}
                  type="button"
                >
                  Version verbindlich aktivieren
                </Button>
              </article>
            </div>

            <aside className="legal-einvoice">
              <HugeiconsIcon
                aria-hidden="true"
                icon={ShieldUserIcon}
                size={21}
              />
              <div>
                <h3>E-Rechnungs-Grenze des Piloten</h3>
                <p>
                  LeonAid aktiviert ERP light nur, wenn fachlich bestätigt ist,
                  dass keine E-Rechnung erforderlich ist. Eine Pflicht führt zu
                  einem sichtbaren Stopp statt zu einer stillen Teillösung.
                </p>
              </div>
              <FormField
                description="Entscheidung aus der fachlichen Prüfung."
                label="E-Rechnung"
                required
              >
                <select
                  onChange={(event) =>
                    update(
                      "eInvoiceDecision",
                      event.target.value as LegalForm["eInvoiceDecision"],
                    )
                  }
                  value={form.eInvoiceDecision}
                >
                  <option value="pending">Noch zu prüfen</option>
                  <option value="not_required">Nicht erforderlich</option>
                  <option value="required">Erforderlich</option>
                </select>
              </FormField>
              <FormField
                description="Referenz auf die dokumentierte Entscheidung."
                label="Nachweis-ID"
                required
              >
                <input
                  onChange={(event) =>
                    update("eInvoiceEvidenceId", event.target.value)
                  }
                  placeholder="z. B. ERECHNUNG-2026-01"
                  value={form.eInvoiceEvidenceId}
                />
              </FormField>
            </aside>
          </section>
        ) : null}

        <footer className="legal-form-footer">
          <div>
            <strong>Als neuen Entwurf speichern</strong>
            <span>
              Die aktive Version bleibt unverändert, bis der neue Entwurf
              freigegeben und aktiviert wurde.
            </span>
          </div>
          <Button disabled={save.isPending} type="submit">
            {save.isPending
              ? "Entwurf wird gespeichert …"
              : "Entwurf speichern"}
          </Button>
        </footer>
      </form>
    </div>
  );
}
