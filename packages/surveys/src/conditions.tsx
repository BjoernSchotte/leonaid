import { formatEditorMessage, type EditorTranslator } from "./editor-i18n";
import type { JsonValue } from "./contracts";
import type { EditorQuestion } from "./editor-model";

type Row = { reference: string; operator: string; value: JsonValue };
const labels: Record<string, string> = {
  notempty: "ist beantwortet",
  empty: "ist nicht beantwortet",
  "=": "ist gleich",
  "!=": "ist ungleich",
  contains: "enthält",
  notcontains: "enthält nicht",
  "<": "ist kleiner als",
  "<=": "ist höchstens",
  ">": "ist größer als",
  ">=": "ist mindestens",
};
function parse(expression: string): { rows: Row[]; mode: "and" | "or" } | null {
  if (!expression) return { rows: [], mode: "and" };
  let quote = "",
    depth = 0,
    start = 0,
    escaped = false;
  const parts: string[] = [];
  const joins: string[] = [];
  for (let i = 0; i < expression.length; i++) {
    const char = expression[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === "(") depth++;
    if (char === ")") depth--;
    if (depth === 0)
      for (const join of [" and ", " or "])
        if (expression.startsWith(join, i)) {
          parts.push(expression.slice(start, i));
          joins.push(join.trim());
          i += join.length - 1;
          start = i + 1;
        }
  }
  if (quote || depth !== 0 || new Set(joins).size > 1) return null;
  parts.push(expression.slice(start));
  const rows: Row[] = [];
  for (let part of parts) {
    part = part.trim();
    if (part.startsWith("(") && part.endsWith(")"))
      part = part.slice(1, -1).trim();
    const match = part.match(
      /^\{([A-Za-z][A-Za-z0-9_]*)\}\s*(notempty|empty|notcontains|contains|<=|>=|!=|=|<|>)\s*(.*)$/,
    );
    if (!match) return null;
    let value: JsonValue = "";
    if (!["empty", "notempty"].includes(match[2])) {
      try {
        value =
          match[3].startsWith("'") && match[3].endsWith("'")
            ? match[3].slice(1, -1)
            : JSON.parse(match[3]);
      } catch {
        return null;
      }
    }
    rows.push({ reference: match[1], operator: match[2], value });
  }
  return { rows, mode: joins[0] === "or" ? "or" : "and" };
}
export function ConditionBuilder({
  expression,
  questions,
  onChange,
  translate: t = formatEditorMessage,
}: {
  translate?: EditorTranslator;
  expression: string;
  questions: EditorQuestion[];
  onChange: (value: string | undefined) => void;
}) {
  const parsed = parse(expression);
  if (!parsed)
    return (
      <div>
        <p>
          {t(
            "Diese vorhandene Bedingung bleibt unverändert erhalten. Der geführte Editor unterstützt eine Ebene mit allen oder beliebigen Regeln.",
          )}
        </p>
        <button type="button" onClick={() => onChange(undefined)}>
          {t("Bedingung entfernen")}
        </button>
      </div>
    );
  function save(rows: Row[], mode = parsed!.mode) {
    onChange(
      rows.length
        ? rows
            .map(
              (row) =>
                `({${row.reference}} ${row.operator}${["empty", "notempty"].includes(row.operator) ? "" : ` ${JSON.stringify(row.value)}`})`,
            )
            .join(` ${mode} `)
        : undefined,
    );
  }
  return (
    <fieldset>
      <legend>{t("Sichtbarkeit")}</legend>
      <p>{t("Ohne Regel immer anzeigen.")}</p>
      {parsed.rows.length > 1 && (
        <label>
          {t("Regeln verknüpfen")}
          <select
            value={parsed.mode}
            onChange={(event) =>
              save(parsed.rows, event.target.value as "and" | "or")
            }
          >
            <option value="and">{t("Alle Regeln müssen zutreffen")}</option>
            <option value="or">
              {t("Mindestens eine Regel muss zutreffen")}
            </option>
          </select>
        </label>
      )}
      {parsed.rows.map((row, index) => {
        const source = questions.find((q) => q.name === row.reference);
        const numeric =
          source?.type === "rating" || source?.inputType === "number";
        const operators = numeric
          ? ["notempty", "empty", "=", "!=", "<", "<=", ">", ">="]
          : source?.type === "checkbox"
            ? ["notempty", "empty", "contains", "notcontains"]
            : ["notempty", "empty", "=", "!=", "contains", "notcontains"];
        const choices = Array.isArray(source?.choices) ? source.choices : [];
        const optionValue = (value: JsonValue) =>
          value && typeof value === "object" && !Array.isArray(value)
            ? value.value
            : value;
        const update = (patch: Partial<Row>) =>
          save(
            parsed.rows.map((item, i) =>
              i === index ? { ...item, ...patch } : item,
            ),
          );
        return (
          <div key={index}>
            <label>
              {t("Vorherige Frage {number}", { number: index + 1 })}
              <select
                value={row.reference}
                onChange={(event) =>
                  update({
                    reference: event.target.value,
                    operator: "notempty",
                    value: "",
                  })
                }
              >
                {!source && (
                  <option value={row.reference}>
                    {t("Frage steht nicht mehr davor")}
                  </option>
                )}
                {questions.map((q) => (
                  <option key={q.name} value={q.name}>
                    {String(q.title ?? q.name)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("Vergleich {number}", { number: index + 1 })}
              <select
                value={row.operator}
                onChange={(event) =>
                  update({
                    operator: event.target.value,
                    value: choices.length
                      ? optionValue(choices[0])
                      : numeric
                        ? 0
                        : "",
                  })
                }
              >
                {operators.map((op) => (
                  <option key={op} value={op}>
                    {t(labels[op])}
                  </option>
                ))}
              </select>
            </label>
            {!["empty", "notempty"].includes(row.operator) &&
              (choices.length ? (
                <label>
                  {t("Antwortwert {number}", { number: index + 1 })}
                  <select
                    value={String(
                      choices.findIndex(
                        (value) => optionValue(value) === row.value,
                      ),
                    )}
                    onChange={(event) =>
                      update({
                        value: optionValue(choices[Number(event.target.value)]),
                      })
                    }
                  >
                    <option value="-1" disabled>
                      {t("Antwort wählen")}
                    </option>
                    {choices.map((value, i) => (
                      <option key={i} value={i}>
                        {String(
                          value &&
                            typeof value === "object" &&
                            !Array.isArray(value)
                            ? (value.text ?? value.value)
                            : value,
                        )}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label>
                  {t("Vergleichswert {number}", { number: index + 1 })}
                  <input
                    type={numeric ? "number" : "text"}
                    value={String(row.value)}
                    onChange={(event) =>
                      update({
                        value: numeric
                          ? Number(event.target.value)
                          : event.target.value,
                      })
                    }
                  />
                </label>
              ))}
            <button
              type="button"
              onClick={() => save(parsed.rows.filter((_, i) => i !== index))}
            >
              {t("Regel {number} entfernen", { number: index + 1 })}
            </button>
          </div>
        );
      })}
      <button
        type="button"
        disabled={!questions.length}
        onClick={() =>
          save([
            ...parsed.rows,
            { reference: questions[0].name, operator: "notempty", value: "" },
          ])
        }
      >
        {t("Regel hinzufügen")}
      </button>
    </fieldset>
  );
}
