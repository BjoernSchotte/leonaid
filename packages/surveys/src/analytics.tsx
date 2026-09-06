import type { AnalysisSnapshot, QuestionAggregate } from "./contracts";

/** Host-supplied copy and formatting keep analytics independent of LeonAid. */
export interface AnalyticsMessages {
  heading: string;
  participants: string;
  statusOverview: string;
  inProgress: string;
  partial: string;
  completed: string;
  lastPageHint: string;
  relevant: string;
  answered: string;
  unanswered: string;
  hidden: string;
  invalid: string;
  choice: string;
  count: string;
  percentage: string;
  table: string;
  mean: string;
  minimum: string;
  maximum: string;
  nps: string;
  noValue: string;
  empty: string;
  multipleChoices: string;
  denominator: string;
  matrixDenominator: string;
  lastPage: string;
}

export const englishAnalytics: AnalyticsMessages = {
  heading: "Results",
  participants: "Selected participants",
  statusOverview:
    "Participants in this version, date range and data source, before status filtering",
  inProgress: "In progress",
  partial: "Partial responses",
  completed: "Completed",
  lastPageHint:
    "The last saved page can indicate where participation stopped; it does not explain why.",
  relevant: "Question shown",
  answered: "Valid answers",
  unanswered: "Unanswered",
  hidden: "Question hidden",
  invalid: "Invalid answers",
  choice: "Answer",
  count: "Count",
  percentage: "Share",
  table: "View data table",
  mean: "Mean",
  minimum: "Minimum",
  maximum: "Maximum",
  nps: "Net Promoter Score",
  noValue: "No valid answers",
  empty:
    "No participants match these filters. Select another version, period or status.",
  multipleChoices:
    "Multiple selections are possible; percentages can add up to more than 100%.",
  denominator: "Percentages use valid answers to this question.",
  matrixDenominator: "Percentages use valid answers in this row.",
  lastPage: "Last saved page",
};

function Distribution({
  counts,
  messages: m,
  formatNumber: n,
  label,
}: {
  counts: QuestionAggregate["counts"];
  messages: AnalyticsMessages;
  formatNumber: (value: number) => string;
  label: string;
}) {
  return (
    <>
      <div className="survey-analytics-bars" aria-hidden="true">
        {counts.map((bucket, index) => (
          <div className="survey-analytics-bar" key={index}>
            <span>{bucket.label}</span>
            <span className="survey-analytics-track">
              <span
                style={{
                  width: `${Math.max(0, Math.min(100, bucket.percentage ?? 0))}%`,
                }}
              />
            </span>
            <span>
              {n(bucket.count)} ·{" "}
              {bucket.percentage === null ? "—" : `${n(bucket.percentage)} %`}
            </span>
          </div>
        ))}
      </div>
      <details className="survey-analytics-table">
        <summary>
          {m.table} — {label}
        </summary>
        <div
          className="survey-analytics-scroll"
          tabIndex={0}
          role="region"
          aria-label={label}
        >
          <table>
            <caption>{label}</caption>
            <thead>
              <tr>
                <th scope="col">{m.choice}</th>
                <th scope="col">{m.count}</th>
                <th scope="col">{m.percentage}</th>
              </tr>
            </thead>
            <tbody>
              {counts.map((bucket, index) => (
                <tr key={index}>
                  <th scope="row">{bucket.label}</th>
                  <td>{n(bucket.count)}</td>
                  <td>
                    {bucket.percentage === null
                      ? m.noValue
                      : `${n(bucket.percentage)} %`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

/** Render only a frozen aggregate snapshot. This entrypoint never loads raw responses. */
export function SurveyAnalytics({
  snapshot,
  messages: m = englishAnalytics,
  locale = "en",
}: {
  snapshot: AnalysisSnapshot;
  messages?: AnalyticsMessages;
  locale?: string;
}) {
  const n = (value: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
  return (
    <section
      className="survey-analytics"
      aria-label={m.heading}
      data-snapshot-id={snapshot.id}
    >
      <section aria-label={m.statusOverview}>
        <p>{m.statusOverview}</p>
        <dl className="survey-analytics-counts">
          {(
            [
              ["in_progress", m.inProgress],
              ["partial", m.partial],
              ["completed", m.completed],
            ] as const
          ).map(([status, label]) => (
            <div key={status}>
              <dt>{label}</dt>
              <dd>{n(snapshot.statusCounts[status])}</dd>
            </div>
          ))}
        </dl>
      </section>
      <p className="survey-analytics-total">
        {m.participants}: <strong>{n(snapshot.participationCount)}</strong>
      </p>
      {snapshot.participationCount === 0 && <p role="status">{m.empty}</p>}
      {snapshot.questions.map((q) => (
        <section
          className="survey-analytics-question"
          key={q.questionId}
          aria-label={q.title}
          data-question-id={q.questionId}
        >
          <h3>{q.title}</h3>
          <dl className="survey-analytics-counts">
            {(
              [
                ["relevant", m.relevant],
                ["answered", m.answered],
                ["unanswered", m.unanswered],
                ["hidden", m.hidden],
                ["invalid", m.invalid],
              ] as const
            ).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{n(q[key])}</dd>
              </div>
            ))}
          </dl>
          {(q.kind === "number" || q.kind === "rating") && (
            <dl className="survey-analytics-metrics">
              {(
                [
                  ["mean", m.mean],
                  ["minimum", m.minimum],
                  ["maximum", m.maximum],
                  ...(q.nps !== null ||
                  (q.kind === "rating" &&
                    q.counts.length === 11 &&
                    q.counts[0]?.value === 0 &&
                    q.counts[10]?.value === 10)
                    ? [["nps", m.nps]]
                    : []),
                ] as ["mean" | "minimum" | "maximum" | "nps", string][]
              ).map(([key, label]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>{q[key] === null ? m.noValue : n(q[key])}</dd>
                </div>
              ))}
            </dl>
          )}
          {q.counts.length > 0 && (
            <>
              <p>
                {m.denominator} {q.kind === "checkbox" && m.multipleChoices}
              </p>
              <Distribution
                counts={q.counts}
                messages={m}
                formatNumber={n}
                label={q.title}
              />
            </>
          )}
          {q.matrixRows.map((row) => (
            <section key={row.rowId} aria-label={row.label}>
              <h4>{row.label}</h4>
              <p>
                {m.matrixDenominator} {m.answered}: {n(row.answered)} ·{" "}
                {m.unanswered}: {n(row.unanswered)} · {m.invalid}:{" "}
                {n(row.invalid)}
              </p>
              <Distribution
                counts={row.counts}
                messages={m}
                formatNumber={n}
                label={`${q.title} / ${row.label}`}
              />
            </section>
          ))}
        </section>
      ))}
      <section className="survey-analytics-question" aria-label={m.lastPage}>
        <h3>{m.lastPage}</h3>
        <p>{m.lastPageHint}</p>
        <Distribution
          counts={snapshot.lastPageCounts.map((page) => ({
            value: page.pageId,
            label: page.title,
            count: page.count,
            percentage: snapshot.participationCount
              ? (page.count / snapshot.participationCount) * 100
              : null,
          }))}
          messages={m}
          formatNumber={n}
          label={m.lastPage}
        />
      </section>
    </section>
  );
}
