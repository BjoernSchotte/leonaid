import { expect, test } from "bun:test";
import { Model } from "survey-core";
import { SaveCoordinator } from "../../packages/surveys/src/runner";
import type {
  Participation,
  ParticipationAdapter,
  Result,
  ResponseSnapshot,
  SaveResponse,
} from "../../packages/surveys/src/contracts";
const participation: Participation = {
  id: "p",
  inactivityTimeoutSeconds: 30,
  version: {
    id: "v",
    surveyId: "s",
    number: 1,
    definition: {
      pages: [{ name: "page", elements: [{ type: "text", name: "note" }] }],
    },
    rendererVersion: "3.0.3",
    capabilityProfile: "initial-v1",
    publishedAt: "2026-09-06",
  },
  response: {
    participationId: "p",
    versionId: "v",
    revision: 1,
    status: "in_progress",
    answers: {},
    currentPage: "page",
    lastAnswerChangedAt: null,
    completedAt: null,
    diagnostics: [],
  },
};
const ok = (input: SaveResponse): Result<ResponseSnapshot> => ({
  ok: true,
  value: {
    ...participation.response,
    revision: input.expectedRevision + 1,
    answers: input.answers,
  },
});
function adapter(save: ParticipationAdapter["save"]): ParticipationAdapter {
  return {
    save,
    start: async () => {
      throw Error("unexpected");
    },
    restore: async () => {
      throw Error("unexpected");
    },
    complete: async () => {
      throw Error("unexpected");
    },
  };
}
test("an acknowledgement for an older edit cannot claim the newer edit is saved", async () => {
  const calls: SaveResponse[] = [];
  let release!: (result: Result<ResponseSnapshot>) => void;
  const model = new Model(participation.version.definition);
  const saves = new SaveCoordinator(
    model,
    participation,
    adapter(async (_, input) => {
      calls.push(structuredClone(input));
      if (calls.length === 1)
        return new Promise((resolve) => {
          release = resolve;
        });
      return ok(input);
    }),
    () => {},
  );
  model.setValue("note", "first");
  saves.changed();
  const done = saves.flush();
  model.setValue("note", "second");
  saves.changed();
  release(ok(calls[0]));
  expect(await done).toBe(true);
  expect(calls).toHaveLength(2);
  expect(calls[1].expectedRevision).toBe(2);
  expect(calls[1].answers).toEqual({ note: "second" });
  expect(saves.response.answers).toEqual({ note: "second" });
  saves.dispose();
});
test("uncertain write retries its exact operation before sending newer edits", async () => {
  const calls: SaveResponse[] = [];
  const model = new Model(participation.version.definition);
  const saves = new SaveCoordinator(
    model,
    participation,
    adapter(async (_, input) => {
      calls.push(structuredClone(input));
      if (calls.length === 1) throw Error("lost acknowledgement");
      return ok(input);
    }),
    () => {},
  );
  model.setValue("note", "first");
  saves.changed();
  expect(await saves.flush()).toBe(false);
  expect(saves.state).toBe("error");
  model.setValue("note", "second");
  saves.changed();
  expect(await saves.flush()).toBe(true);
  expect(calls[1]).toEqual(calls[0]);
  expect(calls[2].answers).toEqual({ note: "second" });
  expect(calls[2].expectedRevision).toBe(2);
  saves.dispose();
});

test("a rejected invalid snapshot does not prevent saving a subsequent correction", async () => {
  const calls: SaveResponse[] = [];
  const model = new Model(participation.version.definition);
  const saves = new SaveCoordinator(
    model,
    participation,
    adapter(async (_, input) => {
      calls.push(structuredClone(input));
      if (calls.length === 1)
        return {
          ok: false,
          error: {
            code: "invalid_response",
            message: "Invalid",
            diagnostics: [],
          },
        };
      return ok(input);
    }),
    () => {},
  );
  model.setValue("note", "invalid");
  saves.changed();
  expect(await saves.flush()).toBe(false);
  model.setValue("note", "corrected");
  saves.changed();
  expect(await saves.flush()).toBe(true);
  expect(calls).toHaveLength(2);
  expect(calls[1].answers).toEqual({ note: "corrected" });
  expect(calls[1].expectedRevision).toBe(1);
  expect(calls[1].operationId).not.toBe(calls[0].operationId);
  saves.dispose();
});
