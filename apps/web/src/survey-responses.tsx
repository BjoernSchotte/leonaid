import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  type LeonAidApiClient,
  type ResponseSelection,
  type ResponseItems,
  type IndividualResponse,
  type FreeTextItems,
  type ResponseQuestion,
  type CreateAnalysisSnapshot,
} from "@leonaid/api-client";
import { Button } from "@leonaid/ui";
import type { ResponseStatus } from "@leonaid/surveys/contracts";

const statusLabels: Record<ResponseStatus, string> = {
  completed: "Abgeschlossen",
  partial: "Teilantwort",
  in_progress: "In Bearbeitung",
};
const localDate = (value: string | null) =>
  value
    ? new Date(
        new Date(value).getTime() - new Date(value).getTimezoneOffset() * 60000,
      )
        .toISOString()
        .slice(0, 16)
    : "";
function answerText(value: unknown, question: ResponseQuestion): string {
  if (value == null || value === "" || (Array.isArray(value) && !value.length))
    return "Nicht beantwortet";
  const choice = (item: unknown) =>
    question.choices.find(
      (c) => JSON.stringify(c.value) === JSON.stringify(item),
    )?.label ?? (typeof item === "string" ? item : JSON.stringify(item));
  if (Array.isArray(value)) return value.map(choice).join("\n");
  if (typeof value === "object" && !Object.keys(value).length)
    return "Nicht beantwortet";
  if (question.kind === "matrix" && typeof value === "object")
    return Object.entries(value)
      .map(
        ([row, item]) =>
          `${question.rows.find((r) => r.value === row)?.label ?? row}: ${choice(item)}`,
      )
      .join("\n");
  return choice(value);
}

export function SurveyResponses({
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
  const [statuses, setStatuses] = useState<ResponseStatus[]>([
    "partial",
    "completed",
  ]);
  const [from, setFrom] = useState("");
  const [before, setBefore] = useState("");
  const [isTest, setIsTest] = useState(false);
  const [selection, setSelection] = useState<ResponseSelection | null>(null);
  const [items, setItems] = useState<ResponseItems | null>(null);
  const [individual, setIndividual] = useState<IndividualResponse | null>(null);
  const [texts, setTexts] = useState<FreeTextItems | null>(null);
  const [questionId, setQuestionId] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(false);
  const running = useRef(false);
  const pending = useRef<CreateAnalysisSnapshot | null>(null);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  function remember(snapshotId: string, participationId?: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("responseSelection", snapshotId);
    if (participationId) url.searchParams.set("response", participationId);
    else url.searchParams.delete("response");
    history.replaceState(null, "", url);
  }
  function apply(meta: ResponseSelection, rows: ResponseItems) {
    setSelection(meta);
    setItems(rows);
    setIndividual(null);
    setTexts(null);
    setQuestionId(
      meta.questions.find((q) => ["text", "comment"].includes(q.kind))?.id ??
        "",
    );
  }
  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    void (async () => {
      try {
        const value = await client.listSurveyResponseVersions(
          surveyId,
          options,
        );
        if (controller.signal.aborted) return;
        setVersions(value.items);
        setVersion(value.items[0]?.id ?? "");
        const params = new URLSearchParams(location.search);
        const snapshotId = params.get("responseSelection");
        if (snapshotId) {
          const meta = await client.getSurveyResponseSelection(
            surveyId,
            snapshotId,
            options,
          );
          const rows = await client.listSurveyResponses(
            surveyId,
            snapshotId,
            {},
            options,
          );
          const responseId = params.get("response");
          const detail = responseId
            ? await client.getSurveyResponse(
                surveyId,
                snapshotId,
                responseId,
                options,
              )
            : null;
          if (controller.signal.aborted) return;
          apply(meta, rows);
          setIndividual(detail);
          setVersion(meta.filter.versionId);
          setStatuses(meta.filter.statuses);
          setFrom(localDate(meta.filter.createdFrom));
          setBefore(localDate(meta.filter.createdBefore));
          setIsTest(meta.filter.isTest);
        }
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(
            cause instanceof ApiError
              ? cause.detail.message
              : "Antworten konnten nicht geladen werden. Bitte öffnen Sie die Umfrage erneut.",
          );
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    })();
    return () => controller.abort();
  }, [client, surveyId]);

  async function run(operation: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (cause) {
      const uncertain = !(cause instanceof ApiError) || cause.status >= 500;
      setError(
        cause instanceof ApiError
          ? cause.detail.message
          : "Die Anfrage konnte nicht bestätigt werden. Bitte versuchen Sie es erneut.",
      );
      setRetry(Boolean(pending.current) && uncertain);
      if (!uncertain) {
        pending.current = null;
        setSelection(null);
        setItems(null);
        setIndividual(null);
        setTexts(null);
      }
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  async function create(repeat = false) {
    await run(async () => {
      if (!repeat) {
        const createdFrom = from ? new Date(from).toISOString() : null;
        const createdBefore = before ? new Date(before).toISOString() : null;
        if (createdFrom && createdBefore && createdFrom >= createdBefore) {
          setError("Das Ende des Zeitraums muss nach seinem Beginn liegen.");
          return;
        }
        pending.current = {
          operationId: crypto.randomUUID(),
          filter: {
            versionId: version,
            statuses,
            isTest: canTest && isTest,
            createdFrom,
            createdBefore,
          },
        };
      }
      if (!pending.current) return;
      const meta = await client.createSurveyResponseSelection(
        surveyId,
        pending.current,
      );
      const rows = await client.listSurveyResponses(surveyId, meta.id);
      apply(meta, rows);
      remember(meta.id);
      pending.current = null;
      setRetry(false);
    });
  }
  async function page(offset: number) {
    if (!selection) return;
    await run(async () => {
      const rows = await client.listSurveyResponses(surveyId, selection.id, {
        offset,
      });
      setItems(rows);
      setIndividual(null);
      remember(selection.id);
    });
  }
  async function open(participationId: string) {
    if (!selection) return;
    await run(async () => {
      setIndividual(null);
      const detail = await client.getSurveyResponse(
        surveyId,
        selection.id,
        participationId,
      );
      setIndividual(detail);
      remember(selection.id, participationId);
    });
  }
  async function freeText(offset = 0) {
    if (!selection || !questionId) return;
    await run(async () =>
      setTexts(
        await client.listSurveyFreeText(surveyId, selection.id, questionId, {
          offset,
        }),
      ),
    );
  }
  return (
    <section
      className="surveys-responses"
      aria-label="Einzelantworten und Freitext"
    >
      <h2>Einzelantworten und Freitext</h2>
      <p>
        Wählen Sie einen festen Antwortstand. Neue Antworten und spätere
        Änderungen erscheinen erst in einer neuen Auswahl.
      </p>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">Antworten werden geladen …</p>}
      {!busy && !versions.length && !error && (
        <p>Veröffentlichen Sie zuerst einen Fragebogen.</p>
      )}
      {versions.length > 0 && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <fieldset
            className="surveys-analysis-filters"
            disabled={busy || retry}
          >
            <legend>Antwortstand auswählen</legend>
            <label>
              Version der Einzelantworten
              <select
                value={version}
                onChange={(e) => setVersion(e.target.value)}
              >
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    Version {v.number}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="surveys-analysis-statuses">
              <legend>Teilnahmestatus</legend>
              {Object.entries(statusLabels).map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={statuses.includes(key as ResponseStatus)}
                    onChange={(e) =>
                      setStatuses((current) =>
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
              Begonnen ab
              <input
                type="datetime-local"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label>
              Begonnen vor
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
            <Button type="submit" disabled={!statuses.length}>
              Antworten auswählen
            </Button>
          </fieldset>
        </form>
      )}
      {retry && (
        <div className="surveys-actions">
          <Button disabled={busy} onClick={() => void create(true)}>
            Auswahl erneut anfordern
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
      {selection && items && (
        <>
          <p className="surveys-analysis-applied" role="status">
            Antwortstand: Version {selection.versionNumber} ·{" "}
            {selection.filter.statuses.map((s) => statusLabels[s]).join(", ")} ·{" "}
            {selection.filter.isTest ? "Testteilnahmen" : "Echte Teilnahmen"} ·{" "}
            {selection.total} Teilnahmen. Stand vom{" "}
            {new Date(selection.createdAt).toLocaleString("de-DE")} ({zone}).
            Zeitraum:{" "}
            {selection.filter.createdFrom
              ? new Date(selection.filter.createdFrom).toLocaleString("de-DE")
              : "offener Beginn"}{" "}
            bis vor{" "}
            {selection.filter.createdBefore
              ? new Date(selection.filter.createdBefore).toLocaleString("de-DE")
              : "offenes Ende"}
            .
          </p>
          {!items.items.length && (
            <p>Für diese Auswahl gibt es keine weiteren Antworten.</p>
          )}
          <ol className="surveys-response-list" start={items.offset + 1}>
            {items.items.map((item, index) => (
              <li key={item.participationId}>
                <span>
                  {statusLabels[item.status]} · begonnen am{" "}
                  {new Date(item.createdAt).toLocaleString("de-DE")}
                </span>
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void open(item.participationId)}
                >
                  Antwort {items.offset + index + 1} ansehen
                </Button>
              </li>
            ))}
          </ol>
          <nav className="surveys-actions" aria-label="Antwortseiten">
            <Button
              variant="secondary"
              disabled={busy || items.offset === 0}
              onClick={() => void page(Math.max(0, items.offset - 50))}
            >
              Vorherige Antworten
            </Button>
            <Button
              variant="secondary"
              disabled={
                busy || items.offset + items.items.length >= items.total
              }
              onClick={() => void page(items.offset + 50)}
            >
              Weitere Antworten
            </Button>
          </nav>
          {individual && (
            <section
              className="surveys-individual"
              aria-label="Geöffnete Einzelantwort"
            >
              <h3>Einzelantwort</h3>
              <p>
                {statusLabels[individual.status]} · begonnen am{" "}
                {new Date(individual.createdAt).toLocaleString("de-DE")}
              </p>
              <dl>
                {selection.questions.map((q) => (
                  <div key={q.id}>
                    <dt>{q.title}</dt>
                    <dd>{answerText(individual.answers[q.id], q)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}
          <section aria-label="Freitextantworten" className="surveys-free-text">
            <h3>Freitextantworten</h3>
            {selection.questions.some((q) =>
              ["text", "comment"].includes(q.kind),
            ) ? (
              <>
                <label>
                  Freitextfrage
                  <select
                    disabled={busy}
                    value={questionId}
                    onChange={(e) => {
                      setQuestionId(e.target.value);
                      setTexts(null);
                    }}
                  >
                    {selection.questions
                      .filter((q) => ["text", "comment"].includes(q.kind))
                      .map((q) => (
                        <option key={q.id} value={q.id}>
                          {q.title}
                        </option>
                      ))}
                  </select>
                </label>
                <Button
                  variant="secondary"
                  disabled={busy || retry}
                  onClick={() => void freeText()}
                >
                  Freitext laden
                </Button>
                {texts && (
                  <>
                    <p>{texts.total} Freitextantworten</p>
                    {texts.items.length ? (
                      <ol start={texts.offset + 1}>
                        {texts.items.map((item) => (
                          <li key={item.participationId}>
                            <p>{item.text}</p>
                            <Button
                              variant="secondary"
                              disabled={busy}
                              onClick={() => void open(item.participationId)}
                            >
                              Zugehörige Einzelantwort ansehen
                            </Button>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p>Keine Freitextantworten für diese Auswahl.</p>
                    )}
                    <nav
                      className="surveys-actions"
                      aria-label="Freitextseiten"
                    >
                      <Button
                        variant="secondary"
                        disabled={busy || texts.offset === 0}
                        onClick={() =>
                          void freeText(Math.max(0, texts.offset - 50))
                        }
                      >
                        Vorherige Freitexte
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={
                          busy ||
                          texts.offset + texts.items.length >= texts.total
                        }
                        onClick={() => void freeText(texts.offset + 50)}
                      >
                        Weitere Freitexte
                      </Button>
                    </nav>
                  </>
                )}
              </>
            ) : (
              <p>Dieser Fragebogen enthält keine Freitextfragen.</p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
