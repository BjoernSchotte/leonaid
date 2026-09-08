import type { JsonValue, QuestionAggregate } from "./contracts";
import { profileAnswerError, type ProfileQuestion } from "./answer-validation";
import { createSurveyModel, restoreSurveyAnswers } from "./model";

const absent = (value: unknown) =>
  value === undefined || value === null || value === "" ||
  (Array.isArray(value) && value.length === 0) ||
  (typeof value === "object" && value !== null && Object.keys(value).length === 0);

function label(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const localized = value as Record<string, unknown>;
    for (const key of ["de", "default", "en"])
      if (typeof localized[key] === "string") return localized[key];
  }
  return fallback;
}

function options(items: unknown): QuestionAggregate["counts"] {
  if (!Array.isArray(items)) return [];
  return items.map((item) => {
    const object = item && typeof item === "object" && !Array.isArray(item);
    const value = (object ? item.value : item) as JsonValue;
    return { value, label: label(object ? item.text : undefined, String(value)), count: 0, percentage: null };
  });
}

function initial(question: ProfileQuestion): QuestionAggregate {
  const kind = question.type === "text" ? String(question.inputType ?? "text") : question.type;
  let counts = options(question.choices);
  if (kind === "rating") {
    const low = Number(question.rateMin ?? 1), high = Number(question.rateMax ?? 5);
    const step = Number(question.rateStep ?? 1);
    counts = Array.from({ length: Math.floor((high - low) / step + 1e-9) + 1 }, (_, i) => {
      const value = Number((low + i * step).toPrecision(14));
      return { value, label: String(value), count: 0, percentage: null };
    });
  }
  return {
    questionId: question.name, title: label(question.title, question.name), kind,
    relevant: 0, answered: 0, unanswered: 0, hidden: 0, invalid: 0,
    counts, sum: null, mean: null, minimum: null, maximum: null, nps: null,
    matrixRows: kind === "matrix" ? options(question.rows).map((row) => ({
      rowId: String(row.value), label: row.label, answered: 0, unanswered: 0, invalid: 0,
      counts: options(question.columns),
    })) : [],
  };
}

function increment(counts: QuestionAggregate["counts"], value: unknown) {
  // Initial-v1 choices have scalar, type-sensitive identities.
  const item = counts.find((entry) => entry.value === value);
  if (item) item.count += 1;
}

/** Server-side building block. Host must approve the stored initial-v1 definition.
 * No respondent-created value or identity is copied into aggregate output.
 * Status/version/test/date selection and authorization belong to the host.
 * Numeric summaries use valid answered values; selection percentages use valid
 * answered participants, so checkbox percentages may total more than 100%.
 */
export function aggregateApprovedSurvey(
  definition: Record<string, unknown>, responses: Record<string, unknown>[],
): QuestionAggregate[] {
  const sources = (definition.pages as Array<{ elements: ProfileQuestion[] }>)
    .flatMap((page) => page.elements);
  const known = new Set(sources.map((question) => question.name));
  const results = sources.map(initial);
  for (const answers of responses) {
    if (Object.keys(answers).some((key) => !known.has(key))) throw new Error("unknown_answer");
    const model = createSurveyModel(definition);
    try {
      restoreSurveyAnswers(model, answers);
      sources.forEach((source, index) => {
        const result = results[index];
        const question = model.getQuestionByName(source.name);
        if (!question.isVisible || !question.page.isVisible) {
          result.hidden += 1;
          return;
        }
        result.relevant += 1;
        const value: unknown = model.getValue(source.name);
        if (absent(value)) {
          result.unanswered += 1;
          result.matrixRows.forEach((row) => row.unanswered += 1);
          return;
        }
        if (profileAnswerError(source, value, false) !== undefined) {
          result.invalid += 1;
          result.matrixRows.forEach((row) => row.invalid += 1);
          return;
        }
        result.answered += 1;
        if (result.kind === "number" || result.kind === "rating") {
          const numeric = value as number;
          result.sum = (result.sum ?? 0) + numeric;
          result.minimum = Math.min(result.minimum ?? numeric, numeric);
          result.maximum = Math.max(result.maximum ?? numeric, numeric);
        }
        if (result.kind === "checkbox") (value as unknown[]).forEach((item) => increment(result.counts, item));
        else if (result.kind === "matrix") {
          const cells = value as Record<string, unknown>;
          result.matrixRows.forEach((row) => {
            if (!(row.rowId in cells)) row.unanswered += 1;
            else {
              row.answered += 1;
              increment(row.counts, cells[row.rowId]);
            }
          });
        } else if (result.kind === "rating") {
          const position = Math.round(((value as number) - Number(source.rateMin ?? 1)) / Number(source.rateStep ?? 1));
          result.counts[position].count += 1;
        } else increment(result.counts, value);
      });
    } finally {
      model.dispose();
    }
  }
  results.forEach((result, index) => {
    if (result.sum !== null && result.answered) result.mean = result.sum / result.answered;
    result.counts.forEach((item) => item.percentage = result.answered ? item.count / result.answered * 100 : null);
    result.matrixRows.forEach((row) => row.counts.forEach((item) => {
      item.percentage = row.answered ? item.count / row.answered * 100 : null;
    }));
    const source = sources[index];
    // Initial-v1 NPS template is explicitly a 0..10 rating with step 1.
    if (result.kind === "rating" && source.rateMin === 0 && source.rateMax === 10 &&
        (source.rateStep ?? 1) === 1 && result.answered) {
      const promoters = result.counts.filter((item) => Number(item.value) >= 9).reduce((n, item) => n + item.count, 0);
      const detractors = result.counts.filter((item) => Number(item.value) <= 6).reduce((n, item) => n + item.count, 0);
      result.nps = (promoters - detractors) / result.answered * 100;
    }
  });
  return results;
}
