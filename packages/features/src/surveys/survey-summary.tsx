import { SlidersHorizontal } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type {
  AggregateCount,
  AnalysisSnapshot,
  FreeTextItems,
  LeonAidApiClient,
  QuestionAggregate,
  ResponseSelection,
} from "@leonaid/api-client";
import {
  Button,
  ChartCanvas,
  ChartLegend,
  ChartTable,
  distributionConfig,
  Meter,
  stackedConfig,
  stackedSteps,
  type ChartTheme,
} from "@leonaid/ui";

import { useContextCommands } from "../command-palette/store";
import "./survey-summary.css";

/*
 * The evaluation of a frozen selection (prototype "Antworten" tab): one
 * panel per question. Every number comes disclosed from the server (k = 5):
 * a withheld count is null and shows as "< k"; a question with too few
 * answers shows only a note. Free-text quotes are for readers
 * (read_responses) only and load from their own endpoint.
 */

const TEXT_KINDS = new Set(["text", "comment"]);
const numberFormat = new Intl.NumberFormat("de-DE", {
  maximumFractionDigits: 1,
});
const n = (value: number) => numberFormat.format(value);

/**
 * One neutral marker for every withheld count: some are 1–4 people, others
 * are withheld because they would reveal those (review 5.6b, option A).
 */
const WITHHELD = "–";
function withheldText(_k: number) {
  return WITHHELD;
}
const shown = (value: number | null | undefined) =>
  value === null || value === undefined ? WITHHELD : n(value);

function countText(bucket: AggregateCount, k: number) {
  if (bucket.count === null) return withheldText(k);
  return bucket.percentage === null
    ? n(bucket.count)
    : `${n(bucket.count)} (${Math.round(bucket.percentage)} %)`;
}

function isNps(question: QuestionAggregate) {
  return (
    question.kind === "rating" &&
    (question.npsSegments != null ||
      (question.counts.length === 11 &&
        question.counts[0]?.value === 0 &&
        question.counts[10]?.value === 10))
  );
}

/** Prototype `Bars`: label, Meter, "n (x %)". */
function Bars({
  buckets,
  k,
  max,
  title,
}: {
  buckets: readonly AggregateCount[];
  k: number;
  max: number;
  title: string;
}) {
  return (
    <ul aria-label={title} className="bars">
      {buckets.map((bucket) => (
        <li key={String(bucket.value)}>
          <span className="bars-label">{bucket.label}</span>
          <Meter
            label={`${bucket.label}: ${
              bucket.count === null ? `weniger als ${k}` : countText(bucket, k)
            }`}
            max={max}
            value={bucket.count ?? 0}
          />
          <span className="bars-value num">
            {bucket.count === null ? (
              <span className="subtle">{withheldText(k)}</span>
            ) : (
              <>
                {n(bucket.count)}{" "}
                {bucket.percentage === null ? null : (
                  <span className="subtle">
                    ({Math.round(bucket.percentage)} %)
                  </span>
                )}
              </>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

function NpsPanel({ question, k }: { question: QuestionAggregate; k: number }) {
  const segments = question.npsSegments;
  const groups = [
    ["Kritiker (0–6)", segments?.detractors ?? null],
    ["Passive (7–8)", segments?.passives ?? null],
    ["Förderer (9–10)", segments?.promoters ?? null],
  ] as const;
  const share = (count: number | null) =>
    count === null || !question.answered
      ? null
      : (count / question.answered) * 100;
  const label = (count: number | null) =>
    count === null
      ? withheldText(k)
      : `${n(count)} (${Math.round(share(count) ?? 0)} %)`;
  const steps = stackedSteps(3, true);
  const segmentConfig = useCallback(
    (theme: ChartTheme) =>
      stackedConfig(
        [
          {
            label: question.title,
            segments: groups.map(([name, count]) => ({
              label: name,
              percentage: share(count),
            })),
          },
        ],
        theme,
        {
          withheldLabel: withheldText(k),
          showRowLabels: false,
          negativeFirst: true,
        },
      ),
    // groups and share derive from the question.
    [question, k],
  );
  const distribution = useCallback(
    (theme: ChartTheme) =>
      distributionConfig(
        question.counts.map((bucket) => ({
          label: bucket.label,
          count: bucket.count,
        })),
        theme,
        { withheldLabel: withheldText(k), unit: "Antworten" },
      ),
    [question, k],
  );
  return (
    <>
      <p className="answer-avg">
        <span className="num">
          {question.nps === null ? "–" : n(Math.round(question.nps))}
        </span>{" "}
        <span className="subtle small">Net Promoter Score (−100 bis 100)</span>
      </p>
      {segments ? (
        <figure className="svs-figure">
          <ChartCanvas
            config={segmentConfig}
            height={28}
            label={`${question.title}: ${groups
              .map(([name, count]) => `${name} ${label(count)}`)
              .join(", ")}.`}
          />
          <ChartLegend
            items={groups.map(([name, count], index) => ({
              label: name,
              value: label(count),
              step: steps[index]!,
            }))}
            label={`Legende: ${question.title}`}
          />
        </figure>
      ) : null}
      <figure className="svs-figure">
        <figcaption className="subtle small">Verteilung 0 bis 10</figcaption>
        <ChartCanvas
          config={distribution}
          height={140}
          label={`${question.title}, Verteilung: ${question.counts
            .map((bucket) => `${bucket.label}: ${countText(bucket, k)}`)
            .join(", ")}.`}
        />
        <ChartTable
          caption={question.title}
          columns={["Wert", "Anzahl"]}
          rows={question.counts.map((bucket) => [
            bucket.label,
            countText(bucket, k),
          ])}
        />
      </figure>
    </>
  );
}

function MatrixPanel({
  question,
  k,
}: {
  question: QuestionAggregate;
  k: number;
}) {
  const shown = question.matrixRows.filter((row) => !row.suppressed);
  const columns = shown[0]?.counts.map((bucket) => bucket.label) ?? [];
  const steps = stackedSteps(columns.length);
  const config = useCallback(
    (theme: ChartTheme) =>
      stackedConfig(
        shown.map((row) => ({
          label: row.label,
          segments: row.counts.map((bucket) => ({
            label: bucket.label,
            percentage: bucket.percentage,
          })),
        })),
        theme,
        { withheldLabel: withheldText(k) },
      ),
    // shown derives from the question.
    [question, k],
  );
  const hidden = question.matrixRows.filter((row) => row.suppressed);
  const partly = shown.filter((row) =>
    row.counts.some((bucket) => bucket.count === null),
  );
  return (
    <>
      {shown.length ? (
        <figure className="svs-figure">
          <ChartCanvas
            config={config}
            height={Math.max(48, shown.length * 34)}
            label={`${question.title}: ${shown
              .map(
                (row) =>
                  `${row.label} ${row.counts
                    .map((bucket) => `${bucket.label} ${countText(bucket, k)}`)
                    .join(", ")}`,
              )
              .join("; ")}.`}
          />
          <ChartLegend
            items={columns.map((column, index) => ({
              label: column,
              value: "",
              step: steps[index]!,
            }))}
            label={`Legende: ${question.title}`}
          />
          <ChartTable
            caption={question.title}
            columns={["Zeile", ...columns]}
            rows={shown.map((row) => [
              row.label,
              ...row.counts.map((bucket) => countText(bucket, k)),
            ])}
          />
        </figure>
      ) : null}
      {partly.length ? (
        <p className="svs-note">
          Ohne Anteil (unter {k} Personen oder daraus ableitbar):{" "}
          {partly
            .map(
              (row) =>
                `${row.label}: ${row.counts
                  .filter((bucket) => bucket.count === null)
                  .map((bucket) => bucket.label)
                  .join(", ")}`,
            )
            .join("; ")}
          .
        </p>
      ) : null}
      {hidden.length ? (
        <p className="svs-note">
          Ohne Auswertung (weniger als {k} gültige Antworten):{" "}
          {hidden.map((row) => row.label).join(", ")}.
        </p>
      ) : null}
    </>
  );
}

function Quotes({
  client,
  surveyId,
  selectionId,
  question,
}: {
  client: LeonAidApiClient;
  surveyId: string;
  selectionId: string;
  question: QuestionAggregate;
}) {
  const [texts, setTexts] = useState<FreeTextItems | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    client
      .listSurveyFreeText(
        surveyId,
        selectionId,
        question.questionId,
        {},
        {
          signal: controller.signal,
        },
      )
      .then((value) => {
        if (!controller.signal.aborted) setTexts(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [client, surveyId, selectionId, question.questionId]);
  const all = `/admin/surveys/${encodeURIComponent(surveyId)}/responses?responseSelection=${encodeURIComponent(selectionId)}&freeText=${encodeURIComponent(question.questionId)}`;
  if (failed)
    return (
      <p className="svs-note" role="status">
        Freitexte konnten nicht geladen werden.
      </p>
    );
  if (!texts)
    return (
      <p className="svs-note" role="status">
        Freitexte werden geladen …
      </p>
    );
  return (
    <>
      {texts.items.length ? (
        <ul className="answer-texts">
          {texts.items.slice(0, 6).map((item) => (
            <li key={item.participationId}>„{item.text}“</li>
          ))}
        </ul>
      ) : (
        <p className="svs-note">Keine Freitextantworten für diese Auswahl.</p>
      )}
      {texts.total > 0 ? (
        <a className="svs-more" href={all}>
          Alle {texts.total} Freitexte ansehen
        </a>
      ) : null}
    </>
  );
}

function QuestionPanel({
  index,
  question,
  k,
  quotes,
}: {
  index: number;
  question: QuestionAggregate;
  k: number;
  quotes: ReactNode;
}) {
  let body: ReactNode;
  if (question.suppressed) {
    body = (
      <p className="svs-note">
        Weniger als {k} gültige Antworten: Diese Frage wird nicht ausgewertet,
        damit niemand erkennbar wird.
      </p>
    );
  } else if (TEXT_KINDS.has(question.kind)) {
    body = quotes ?? (
      <p className="svs-note">
        {shown(question.answered)} Antworten (Freitext).
      </p>
    );
  } else if (question.kind === "matrix") {
    body = <MatrixPanel k={k} question={question} />;
  } else if (isNps(question)) {
    body = <NpsPanel k={k} question={question} />;
  } else if (question.kind === "rating") {
    // Prototype: hero average, then the scale from high to low.
    const top = question.counts.at(-1)?.label ?? "";
    body = (
      <>
        <p className="answer-avg">
          <span className="num">
            {question.mean === null ? "–" : n(question.mean)}
          </span>{" "}
          <span className="subtle small">Durchschnitt von {top}</span>
        </p>
        <Bars
          buckets={[...question.counts].reverse()}
          k={k}
          max={question.answered ?? 0}
          title={question.title}
        />
      </>
    );
  } else if (question.kind === "number") {
    // No minimum or maximum: each is one person's value (R6).
    body = (
      <dl className="svs-stats">
        <div>
          <dt>Durchschnitt</dt>
          <dd className="num">
            {question.mean === null ? "–" : n(question.mean)}
          </dd>
        </div>
      </dl>
    );
  } else if (question.kind === "date") {
    body = <p className="svs-note">{shown(question.answered)} Antworten.</p>;
  } else {
    // Single and multiple choice: largest first (prototype).
    const buckets = [...question.counts].sort(
      (a, b) => (b.count ?? 0) - (a.count ?? 0),
    );
    body = (
      <>
        {question.kind === "checkbox" ? (
          <p className="svs-note">
            Mehrfachauswahl: Anteile beziehen sich auf{" "}
            {shown(question.answered)} Antwortende.
          </p>
        ) : null}
        <Bars
          buckets={buckets}
          k={k}
          max={question.answered ?? 0}
          title={question.title}
        />
      </>
    );
  }
  return (
    <section
      aria-labelledby={`svs-q-${question.questionId}`}
      className="panel panel-pad svs-panel"
      data-question-id={question.questionId}
    >
      <h2 className="answer-q" id={`svs-q-${question.questionId}`}>
        {index + 1}. {question.title}
      </h2>
      {body}
    </section>
  );
}

export function SurveySummary({
  aggregates,
  applied,
  client,
  onChoose,
  selection,
  surveyId,
}: {
  aggregates: AnalysisSnapshot;
  applied: ReactNode;
  client: LeonAidApiClient;
  onChoose: () => void;
  /** Readers only: enables the free-text quotes. */
  selection: ResponseSelection | null;
  surveyId: string;
}) {
  const k = aggregates.minimumGroupSize ?? 5;
  useContextCommands(
    useMemo(
      () => [
        {
          id: "surveys:summary:choose",
          label: "Antwortstand wählen",
          group: "Auswertung",
          icon: SlidersHorizontal,
          run: onChoose,
        },
      ],
      [onChoose],
    ),
  );
  return (
    <div className="svs-page">
      <header className="page-header">
        <div className="page-heading">
          <h1>Auswertung</h1>
          <span className="page-count num">
            {aggregates.participationCount === null
              ? "Weniger als 5 Teilnahmen"
              : `${aggregates.participationCount} Teilnahmen`}
          </span>
        </div>
        <div className="page-actions">
          <Button
            icon={SlidersHorizontal}
            onClick={onChoose}
            variant="secondary"
          >
            Antwortstand wählen
          </Button>
        </div>
      </header>
      {applied}
      {aggregates.suppressed ? (
        <div className="callout" role="status">
          <span>
            Weniger als {k} Teilnahmen: Die Auswertung wird nicht gezeigt, damit
            niemand erkennbar wird.
          </span>
        </div>
      ) : (
        <>
          <p className="small muted">
            Auswertung ohne Namen. „{withheldText(k)}“ verborgen: unter {k}{" "}
            Personen oder daraus ableitbar.
          </p>
          <div className="answer-grid">
            {aggregates.questions.map((question, index) => (
              <QuestionPanel
                index={index}
                k={k}
                key={question.questionId}
                question={question}
                quotes={
                  selection && TEXT_KINDS.has(question.kind) ? (
                    <Quotes
                      client={client}
                      question={question}
                      selectionId={aggregates.id}
                      surveyId={surveyId}
                    />
                  ) : null
                }
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
