import { expect, test } from "bun:test";
import { EditorHistory } from "../../packages/surveys/src/editor-model";
import { DraftCoordinator } from "../../packages/surveys/src/editor-saves";
import type {
  AuthoringAdapter,
  Draft,
  SaveDraft,
} from "../../packages/surveys/src/contracts";

const definition = {
  title: "Example",
  unknown: { preserve: [1, 2] },
  pages: [
    {
      name: "p",
      elements: [
        { name: "source", type: "text", title: "Original" },
        {
          name: "follow",
          type: "comment",
          visibleIf: "{source} = '{source}'",
          custom: { unchanged: true },
        },
      ],
    },
  ],
};
test("duplicating a page remaps references without rewriting quoted literals or unknown data", () => {
  const history = new EditorHistory(definition);
  const newPage = history.duplicatePage("p");
  const copy = history.document.pages.find((page) => page.name === newPage)!;
  expect(copy.elements[0].name).not.toBe("source");
  expect(copy.elements[1].visibleIf).toBe(
    `{${copy.elements[0].name}} = '{source}'`,
  );
  expect(copy.elements[1].custom).toEqual({ unchanged: true });
  expect(history.document.unknown).toEqual({ preserve: [1, 2] });
  history.undo();
  expect(history.document).toEqual(definition);
  history.redo();
  expect(history.document.pages[1]).toEqual(copy);
});
test("moves and wording edits retain identity; a new edit after undo discards redo", () => {
  const history = new EditorHistory(definition);
  const target = history.addPage();
  history.moveQuestion("source", target, 0);
  history.updateQuestion("source", { title: "Reworded" });
  expect(history.document.pages[1].elements[0].name).toBe("source");
  history.undo();
  expect(history.document.pages[1].elements[0].title).toBe("Original");
  history.updateQuestion("source", { description: "New branch" });
  expect(history.canRedo).toBe(false);
  const detached = history.document;
  detached.pages.length = 0;
  expect(history.document.pages).toHaveLength(2);
});
test("an uncertain draft save retries the identical operation before newer edits", async () => {
  const history = new EditorHistory(definition);
  const draft: Draft = { surveyId: "survey", revision: 1, definition };
  const calls: SaveDraft[] = [];
  let fail = true;
  const adapter: AuthoringAdapter = {
    loadDraft: async () => ({ ok: true, value: draft }),
    publish: async () => {
      throw new Error("not used");
    },
    saveDraft: async (_, input) => {
      calls.push(structuredClone(input));
      if (fail) {
        fail = false;
        throw new Error("connection lost");
      }
      return {
        ok: true,
        value: {
          ...draft,
          revision: input.expectedRevision + 1,
          definition: input.definition,
        },
      };
    },
  };
  const saves = new DraftCoordinator(draft, history, adapter, () => {});
  history.updateQuestion("source", { title: "First" });
  expect(await saves.flush()).toBe(false);
  history.updateQuestion("source", { title: "Second" });
  expect(await saves.flush()).toBe(true);
  expect(calls[1]).toEqual(calls[0]);
  expect(calls[2].expectedRevision).toBe(2);
  expect((calls[2].definition.pages as any)[0].elements[0].title).toBe(
    "Second",
  );
  expect(saves.state).toBe("saved");
});
