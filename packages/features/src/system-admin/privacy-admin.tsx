import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  DatabaseExportIcon,
  Delete02Icon,
  File02Icon,
  LockIcon,
  Search01Icon,
  ShieldUserIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  type LeonAidApiClient,
  type PrivacyConsentResponse,
  type PrivacyErasureResponse,
  type PrivacySubjectReportResponse,
} from "@leonaid/api-client";
import { Button, ConfirmDialog, FormField, StatusMessage } from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";

export interface PrivacyAdminPageProps {
  readonly client: LeonAidApiClient;
}

const purposeLabels = {
  acquisition: "Akquise",
  marketing: "Marketing",
  public_order_fulfilment: "Öffentliche Bestellung",
} as const;

const referenceLabels = {
  activity: "Kontaktaktivität",
  assignment: "Akquise-Zuordnung",
  commitment: "Bestellung / Zusage",
  document: "Dokument",
  invoice: "Rechnung",
} as const;

function localDateTime(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function saveExport(report: PrivacySubjectReportResponse) {
  const blob = new Blob([JSON.stringify(report, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.download = `leonaid-datenauskunft-${new Date()
    .toISOString()
    .slice(0, 10)}.json`;
  anchor.href = url;
  anchor.click();
  URL.revokeObjectURL(url);
}

function EvidenceCard({
  consent,
  onRevoke,
  pending,
}: {
  readonly consent: PrivacyConsentResponse;
  readonly onRevoke: (consent: PrivacyConsentResponse) => void;
  readonly pending: boolean;
}) {
  const active = consent.revokedAt === null;
  return (
    <article className="privacy-evidence" data-consent-id={consent.id}>
      <div className="privacy-evidence__status">
        <span data-active={active}>{active ? "Aktiv" : "Gesperrt"}</span>
        <small>{purposeLabels[consent.purpose]}</small>
      </div>
      <div>
        <h3>
          {consent.evidenceKind === "notice_acknowledgement"
            ? "Datenschutzhinweis bestätigt"
            : "Einwilligungsnachweis"}
        </h3>
        <p>
          Textversion <strong>{consent.textVersion}</strong> · Quelle{" "}
          {consent.source}
        </p>
        <small>
          Erfasst {localDateTime(consent.grantedAt)}
          {consent.revokedAt
            ? ` · gesperrt ${localDateTime(consent.revokedAt)}`
            : ""}
        </small>
      </div>
      {active ? (
        <Button
          disabled={pending}
          onClick={() => onRevoke(consent)}
          variant="secondary"
        >
          Kontakt sperren
        </Button>
      ) : null}
    </article>
  );
}

export function PrivacyAdminPage({ client }: PrivacyAdminPageProps) {
  const [email, setEmail] = useState("");
  const [report, setReport] = useState<PrivacySubjectReportResponse | null>(
    null,
  );
  const [revokeTarget, setRevokeTarget] =
    useState<PrivacyConsentResponse | null>(null);
  const [erasureConfirmation, setErasureConfirmation] = useState("");
  const [eraseDialogOpen, setEraseDialogOpen] = useState(false);
  const [erasureResult, setErasureResult] =
    useState<PrivacyErasureResponse | null>(null);

  const lookup = useMutation({
    mutationFn: (subjectEmail: string) =>
      client.lookupPrivacySubject({ email: subjectEmail }),
    onSuccess: (data) => {
      setReport(data);
      setErasureResult(null);
      setErasureConfirmation("");
    },
  });
  const exportSubject = useMutation({
    mutationFn: (subjectEmail: string) =>
      client.exportPrivacySubject({ email: subjectEmail }),
    onSuccess: saveExport,
  });
  const revoke = useMutation({
    mutationFn: (consent: PrivacyConsentResponse) =>
      client.revokePrivacyConsent(consent.id, {
        reason: "Kontaktwunsch der betroffenen Person",
      }),
    onSuccess: async () => {
      setRevokeTarget(null);
      const refreshed = await client.lookupPrivacySubject({ email });
      setReport(refreshed);
    },
  });
  const erase = useMutation({
    mutationFn: () =>
      client.erasePrivacySubject({
        confirmation: erasureConfirmation,
        email,
      }),
    onSuccess: async (result) => {
      setEraseDialogOpen(false);
      setErasureResult(result);
      const refreshed = await client.lookupPrivacySubject({ email });
      setReport(refreshed);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const normalized = email.trim().toLowerCase();
    setEmail(normalized);
    lookup.mutate(normalized);
  }

  const operationError =
    lookup.error ?? exportSubject.error ?? revoke.error ?? erase.error;
  const error = operationError ? actionErrorMessage(operationError) : null;

  return (
    <div className="privacy-admin-page">
      <header className="privacy-admin-header">
        <div className="privacy-admin-header__icon" aria-hidden="true">
          <HugeiconsIcon icon={ShieldUserIcon} size={25} strokeWidth={1.8} />
        </div>
        <div>
          <p className="privacy-eyebrow">System · Datenschutz</p>
          <h1>Datenschutz-Vorgänge</h1>
          <p>
            Finde LeonAid-Daten über eine exakte E-Mail-Adresse, sperre
            Folgendkontakte und führe Auskunft oder Anonymisierung
            nachvollziehbar aus.
          </p>
        </div>
      </header>

      <section
        aria-labelledby="privacy-search-title"
        className="privacy-search-card"
      >
        <div>
          <p className="privacy-eyebrow">1 · Person finden</p>
          <h2 id="privacy-search-title">Exakte E-Mail-Adresse</h2>
          <p>
            Die Suche gleicht nur exakt ab. E-Mail-Adressen werden nicht in
            URLs, Logs oder Löschprotokollen abgelegt.
          </p>
        </div>
        <form className="privacy-search-form" onSubmit={submit}>
          <FormField
            description="Die Adresse aus der Anfrage der betroffenen Person."
            label="E-Mail-Adresse"
            required
          >
            <input
              autoComplete="off"
              data-testid="privacy-email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@unternehmen.de"
              type="email"
              value={email}
            />
          </FormField>
          <Button
            disabled={lookup.isPending}
            icon={
              <HugeiconsIcon aria-hidden="true" icon={Search01Icon} size={18} />
            }
            type="submit"
          >
            {lookup.isPending ? "Suche läuft …" : "Daten prüfen"}
          </Button>
        </form>
      </section>

      {error ? (
        <StatusMessage tone="error">
          <strong>Vorgang nicht abgeschlossen</strong>
          <p>{error.message}</p>
        </StatusMessage>
      ) : null}

      {report && !report.found ? (
        <StatusMessage tone="info">
          <strong>Keine LeonAid-Daten gefunden</strong>
          <p>
            Prüfe die Schreibweise. Die Suche enthält bewusst keine unscharfen
            Treffer.
          </p>
        </StatusMessage>
      ) : null}

      {report?.found ? (
        <>
          <section className="privacy-summary" data-testid="privacy-summary">
            <div>
              <p className="privacy-eyebrow">2 · Umfang verstehen</p>
              <h2>{report.subjectEmail}</h2>
              <p>
                {report.consents.length} Nachweis
                {report.consents.length === 1 ? "" : "e"},{" "}
                {report.references.length} fachliche Zuordnung
                {report.references.length === 1 ? "" : "en"}
              </p>
            </div>
            <Button
              disabled={exportSubject.isPending}
              icon={
                <HugeiconsIcon
                  aria-hidden="true"
                  icon={DatabaseExportIcon}
                  size={18}
                />
              }
              onClick={() => exportSubject.mutate(report.subjectEmail)}
              variant="secondary"
            >
              JSON-Auskunft laden
            </Button>
          </section>

          <div className="privacy-result-grid">
            <section
              aria-labelledby="privacy-evidence-title"
              className="privacy-panel"
            >
              <div className="privacy-panel__heading">
                <HugeiconsIcon aria-hidden="true" icon={LockIcon} size={20} />
                <div>
                  <h2 id="privacy-evidence-title">Nachweise & Sperren</h2>
                  <p>Version, Zweck, Quelle und Zeitpunkt bleiben sichtbar.</p>
                </div>
              </div>
              <div className="privacy-evidence-list">
                {report.consents.map((consent) => (
                  <EvidenceCard
                    consent={consent}
                    key={consent.id}
                    onRevoke={setRevokeTarget}
                    pending={revoke.isPending}
                  />
                ))}
              </div>
              {report.suppressions.length ? (
                <div className="privacy-suppression" role="status">
                  <strong>Folgendkontakt gesperrt</strong>
                  <p>
                    {report.suppressions
                      .map(
                        (item) =>
                          `${purposeLabels[item.purpose]} per ${item.channel}`,
                      )
                      .join(" · ")}
                  </p>
                </div>
              ) : null}
            </section>

            <section
              aria-labelledby="privacy-references-title"
              className="privacy-panel"
            >
              <div className="privacy-panel__heading">
                <HugeiconsIcon aria-hidden="true" icon={File02Icon} size={20} />
                <div>
                  <h2 id="privacy-references-title">Zugeordnete Daten</h2>
                  <p>
                    Nur Datensätze der exakt gefundenen Person werden
                    aufgeführt.
                  </p>
                </div>
              </div>
              <ul className="privacy-reference-list">
                {report.references.map((item) => (
                  <li key={item.id}>
                    <span>{referenceLabels[item.referenceType]}</span>
                    <strong>{item.label}</strong>
                    <small>{item.status ?? "Ohne Status"}</small>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section className="privacy-open-decisions">
            <HugeiconsIcon aria-hidden="true" icon={Alert02Icon} size={21} />
            <div>
              <h2>Offene Entscheidungen – keine Rechtsannahmen</h2>
              <ul>
                {report.openLegalDecisions.map((decision) => (
                  <li key={decision}>{decision}</li>
                ))}
              </ul>
            </div>
          </section>

          <section
            aria-labelledby="privacy-erasure-title"
            className="privacy-danger-zone"
          >
            <div>
              <p className="privacy-eyebrow">3 · Kontrolliert abschließen</p>
              <h2 id="privacy-erasure-title">Operative Daten anonymisieren</h2>
              <p>
                Bestell- und Kontaktdaten werden anonymisiert. Ausgestellte
                Rechnungen und ihre erzeugten PDFs bleiben unverändert
                zugeordnet.
              </p>
            </div>
            <div className="privacy-erasure-control">
              <FormField
                description="Zur Bestätigung die gefundene E-Mail-Adresse exakt wiederholen."
                label="Bestätigung"
              >
                <input
                  autoComplete="off"
                  data-testid="privacy-erasure-confirmation"
                  onChange={(event) =>
                    setErasureConfirmation(event.target.value)
                  }
                  placeholder={report.subjectEmail}
                  type="email"
                  value={erasureConfirmation}
                />
              </FormField>
              <Button
                disabled={
                  erasureResult !== null ||
                  erasureConfirmation !== report.subjectEmail
                }
                icon={
                  <HugeiconsIcon
                    aria-hidden="true"
                    icon={Delete02Icon}
                    size={18}
                  />
                }
                onClick={() => setEraseDialogOpen(true)}
                variant="danger"
              >
                {erasureResult
                  ? "Bereits anonymisiert"
                  : "Anonymisierung prüfen"}
              </Button>
            </div>
          </section>
        </>
      ) : null}

      {erasureResult ? (
        <StatusMessage tone="success">
          <HugeiconsIcon
            aria-hidden="true"
            icon={CheckmarkCircle02Icon}
            size={20}
          />
          <strong>Anonymisierung abgeschlossen</strong>
          <p>
            {erasureResult.anonymizedCommitments} operative Bestellung(en)
            anonymisiert; {erasureResult.retainedInvoiceIds.length} Rechnung(en)
            und {erasureResult.retainedDocumentIds.length} Dokument(e)
            unverändert erhalten.
          </p>
        </StatusMessage>
      ) : null}

      <ConfirmDialog
        confirmLabel="Kontakt jetzt sperren"
        description="E-Mail-Akquise und Marketing werden gesperrt. Der Nachweis bleibt mit dem Sperrzeitpunkt nachvollziehbar."
        onConfirm={() => revokeTarget && revoke.mutate(revokeTarget)}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
        open={revokeTarget !== null}
        pending={revoke.isPending}
        title="Folgendkontakt sperren?"
        tone="danger"
      />
      <ConfirmDialog
        confirmLabel="Operative Daten anonymisieren"
        description="Dieser Vorgang entfernt operative personenbezogene Inhalte. Ausgestellte Rechnungen und Rechnungs-PDFs bleiben unverändert erhalten."
        onConfirm={() => erase.mutate()}
        onOpenChange={setEraseDialogOpen}
        open={eraseDialogOpen}
        pending={erase.isPending}
        title="Anonymisierung verbindlich ausführen?"
        tone="danger"
      />
    </div>
  );
}
