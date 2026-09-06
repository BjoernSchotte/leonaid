import { useEffect, useRef, useState } from "react";
import { ApiError, type LeonAidApiClient } from "@leonaid/api-client";
import { Button } from "@leonaid/ui";
import {
  SurveyAnalytics,
  type AnalyticsMessages,
} from "@leonaid/surveys/analytics";
import type {
  AnalysisFilter,
  AnalysisSnapshot,
  ResponseStatus,
} from "@leonaid/surveys/contracts";
import "@leonaid/surveys/analytics-styles";

const messages: AnalyticsMessages = {
  statusOverview:
    "Teilnahmen dieser Version, dieses Zeitraums und dieser Antwortquelle vor dem Statusfilter",
  inProgress: "In Bearbeitung",
  partial: "Teilantworten",
  completed: "Abgeschlossen",
  lastPageHint:
    "Die zuletzt gespeicherte Seite kann zeigen, wo eine Teilnahme endete. Sie erklärt nicht den Grund.",
  heading: "Ergebnisse",
  participants: "Ausgewählte Teilnahmen",
  relevant: "Frage angezeigt",
  answered: "Gültig beantwortet",
  unanswered: "Unbeantwortet",
  hidden: "Frage ausgeblendet",
  invalid: "Ungültige Antworten",
  choice: "Antwort",
  count: "Anzahl",
  percentage: "Anteil",
  table: "Datentabelle anzeigen",
  mean: "Durchschnitt",
  minimum: "Minimum",
  maximum: "Maximum",
  nps: "Net Promoter Score",
  noValue: "Keine gültigen Antworten",
  empty:
    "Für diese Filter gibt es keine Teilnahmen. Wählen Sie eine andere Version, einen anderen Zeitraum oder Status.",
  multipleChoices:
    "Mehrfachauswahl ist möglich; die Anteile können zusammen mehr als 100 % ergeben.",
  denominator:
    "Die Anteile beziehen sich auf gültige Antworten zu dieser Frage.",
  matrixDenominator:
    "Die Anteile beziehen sich auf gültige Antworten in dieser Zeile.",
  lastPage: "Zuletzt gespeicherte Seite",
};
const statuses: Record<ResponseStatus, string> = {
  completed: "Abgeschlossen",
  partial: "Teilantworten",
  in_progress: "In Bearbeitung",
};
type Pending = { operationId: string; filter: AnalysisFilter };

export function SurveyAnalysis({
  client,
  surveyId,
  canTest,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  canTest: boolean;
}) {
  const [versions, setVersions] = useState<{ id: string; number: number }[]>(
    [],
  );
  const [version, setVersion] = useState("");
  const [selected, setSelected] = useState<ResponseStatus[]>([
    "partial",
    "completed",
  ]);
  const [isTest, setIsTest] = useState(false);
  const [from, setFrom] = useState("");
  const [before, setBefore] = useState("");
  const [snapshot, setSnapshot] = useState<AnalysisSnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const pending = useRef<Pending | null>(null);
  const inFlight = useRef(false);
  const [retry, setRetry] = useState(false);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void client
      .listSurveyAnalysisVersions(surveyId, { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return;
        setVersions(value.items);
        setVersion(value.items[0]?.id ?? "");
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "Versionen konnten nicht geladen werden. Bitte öffnen Sie die Umfrage erneut.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [client, surveyId]);

  async function analyze(repeat = false) {
    if (inFlight.current) return;
    if (!repeat) {
      const start = from ? new Date(from).toISOString() : null;
      const end = before ? new Date(before).toISOString() : null;
      if (start && end && start >= end) {
        setError("Das Ende des Zeitraums muss nach seinem Beginn liegen.");
        return;
      }
      pending.current = {
        operationId: crypto.randomUUID(),
        filter: {
          versionId: version,
          statuses: selected,
          isTest: canTest && isTest,
          createdFrom: start,
          createdBefore: end,
        },
      };
    }
    if (!pending.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const value = await client.createSurveyAnalysis(
        surveyId,
        pending.current,
      );
      setSnapshot(value as AnalysisSnapshot);
      pending.current = null;
      setRetry(false);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.detail.message
          : "Die Auswertung konnte nicht bestätigt werden. Bitte versuchen Sie es erneut.",
      );
      // A lost acknowledgement must repeat the exact operation and filter.
      const uncertain = !(cause instanceof ApiError) || cause.status >= 500;
      setRetry(uncertain);
      if (!uncertain) pending.current = null;
      // Never retain an earlier result after a permission or lifecycle rejection.
      if (cause instanceof ApiError && cause.status < 500) setSnapshot(null);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <section aria-label="Auswertung erstellen" className="surveys-analysis">
      <h2>Auswertung</h2>
      <p>
        Teilantworten und abgeschlossene Teilnahmen werden gemeinsam
        ausgewertet. Jede Auswertung hält den ausgewählten Stand fest.
      </p>
      {loading && <p role="status">Versionen werden geladen …</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && versions.length === 0 && !error && (
        <p>
          Veröffentlichen Sie zuerst einen Fragebogen, um Antworten auszuwerten.
        </p>
      )}
      {versions.length > 0 && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void analyze();
          }}
        >
          <fieldset
            disabled={busy || retry}
            className="surveys-analysis-filters"
          >
            <legend>Antworten auswählen</legend>
            <label>
              Fragebogen-Version
              <select
                value={version}
                onChange={(e) => setVersion(e.target.value)}
              >
                {versions.map((v) => (
                  <option value={v.id} key={v.id}>
                    Version {v.number}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="surveys-analysis-statuses">
              <legend>Teilnahmestatus</legend>
              {Object.entries(statuses).map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={selected.includes(key as ResponseStatus)}
                    onChange={(e) =>
                      setSelected((current) =>
                        e.target.checked
                          ? [...current, key as ResponseStatus]
                          : current.filter((s) => s !== key),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            <label>
              Teilnahme begonnen ab
              <input
                type="datetime-local"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label>
              Teilnahme begonnen vor
              <input
                type="datetime-local"
                value={before}
                onChange={(e) => setBefore(e.target.value)}
              />
            </label>
            {canTest && (
              <label>
                Antwortquelle
                <select
                  value={isTest ? "test" : "real"}
                  onChange={(e) => setIsTest(e.target.value === "test")}
                >
                  <option value="real">Echte Teilnahmen</option>
                  <option value="test">Nur Testteilnahmen</option>
                </select>
              </label>
            )}
            <p>
              Zeitzone: {zone}. Der Beginn zählt mit, der Endzeitpunkt nicht.
            </p>
            <Button type="submit" disabled={!selected.length}>
              {busy ? "Wird ausgewertet …" : "Auswertung erstellen"}
            </Button>
            {!selected.length && (
              <p role="status">Wählen Sie mindestens einen Teilnahmestatus.</p>
            )}
          </fieldset>
        </form>
      )}
      {retry && (
        <div className="surveys-actions">
          <Button disabled={busy} onClick={() => void analyze(true)}>
            Auswertung erneut anfordern
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => {
              pending.current = null;
              setRetry(false);
            }}
          >
            Filter neu wählen
          </Button>
        </div>
      )}
      {snapshot && (
        <>
          <div className="surveys-analysis-applied" role="status">
            <p>
              Ausgewerteter Stand: Version {snapshot.versionNumber} ·{" "}
              {snapshot.filter.statuses.map((s) => statuses[s]).join(", ")} ·{" "}
              {snapshot.filter.isTest ? "Testteilnahmen" : "Echte Teilnahmen"}
            </p>
            <p>
              Zeitraum:{" "}
              {snapshot.filter.createdFrom
                ? new Date(snapshot.filter.createdFrom).toLocaleString("de-DE")
                : "Offener Beginn"}{" "}
              bis vor{" "}
              {snapshot.filter.createdBefore
                ? new Date(snapshot.filter.createdBefore).toLocaleString(
                    "de-DE",
                  )
                : "offenes Ende"}
              . Stand vom {new Date(snapshot.createdAt).toLocaleString("de-DE")}{" "}
              ({zone}).
            </p>
          </div>
          <SurveyAnalytics
            snapshot={snapshot}
            messages={messages}
            locale="de-DE"
          />
        </>
      )}
    </section>
  );
}
