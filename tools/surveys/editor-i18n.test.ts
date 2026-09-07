import { expect, test } from "bun:test";
import { formatEditorMessage } from "../../packages/surveys/src/editor-i18n";
import { EditorHistory } from "../../packages/surveys/src/editor-model";

test("editor placeholders permit reordered host wording and remain plain text", () => {
  expect(
    formatEditorMessage("Remove {number}: {label}", {
      number: 0,
      label: "<script>{number}</script>",
    }),
  ).toBe("Remove 0: <script>{number}</script>");
  expect(formatEditorMessage("{missing} {toString}", {})).toBe(
    "{missing} {toString}",
  );
});

test("translation applies only to newly generated authoring defaults, with stable history", () => {
  const original = {
    title: "Author title",
    pages: [{ name: "original", title: "Author page", elements: [] }],
  };
  let language = "English";
  const history = new EditorHistory(
    original,
    (message) => `${language}: ${message}`,
  );
  const page = history.addPage();
  expect(history.document.pages[1].title).toBe("English: Neue Seite");
  const question = history.addQuestion(page, "matrix");
  expect(history.document.pages[1].elements[0].title).toBe(
    "English: Neue Frage",
  );
  expect(history.document.pages[1].elements[0].rows).toEqual([
    expect.objectContaining({ text: "English: Aspekt 1" }),
  ]);
  language = "French";
  history.addQuestion(page, "radiogroup");
  expect(history.document.pages[1].elements[1].choices).toEqual([
    expect.objectContaining({ text: "French: Antwort 1" }),
    expect.objectContaining({ text: "French: Antwort 2" }),
  ]);
  expect(history.document.title).toBe(original.title);
  expect(history.document.pages[0]).toEqual(original.pages[0]);
  history.undo();
  expect(history.document.pages[1].elements).toHaveLength(1);
  expect(history.document.pages[1].elements[0].name).toBe(question);
  expect(history.document.pages[1].elements[0].title).toBe(
    "English: Neue Frage",
  );
});
