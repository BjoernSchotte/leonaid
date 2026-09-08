/** Initial-v1 answer semantics; the host still validates every write authoritatively. */
export interface ProfileQuestion extends Record<string, unknown> {
  name: string;
  type: string;
}
const number = (question: ProfileQuestion, key: string, fallback: number) =>
  typeof question[key] === "number" ? (question[key] as number) : fallback;
const options = (items: unknown): unknown[] =>
  Array.isArray(items)
    ? items.map((item) =>
        item && typeof item === "object" && !Array.isArray(item)
          ? item.value
          : item,
      )
    : [];
const includes = (items: unknown[], value: unknown) =>
  items.some((item) => item === value);
const absent = (value: unknown) =>
  value === undefined ||
  value === null ||
  value === "" ||
  (Array.isArray(value) && value.length === 0);

export function profileAnswerError(
  question: ProfileQuestion,
  value: unknown,
  complete = true,
  locale: "de" | "en" = "de",
): string | undefined {
  if (absent(value)) {
    if (
      complete &&
      (question.isRequired ||
        (question.type === "checkbox" &&
          number(question, "minSelectedChoices", 0) > 0))
    )
      return locale === "en"
        ? "Please answer this question."
        : "Bitte beantworten Sie diese Frage.";
    return;
  }
  const invalid =
    locale === "en"
      ? "Please enter a valid answer."
      : "Bitte geben Sie eine gültige Antwort ein.";
  if (
    (question.type === "text" || question.type === "comment") &&
    question.inputType !== "number" &&
    question.inputType !== "date"
  ) {
    if (typeof value !== "string" || /[\uD800-\uDFFF]/u.test(value))
      return invalid;
    const min = number(question, "minLength", 0),
      max = number(question, "maxLength", 0) || 10000;
    if (value.length < min)
      return locale === "en"
        ? `Please enter at least ${min} characters.`
        : `Bitte geben Sie mindestens ${min} Zeichen ein.`;
    if (value.length > max)
      return locale === "en"
        ? `Please enter no more than ${max} characters.`
        : `Bitte geben Sie höchstens ${max} Zeichen ein.`;
    return;
  }
  if (question.type === "rating" || question.inputType === "number") {
    const rating = question.type === "rating";
    const min = number(
      question,
      rating ? "rateMin" : "min",
      rating ? 1 : -1e12,
    );
    const max = number(question, rating ? "rateMax" : "max", rating ? 5 : 1e12);
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      value < min ||
      value > max
    )
      return invalid;
    if (rating) {
      const index = (value - min) / number(question, "rateStep", 1),
        rounded = Math.round(index);
      if (
        Math.abs(index - rounded) >
        1e-9 * Math.max(Math.abs(index), Math.abs(rounded))
      )
        return invalid;
    }
    return;
  }
  if (question.inputType === "date") {
    if (
      typeof value !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      value.startsWith("0000")
    )
      return invalid;
    const parsed = new Date(`${value}T00:00:00.000Z`);
    if (
      !Number.isFinite(parsed.getTime()) ||
      parsed.toISOString().slice(0, 10) !== value
    )
      return invalid;
    if (
      (typeof question.min === "string" && value < question.min) ||
      (typeof question.max === "string" && value > question.max)
    )
      return invalid;
    return;
  }
  if (question.type === "radiogroup" || question.type === "dropdown") {
    if (!includes(options(question.choices), value)) return invalid;
    return;
  }
  if (question.type === "checkbox") {
    if (
      !Array.isArray(value) ||
      value.some((item) => !includes(options(question.choices), item)) ||
      new Set(value).size !== value.length
    )
      return invalid;
    const min = number(question, "minSelectedChoices", 0),
      max = number(question, "maxSelectedChoices", 0) || 100;
    if (complete && value.length < min)
      return locale === "en"
        ? `Please select at least ${min} answers.`
        : `Bitte wählen Sie mindestens ${min} Antworten aus.`;
    if (value.length > max)
      return locale === "en"
        ? `Please select no more than ${max} answers.`
        : `Bitte wählen Sie höchstens ${max} Antworten aus.`;
    return;
  }
  if (question.type === "matrix") {
    if (!value || typeof value !== "object" || Array.isArray(value))
      return invalid;
    const rows = options(question.rows).map(String),
      columns = options(question.columns);
    const entries = Object.entries(value);
    if (
      entries.some(
        ([row, answer]) => !rows.includes(row) || !includes(columns, answer),
      )
    )
      return invalid;
    if (
      complete &&
      ((question.isRequired && !entries.length) ||
        (question.isAllRowRequired && entries.length !== rows.length))
    )
      return locale === "en"
        ? "Please answer the required rows."
        : "Bitte beantworten Sie die erforderlichen Zeilen.";
    return;
  }
  return invalid;
}
