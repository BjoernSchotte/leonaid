import type { JsonValue, SurveyDefinition } from "./contracts";

export type QuestionKind =
  | "text"
  | "comment"
  | "radiogroup"
  | "dropdown"
  | "checkbox"
  | "rating"
  | "matrix";
export interface EditorQuestion {
  [key: string]: JsonValue;
  name: string;
  type: string;
}
export interface EditorPage {
  [key: string]: JsonValue;
  name: string;
  elements: EditorQuestion[];
}
export interface EditorDefinition extends SurveyDefinition {
  pages: EditorPage[];
}
const copy = <T>(value: T): T => structuredClone(value);
const id = (prefix: string) =>
  `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;

export function readEditorDefinition(
  value: SurveyDefinition,
): EditorDefinition {
  if (JSON.stringify(value).length > 262144 || !Array.isArray(value.pages))
    throw new Error(
      "Der Fragebogen muss eine begrenzte Liste von Seiten enthalten.",
    );
  const names = new Set<string>();
  const pageNames = new Set<string>();
  for (const page of value.pages) {
    if (
      !page ||
      typeof page !== "object" ||
      Array.isArray(page) ||
      typeof page.name !== "string" ||
      !Array.isArray(page.elements)
    )
      throw new Error("Eine Seite hat kein gültiges Format.");
    if (pageNames.has(page.name))
      throw new Error("Seitennamen müssen eindeutig sein.");
    pageNames.add(page.name);
    for (const question of page.elements) {
      if (
        !question ||
        typeof question !== "object" ||
        Array.isArray(question) ||
        typeof question.name !== "string" ||
        typeof question.type !== "string" ||
        names.has(question.name)
      )
        throw new Error(
          "Fragen benötigen eindeutige Namen und einen Fragetyp.",
        );
      names.add(question.name);
    }
  }
  return copy(value) as EditorDefinition;
}

/** Replace expression references, preserving quoted literals and unknown fields. */
function remapReferences(
  expression: string,
  mapping: Map<string, string>,
): string {
  let result = "",
    quote = "",
    escaped = false;
  for (let index = 0; index < expression.length; index++) {
    const char = expression[index];
    if (quote) {
      result += char;
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === quote) quote = "";
    } else if (char === "'" || char === '"') {
      quote = char;
      result += char;
    } else if (char === "{") {
      const end = expression.indexOf("}", index);
      const name = expression.slice(index + 1, end);
      if (end >= 0 && mapping.has(name)) {
        result += `{${mapping.get(name)}}`;
        index = end;
      } else result += char;
    } else result += char;
  }
  return result;
}

export function newQuestion(type: QuestionKind): EditorQuestion {
  const question: EditorQuestion = {
    type,
    name: id("question"),
    title: "Neue Frage",
  };
  if (["radiogroup", "dropdown", "checkbox"].includes(type))
    question.choices = [
      { value: id("choice"), text: "Antwort 1" },
      { value: id("choice"), text: "Antwort 2" },
    ];
  if (type === "matrix") {
    question.rows = [{ value: id("row"), text: "Aspekt 1" }];
    question.columns = [
      { value: 1, text: "Schlecht" },
      { value: 2, text: "Gut" },
    ];
  }
  return question;
}

export class EditorHistory {
  private present: EditorDefinition;
  private past: EditorDefinition[] = [];
  private future: EditorDefinition[] = [];
  generation = 0;
  constructor(definition: SurveyDefinition) {
    this.present = readEditorDefinition(definition);
  }
  get document(): EditorDefinition {
    return copy(this.present);
  }
  get canUndo() {
    return this.past.length > 0;
  }
  get canRedo() {
    return this.future.length > 0;
  }
  change(mutate: (next: EditorDefinition) => void): void {
    const next = copy(this.present);
    mutate(next);
    const checked = readEditorDefinition(next);
    if (JSON.stringify(checked) === JSON.stringify(this.present)) return;
    this.past = [...this.past.slice(-99), this.present];
    this.present = checked;
    this.future = [];
    this.generation++;
  }
  undo() {
    if (!this.canUndo) return;
    this.future.push(this.present);
    this.present = this.past.pop()!;
    this.generation++;
  }
  redo() {
    if (!this.canRedo) return;
    this.past.push(this.present);
    this.present = this.future.pop()!;
    this.generation++;
  }
  addPage(): string {
    const name = id("page");
    this.change((doc) => {
      doc.pages.push({ name, title: "Neue Seite", elements: [] });
    });
    return name;
  }
  addQuestion(pageId: string, kind: QuestionKind): string {
    const question = newQuestion(kind);
    this.change((doc) => {
      this.page(doc, pageId).elements.push(question);
    });
    return question.name;
  }
  updateQuestion(
    name: string,
    properties: Record<string, JsonValue | undefined>,
  ) {
    this.change((doc) => {
      const question = doc.pages
        .flatMap((page) => page.elements)
        .find((q) => q.name === name);
      if (!question) throw new Error("Frage nicht gefunden.");
      for (const [key, value] of Object.entries(properties)) {
        if (key === "name" || key === "type")
          throw new Error("Identität und Fragetyp bleiben unverändert.");
        if (value === undefined) delete question[key];
        else question[key] = copy(value);
      }
    });
  }
  movePage(name: string, position: number) {
    this.change((doc) => {
      const index = doc.pages.findIndex((page) => page.name === name);
      if (index < 0 || position < 0 || position >= doc.pages.length) return;
      doc.pages.splice(position, 0, doc.pages.splice(index, 1)[0]);
    });
  }
  moveQuestion(name: string, targetPage: string, position: number) {
    this.change((doc) => {
      const source = doc.pages.find((page) =>
        page.elements.some((q) => q.name === name),
      );
      if (!source) throw new Error("Frage nicht gefunden.");
      const target = this.page(doc, targetPage);
      const index = source.elements.findIndex((q) => q.name === name);
      const question = source.elements.splice(index, 1)[0];
      target.elements.splice(
        Math.max(0, Math.min(position, target.elements.length)),
        0,
        question,
      );
    });
  }
  duplicatePage(name: string): string {
    const newId = id("page");
    this.change((doc) => {
      const source = this.page(doc, name);
      const duplicate = copy(source);
      duplicate.name = newId;
      const mapping = new Map(
        source.elements.map((q) => [q.name, id("question")]),
      );
      for (const question of duplicate.elements) {
        question.name = mapping.get(question.name)!;
        if (typeof question.visibleIf === "string")
          question.visibleIf = remapReferences(question.visibleIf, mapping);
      }
      doc.pages.splice(doc.pages.indexOf(source) + 1, 0, duplicate);
    });
    return newId;
  }
  duplicateQuestion(name: string): string {
    const newId = id("question");
    this.change((doc) => {
      const page = doc.pages.find((page) =>
        page.elements.some((q) => q.name === name),
      );
      if (!page) throw new Error("Frage nicht gefunden.");
      const index = page.elements.findIndex((q) => q.name === name);
      page.elements.splice(index + 1, 0, {
        ...copy(page.elements[index]),
        name: newId,
      });
    });
    return newId;
  }
  removePage(name: string) {
    this.change((doc) => {
      doc.pages = doc.pages.filter((page) => page.name !== name);
    });
  }
  removeQuestion(name: string) {
    this.change((doc) => {
      for (const page of doc.pages)
        page.elements = page.elements.filter((q) => q.name !== name);
    });
  }
  private page(doc: EditorDefinition, name: string): EditorPage {
    const page = doc.pages.find((page) => page.name === name);
    if (!page) throw new Error("Seite nicht gefunden.");
    return page;
  }
}
