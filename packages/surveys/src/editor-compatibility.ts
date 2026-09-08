import type { EditorDefinition, EditorQuestion } from "./editor-model";

// Editable initial-v1 profile. The host's publication validator remains authoritative.
const root = new Set([
  "title",
  "description",
  "pages",
  "showProgressBar",
  "completedHtml",
  "locale",
]);
const page = new Set(["name", "title", "description", "elements", "visibleIf"]);
const common = [
  "name",
  "type",
  "title",
  "description",
  "isRequired",
  "visibleIf",
];
const types: Record<string, string[]> = {
  text: ["inputType", "min", "max", "minLength", "maxLength", "placeholder"],
  comment: ["minLength", "maxLength", "placeholder"],
  radiogroup: ["choices"],
  dropdown: ["choices", "placeholder"],
  checkbox: ["choices", "minSelectedChoices", "maxSelectedChoices"],
  rating: ["rateMin", "rateMax", "rateStep"],
  matrix: ["rows", "columns", "isAllRowRequired"],
};
function unsupportedOptions(value: unknown): boolean {
  if (!Array.isArray(value)) return true;
  return value.some((entry) => {
    if (typeof entry === "string" || typeof entry === "number") return false;
    if (!entry || typeof entry !== "object" || Array.isArray(entry))
      return true;
    const option = entry as Record<string, unknown>;
    return (
      Object.keys(option).some((key) => !["value", "text"].includes(key)) ||
      !["string", "number"].includes(typeof option.value) ||
      (option.text !== undefined && typeof option.text !== "string")
    );
  });
}
export function questionIssues(question: EditorQuestion): string[] {
  if (!Object.hasOwn(types, question.type)) return ["type"];
  const allowed = new Set([...common, ...types[question.type]]);
  const fields = Object.keys(question).filter((key) => !allowed.has(key));
  for (const key of ["title", "description", "placeholder", "visibleIf"])
    if (key in question && typeof question[key] !== "string") fields.push(key);
  for (const key of ["choices", "rows", "columns"])
    if (key in question && unsupportedOptions(question[key])) fields.push(key);
  if (
    question.inputType !== undefined &&
    !["text", "number", "date"].includes(String(question.inputType))
  )
    fields.push("inputType");
  return [...new Set(fields)];
}
export function compatibilityIssues(definition: EditorDefinition): string[] {
  const issues = Object.keys(definition)
    .filter((key) => !root.has(key))
    .map((key) => `definition.${key}`);
  definition.pages.forEach((item, index) => {
    const prefix = `pages[${index}]`;
    issues.push(
      ...Object.keys(item)
        .filter((key) => !page.has(key))
        .map((key) => `${prefix}.${key}`),
    );
    item.elements.forEach((question, i) => {
      issues.push(
        ...questionIssues(question).map(
          (key) => `${prefix}.elements[${i}].${key}`,
        ),
      );
    });
  });
  return issues;
}
