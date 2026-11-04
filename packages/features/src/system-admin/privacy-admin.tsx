import { useMutation } from "@tanstack/react-query";
import {
  Database,
  Download,
  FileSearch,
  Info,
  Search,
  ShieldAlert,
  UserX,
} from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import type {
  LeonAidApiClient,
  PrivacyConsentResponse,
  PrivacyErasureResponse,
  PrivacySubjectReportResponse,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  ConfirmDialog,
  DetailProps,
  EmptyState,
  Field,
  Icon,
  Input,
  Modal,
  NextStep,
  StatusMessage,
  useOptionalToast,
} from "@leonaid/ui";

import {
  actionErrorMessage,
  type ActionErrorMessage,
} from "../action-admin/errors";
import { formatDateTime } from "../shared/dates";

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
  inbox_case: "Eingang (Anfrage)",
  invoice: "Rechnung",
} as const;

const channelLabels = {
  email: "E-Mail",
  phone: "Telefon",
  postal: "Post",
} as const;

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

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

/**
 * Datenschutz (prototype System.tsx Privacy): exact-address lookup,
 * Auskunft, Kontaktsperre and anonymization. Invoices stay untouched
 * (statutory retention); the server checks the confirmation and asks for
 * a fresh sign-in.
 */
export function PrivacyTab({ client }: PrivacyAdminPageProps) {
  const toast = useOptionalToast();
  const eraseFormId = useId();
  const [email, setEmail] = useState("");
  const [inputError, setInputError] = useState("");
  const [report, setReport] = useState<PrivacySubjectReportResponse | null>(
    null,
  );
  const [error, setError] = useState<ActionErrorMessage>();
  const [revokeTarget, setRevokeTarget] =
    useState<PrivacyConsentResponse | null>(null);
  const [eraseOpen, setEraseOpen] = useState(false);
  const [erasureConfirmation, setErasureConfirmation] = useState("");
  const [erasureResult, setErasureResult] =
    useState<PrivacyErasureResponse | null>(null);
  const failed = (cause: unknown) => setError(actionErrorMessage(cause));

  const lookup = useMutation({
    mutationFn: (subjectEmail: string) =>
      client.lookupPrivacySubject({ email: subjectEmail }),
    onSuccess: (data) => {
      setReport(data);
      setErasureResult(null);
      setErasureConfirmation("");
    },
    onError: failed,
  });
  const exportSubject = useMutation({
    mutationFn: (subjectEmail: string) =>
      client.exportPrivacySubject({ email: subjectEmail }),
    onSuccess: (data) => {
      saveExport(data);
      toast?.show({
        title: "Auskunft erstellt und heruntergeladen.",
        tone: "success",
      });
    },
    onError: failed,
  });
  const revoke = useMutation({
    mutationFn: (consent: PrivacyConsentResponse) =>
      client.revokePrivacyConsent(consent.id, {
        reason: "Kontaktwunsch der betroffenen Person",
      }),
    onSuccess: async () => {
      setRevokeTarget(null);
      toast?.show({
        title:
          "Kontakt gesperrt. Keine Akquise und kein Marketing mehr an diese Adresse.",
        tone: "success",
      });
      setReport(await client.lookupPrivacySubject({ email }));
    },
    onError: (cause) => {
      setRevokeTarget(null);
      failed(cause);
    },
  });
  const erase = useMutation({
    mutationFn: () =>
      client.erasePrivacySubject({ confirmation: erasureConfirmation, email }),
    onSuccess: async (result) => {
      setEraseOpen(false);
      setErasureResult(result);
      toast?.show({
        title: "Daten anonymisiert. Protokolleintrag erstellt.",
        tone: "success",
      });
      setReport(await client.lookupPrivacySubject({ email }));
    },
    onError: (cause) => {
      setEraseOpen(false);
      failed(cause);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const normalized = email.trim().toLowerCase();
    if (!EMAIL.test(normalized)) {
      setInputError(
        "Bitte eine vollständige E-Mail-Adresse eingeben. Gesucht wird nur nach exakter Übereinstimmung.",
      );
      return;
    }
    setInputError("");
    setError(undefined);
    setEmail(normalized);
    lookup.mutate(normalized);
  }

  const busy =
    lookup.isPending ||
    exportSubject.isPending ||
    revoke.isPending ||
    erase.isPending;

  return (
    <div className="privacy">
      <form className="privacy-search" noValidate onSubmit={submit}>
        <Field
          error={inputError || undefined}
          hint="Die Adresse aus der Anfrage der betroffenen Person. Gesucht wird nur nach exakter Übereinstimmung."
          label="E-Mail-Adresse der betroffenen Person"
        >
          <Input
            autoComplete="off"
            data-testid="privacy-email"
            id="privacy-email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@unternehmen.de"
            type="email"
            value={email}
          />
        </Field>
        <Button
          icon={Search}
          loading={lookup.isPending}
          type="submit"
          variant="primary"
        >
          Nachweise suchen
        </Button>
      </form>

      {error ? (
        <StatusMessage tone="error">
          <strong>Vorgang nicht abgeschlossen</strong>
          <p>{error.message}</p>
        </StatusMessage>
      ) : null}

      {erasureResult ? (
        <StatusMessage tone="success">
          <strong>Anonymisierung abgeschlossen</strong>
          <p>
            {erasureResult.anonymizedCommitments} operative Bestellung(en)
            anonymisiert; {erasureResult.retainedInvoiceIds.length} Rechnung(en)
            und {erasureResult.retainedDocumentIds.length} Dokument(e) gemäß
            freigegebener Frist von {erasureResult.retention.invoiceDays} Tagen
            unverändert erhalten.
          </p>
        </StatusMessage>
      ) : null}

      {report === null ? (
        <EmptyState
          description="Geben Sie die exakte E-Mail-Adresse ein. Sie sehen dann Einwilligungen, Kontaktsperren und gespeicherte Bestellungen dieser Person."
          icon={FileSearch}
          title="Nach einer Person suchen"
        />
      ) : !report.found ? (
        <EmptyState
          description={
            <>
              Zu <strong>{report.subjectEmail || email}</strong> sind keine
              Nachweise, Bestellungen oder Kontakte gespeichert. Die Suche
              enthält bewusst keine unscharfen Treffer.
            </>
          }
          icon={FileSearch}
          title="Keine Daten zu dieser Adresse"
        />
      ) : (
        <>
          {!erasureResult ? (
            <NextStep
              action={
                <Button
                  disabled={busy}
                  icon={Download}
                  loading={exportSubject.isPending}
                  onClick={() => exportSubject.mutate(report.subjectEmail)}
                  variant="primary"
                >
                  Auskunft erstellen
                </Button>
              }
              alternatives={
                <Button
                  disabled={busy}
                  icon={UserX}
                  onClick={() => {
                    setErasureConfirmation("");
                    setEraseOpen(true);
                  }}
                  variant="danger"
                >
                  Anonymisieren …
                </Button>
              }
              consequence="Auskunft als JSON herunterladen, Kontakte sperren oder die operativen Daten anonymisieren. Rechnungen bleiben unverändert (gesetzliche Aufbewahrung)."
              data-testid="privacy-next-step"
            />
          ) : null}

          <div className="system-grid">
            <section
              aria-labelledby="privacy-subject-title"
              className="panel"
              data-testid="privacy-summary"
            >
              <header className="panel-header">
                <h2 className="mono" id="privacy-subject-title">
                  {report.subjectEmail}
                </h2>
                {erasureResult ? (
                  <span className="stamp tone-neutral">Anonymisiert</span>
                ) : (
                  <Badge tone="info">
                    {report.consents.length}{" "}
                    {report.consents.length === 1 ? "Nachweis" : "Nachweise"}
                  </Badge>
                )}
              </header>
              <ul className="svc-list" aria-label="Nachweise und Sperren">
                {report.consents.map((consent) => {
                  const active = consent.revokedAt === null;
                  return (
                    <li
                      className="svc-row"
                      data-consent-id={consent.id}
                      key={consent.id}
                    >
                      <Icon icon={active ? Info : ShieldAlert} size={16} />
                      <span className="svc-name">
                        {consent.evidenceKind === "notice_acknowledgement"
                          ? "Datenschutzhinweis zur Kenntnis genommen"
                          : "Einwilligung"}{" "}
                        · {purposeLabels[consent.purpose]}
                      </span>
                      <span className="svc-state">
                        {active ? (
                          <Button
                            disabled={busy}
                            onClick={() => setRevokeTarget(consent)}
                            size="sm"
                          >
                            Kontakt sperren
                          </Button>
                        ) : (
                          <Badge tone="warn">Gesperrt</Badge>
                        )}
                      </span>
                      <span className="svc-detail small muted">
                        Textversion{" "}
                        <span className="mono">{consent.textVersion}</span> ·{" "}
                        {consent.source} · erfasst{" "}
                        {formatDateTime(consent.grantedAt)}
                        {consent.revokedAt
                          ? ` · gesperrt ${formatDateTime(consent.revokedAt)}`
                          : ""}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <div className="panel-pad stack">
                {report.suppressions.length ? (
                  <div className="callout tone-warn" role="status">
                    <Icon icon={ShieldAlert} size={16} />
                    <span>
                      <strong>Folgendkontakt gesperrt:</strong>{" "}
                      {report.suppressions
                        .map(
                          (item) =>
                            `${purposeLabels[item.purpose]} per ${channelLabels[item.channel]}`,
                        )
                        .join(" · ")}
                    </span>
                  </div>
                ) : null}
                <DetailProps
                  items={report.references.map((item) => ({
                    label: referenceLabels[item.referenceType],
                    value: (
                      <span>
                        <span className="mono">{item.label}</span>
                        {item.status ? (
                          <span className="subtle"> ({item.status})</span>
                        ) : null}
                      </span>
                    ),
                  }))}
                />
                <div className="callout">
                  <Icon icon={Info} size={16} />
                  <span>
                    Rechnungen bleiben unverändert erhalten (gesetzliche
                    Aufbewahrung). Eine Anonymisierung ersetzt nur Kontaktdaten
                    außerhalb der Rechnungsbelege.
                  </span>
                </div>
              </div>
            </section>

            <section
              aria-labelledby="privacy-retention-title"
              className="panel"
              data-testid="privacy-retention"
            >
              <header className="panel-header">
                <h2 id="privacy-retention-title">Aufbewahrung</h2>
                <span className="small muted">
                  Freigegebene Rechtsgrundlage · Version{" "}
                  {report.retention.legalConfigurationVersion}
                </span>
              </header>
              <div className="panel-pad">
                <DetailProps
                  items={[
                    {
                      label: "Rechnungen & PDFs",
                      value: `${report.retention.invoiceDays} Tage`,
                    },
                    {
                      label: "Bestellungen",
                      value: `${report.retention.commitmentDays} Tage`,
                    },
                    {
                      label: "Kontaktdaten",
                      value: `${report.retention.contactDays} Tage`,
                    },
                    {
                      label: "Einwilligungsnachweise",
                      value: `${report.retention.consentEvidenceDays} Tage`,
                    },
                    {
                      label: "Protokoll",
                      value: `${report.retention.auditDays} Tage`,
                    },
                  ]}
                />
              </div>
            </section>

            <section aria-labelledby="open-title" className="panel">
              <header className="panel-header">
                <h2 id="open-title">Offene Entscheidungen</h2>
              </header>
              <ul className="panel-pad stack small">
                {report.openLegalDecisions.map((decision) => (
                  <li className="cluster" key={decision}>
                    <Icon icon={Database} size={14} />
                    {decision}
                  </li>
                ))}
                <li className="cluster">
                  <Icon icon={Database} size={14} />
                  Löschung im CRM (Twenty) erfolgt noch manuell durch die
                  Systemverwaltung.
                </li>
              </ul>
            </section>
          </div>
        </>
      )}

      <ConfirmDialog
        confirmLabel="Kontakt jetzt sperren"
        description="Akquise und Marketing per E-Mail werden gesperrt. Der Nachweis bleibt mit dem Sperrzeitpunkt nachvollziehbar."
        onConfirm={() => revokeTarget && revoke.mutate(revokeTarget)}
        onOpenChange={(open) =>
          !open && !revoke.isPending && setRevokeTarget(null)
        }
        open={revokeTarget !== null}
        pending={revoke.isPending}
        title="Folgendkontakt sperren?"
        tone="danger"
      />
      <Modal
        description="Bestell- und Kontaktdaten werden unwiderruflich anonymisiert. Ausgestellte Rechnungen und ihre PDFs bleiben unverändert erhalten."
        footer={
          <>
            <Button
              disabled={erase.isPending}
              onClick={() => setEraseOpen(false)}
              variant="ghost"
            >
              Abbrechen
            </Button>
            <Button
              disabled={erasureConfirmation !== report?.subjectEmail}
              form={eraseFormId}
              icon={UserX}
              loading={erase.isPending}
              type="submit"
              variant="danger"
            >
              Verbindlich anonymisieren
            </Button>
          </>
        }
        onClose={() => {
          if (!erase.isPending) setEraseOpen(false);
        }}
        open={eraseOpen && Boolean(report?.found)}
        role="alertdialog"
        size="sm"
        title="Operative Daten anonymisieren?"
      >
        <form
          id={eraseFormId}
          onSubmit={(event) => {
            event.preventDefault();
            if (erasureConfirmation === report?.subjectEmail) erase.mutate();
          }}
        >
          <Field
            hint="Zur Bestätigung die gefundene E-Mail-Adresse exakt wiederholen."
            label="Bestätigung"
          >
            <Input
              autoComplete="off"
              data-testid="privacy-erasure-confirmation"
              onChange={(event) => setErasureConfirmation(event.target.value)}
              placeholder={report?.subjectEmail}
              type="email"
              value={erasureConfirmation}
            />
          </Field>
        </form>
      </Modal>
    </div>
  );
}
