import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type FreeTextItems,
  type IndividualResponse,
  type LeonAidApiClient,
  type ResponseItem,
  type ResponseSelection,
  type SurveySummaryResponse,
} from "@leonaid/api-client";
import { resetCommandPaletteState } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import {
  SurveyResponsesPage,
  answerText,
  migrateLegacyResponseParam,
  receivedLabel,
  surveyResponsesHref,
} from "../../../packages/features/src/surveys/survey-responses";
import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const surveyId = "30000000-0000-4000-8000-000000000001";
const snapshotId = "40000000-0000-4000-8000-000000000001";
const versionId = "50000000-0000-4000-8000-000000000001";
const base = `/admin/surveys/${surveyId}/responses`;

beforeAll(() => {
  installDialogPolyfill();
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  resetCommandPaletteState();
  window.history.replaceState(null, "", "/");
  vi.restoreAllMocks();
});

const participation = (index: number) =>
  `60000000-0000-4000-8000-${String(index).padStart(12, "0")}`;

function item(index: number): ResponseItem {
  return {
    participationId: participation(index),
    status: index === 51 ? "partial" : "completed",
    createdAt: new Date(Date.UTC(2026, 9, 1, 8, index)).toISOString(),
    completedAt: null,
    currentPage: null,
    revision: 1,
  };
}

const selection: ResponseSelection = {
  id: snapshotId,
  surveyId,
  versionNumber: 1,
  total: 51,
  createdAt: "2026-10-02T10:00:00Z",
  filter: {
    versionId,
    statuses: ["partial", "completed"],
    isTest: false,
    createdFrom: null,
    createdBefore: null,
  },
  questions: [
    {
      id: "choice",
      kind: "checkbox",
      title: "Auswahl",
      choices: [
        { value: "a", label: "Alpha" },
        { value: "b", label: "Beta" },
      ],
      rows: [],
    },
    { id: "text", kind: "text", title: "Rückmeldung", choices: [], rows: [] },
  ],
};

function summary(capabilities: string[]): SurveySummaryResponse {
  return {
    id: surveyId,
    title: "Helferbefragung",
    status: "active",
    accessMode: "anonymous",
    actionId: null,
    capabilities,
    deletedAt: null,
    endsAt: null,
    inactivityTimeoutSeconds: null,
    ownerUserId: "u1",
    publishedVersionId: versionId,
    revision: 1,
  };
}

function fakeClient(capabilities = ["read_responses"], pageCap = 5000) {
  const all = Array.from({ length: 51 }, (_, index) => item(index + 1));
  return {
    getSurvey: vi.fn(async () => summary(capabilities)),
    listSurveyResponseVersions: vi.fn(async () => ({
      items: [
        { id: versionId, number: 1, publishedAt: "2026-10-01T00:00:00Z" },
      ],
    })),
    getSurveyResponseSelection: vi.fn(async () => selection),
    createSurveyResponseSelection: vi.fn(
      async (
        _survey: string,
        _body: unknown,
        _options?: { signal?: AbortSignal },
      ) => selection,
    ),
    listSurveyResponses: vi.fn(
      async (
        _s: string,
        _id: string,
        query: { offset?: number; limit?: number } = {},
        _options?: { signal?: AbortSignal },
      ) => {
        const offset = query.offset ?? 0;
        return {
          snapshotId,
          offset,
          total: all.length,
          items: all.slice(
            offset,
            offset + Math.min(query.limit ?? 50, pageCap),
          ),
        };
      },
    ),
    getSurveyResponse: vi.fn(
      async (
        _s: string,
        _id: string,
        id: string,
      ): Promise<IndividualResponse> => ({
        ...all.find((row) => row.participationId === id)!,
        answers: {
          choice: ["a", "b"],
          text: `<img src=x> Text ${id.slice(-2)}`,
        },
      }),
    ),
    listSurveyFreeText: vi.fn(
      async (): Promise<FreeTextItems> => ({
        snapshotId,
        questionId: "text",
        offset: 0,
        total: 1,
        items: [
          {
            participationId: participation(7),
            status: "completed",
            text: "Mehr Kaffee",
          },
        ],
      }),
    ),
  };
}

async function renderPage(url: string, client = fakeClient()) {
  window.history.replaceState(null, "", url);
  render(
    <ToastProvider>
      <HotkeyProvider>
        <SurveyResponsesPage
          client={client as unknown as LeonAidApiClient}
          surveyId={surveyId}
        />
      </HotkeyProvider>
    </ToastProvider>,
  );
  return client;
}

function row(number: number) {
  return screen
    .getByText(String(number), { selector: ".mono" })
    .closest("li") as HTMLElement;
}

describe("survey responses helpers", () => {
  it("links the responses page and migrates the old response parameter", () => {
    expect(surveyResponsesHref(surveyId)).toBe(base);
    expect(
      surveyResponsesHref(
        surveyId,
        `?responseSelection=${snapshotId}&response=p1`,
      ),
    ).toBe(`${base}?responseSelection=${snapshotId}&open=p1`);
    // An open response without its selection is meaningless.
    expect(surveyResponsesHref(surveyId, "?response=p1")).toBe(base);
    expect(migrateLegacyResponseParam("?responseSelection=s&response=p1")).toBe(
      "?responseSelection=s&open=p1",
    );
    expect(migrateLegacyResponseParam("?open=p2&response=p1")).toBe("?open=p2");
    expect(migrateLegacyResponseParam("?view=all")).toBe("?view=all");
  });

  it("formats answers and dates as before", () => {
    const [choice] = selection.questions;
    expect(answerText(["a", "b"], choice!)).toBe("Alpha\nBeta");
    expect(answerText(null, choice!)).toBe("Nicht beantwortet");
    const local = new Date(2026, 10, 3, 14, 5).toISOString();
    expect(receivedLabel(local, new Date(2026, 0, 1))).toBe("03.11. 14:05");
    expect(receivedLabel(local, new Date(2027, 0, 1))).toBe("03.11.26 14:05");
  });
});

describe("SurveyResponsesPage", () => {
  it("does not request responses for an account without read rights", async () => {
    const client = fakeClient(["view_aggregates"]);
    await renderPage(`${base}?responseSelection=${snapshotId}`, client);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Dieser Antwortstand ist für Sie nicht zugänglich.",
    );
    expect(client.listSurveyResponseVersions).not.toHaveBeenCalled();
    expect(client.getSurveyResponseSelection).not.toHaveBeenCalled();
    expect(client.listSurveyResponses).not.toHaveBeenCalled();
  });

  it("names the survey's responses when no selection is linked", async () => {
    await renderPage(base, fakeClient(["view_aggregates"]));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Die Einzelantworten dieser Umfrage sind für Sie nicht zugänglich.",
    );
  });

  it("offers no retry when the survey is refused", async () => {
    const client = fakeClient();
    client.getSurvey.mockRejectedValueOnce(
      new ApiError(404, {
        code: "not_found",
        message: "Umfrage nicht gefunden.",
        requestId: "req-2",
      } as never),
    );
    await renderPage(base, client);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Umfrage nicht gefunden.",
    );
    expect(
      screen.queryByRole("button", { name: "Erneut versuchen" }),
    ).toBeNull();
    expect(
      screen.getByRole("link", { name: "Zu allen Umfragen" }),
    ).toBeTruthy();
  });

  it("follows further pages when the server sends fewer rows", async () => {
    const client = fakeClient(["read_responses"], 50);
    await renderPage(`${base}?responseSelection=${snapshotId}`, client);
    await screen.findByText("51 Antworten");
    expect(
      client.listSurveyResponses.mock.calls.map((call) => call[2]),
    ).toEqual([{ limit: 5000 }, { offset: 50, limit: 5000 }]);
  });

  it("shows how many responses load", async () => {
    const client = fakeClient();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    const original = client.listSurveyResponses.getMockImplementation()!;
    client.listSurveyResponses.mockImplementationOnce(async (...args) => {
      await gate;
      return original(...args);
    });
    await renderPage(`${base}?responseSelection=${snapshotId}`, client);
    expect(
      (await screen.findByText("51 Antworten werden geladen …")).textContent,
    ).toBeTruthy();
    await act(async () => release());
    await screen.findByText("51 Antworten");
  });

  it("drops a refused new selection from the URL", async () => {
    const client = fakeClient();
    client.createSurveyResponseSelection.mockRejectedValueOnce(
      new ApiError(409, {
        code: "conflict",
        message: "Diese Auswahl ist nicht möglich.",
        requestId: "req-3",
      } as never),
    );
    await renderPage(
      `${base}?responseSelection=${snapshotId}&open=${participation(3)}`,
      client,
    );
    await screen.findByText("51 Antworten");
    fireEvent.click(
      screen.getByRole("button", { name: "Antwortstand wählen" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Antwortstand wählen",
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Antworten auswählen" }),
    );
    await screen.findByText("Diese Auswahl ist nicht möglich.", {
      exact: false,
    });
    const params = new URL(window.location.href).searchParams;
    expect(params.has("responseSelection")).toBe(false);
    expect(params.has("open")).toBe(false);
  });

  it("asks for a selection first, then lists every page of it", async () => {
    const client = await renderPage(base);
    await screen.findByRole("heading", {
      level: 2,
      name: "Antwortstand wählen",
    });
    expect(screen.queryByLabelText("Antwortquelle")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Antworten auswählen" }),
    );
    await screen.findByRole("heading", { level: 1, name: "Einzelantworten" });
    expect(client.createSurveyResponseSelection).toHaveBeenCalledWith(
      surveyId,
      expect.objectContaining({
        filter: {
          versionId,
          statuses: ["partial", "completed"],
          isTest: false,
          createdFrom: null,
          createdBefore: null,
        },
      }),
      { signal: expect.any(AbortSignal) },
    );
    expect(
      client.listSurveyResponses.mock.calls.map((call) => call[2]),
    ).toEqual([{ limit: 5000 }]);
    // Every list request can be aborted.
    expect(
      client.listSurveyResponses.mock.calls.every(
        (call) => call[3]?.signal instanceof AbortSignal,
      ),
    ).toBe(true);
    expect(screen.getByText("51 Antworten")).toBeTruthy();
    expect(row(51).textContent).toContain("Teilantwort");
    expect(
      new URL(window.location.href).searchParams.get("responseSelection"),
    ).toBe(snapshotId);
    expect(client.getSurveyResponse).not.toHaveBeenCalled();
  });

  it("restores the selection and opens the linked response with escaped text", async () => {
    const client = await renderPage(
      `${base}?responseSelection=${snapshotId}&response=${participation(3)}`,
    );
    const pane = await screen.findByRole("complementary", {
      name: "Details: Antwort 3",
    });
    expect(
      await within(pane).findByText("Alpha\nBeta", {
        collapseWhitespace: false,
      }),
    ).toBeTruthy();
    expect(within(pane).getByText("<img src=x> Text 03")).toBeTruthy();
    expect(pane.querySelector("img")).toBeNull();
    expect(new URL(window.location.href).searchParams.get("open")).toBe(
      participation(3),
    );
    expect(new URL(window.location.href).searchParams.has("response")).toBe(
      false,
    );
    // Status is read-only: no property row to edit it.
    expect(
      within(pane).queryByRole("group", { name: "Eigenschaften" }),
    ).toBeNull();
    expect(client.getSurveyResponse).toHaveBeenCalledTimes(1);
  });

  it("filters by status with the views", async () => {
    await renderPage(`${base}?responseSelection=${snapshotId}`);
    await screen.findByText("51 Antworten");
    fireEvent.click(screen.getByRole("button", { name: "Unvollständig" }));
    expect(screen.getByText("1 von 51")).toBeTruthy();
    expect(row(51)).toBeTruthy();
  });

  it("opens a free-text answer's response in the pane", async () => {
    const client = await renderPage(`${base}?responseSelection=${snapshotId}`);
    await screen.findByText("51 Antworten");
    fireEvent.click(screen.getByRole("button", { name: "Freitexte" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Freitextantworten",
    });
    expect(await within(dialog).findByText("„Mehr Kaffee“")).toBeTruthy();
    expect(client.listSurveyFreeText).toHaveBeenCalledWith(
      surveyId,
      snapshotId,
      "text",
      {},
      expect.anything(),
    );
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Zugehörige Einzelantwort ansehen",
      }),
    );
    expect(
      await screen.findByRole("complementary", { name: "Details: Antwort 7" }),
    ).toBeTruthy();
  });

  it("repeats an unconfirmed selection with the same request", async () => {
    const client = fakeClient();
    client.createSurveyResponseSelection.mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );
    await renderPage(base, client);
    await screen.findByRole("heading", {
      level: 2,
      name: "Antwortstand wählen",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Antworten auswählen" }),
    );
    const repeat = await screen.findByRole("button", {
      name: "Auswahl erneut anfordern",
    });
    expect(screen.getByRole("alert").textContent).toContain(
      "Die Anfrage konnte nicht bestätigt werden.",
    );
    await act(async () => fireEvent.click(repeat));
    await screen.findByText("51 Antworten");
    const [first, second] = client.createSurveyResponseSelection.mock.calls;
    expect(second![1]).toEqual(first![1]);
  });

  it("drops a refused selection and lets the person choose again", async () => {
    const client = fakeClient();
    client.getSurveyResponseSelection.mockRejectedValueOnce(
      new ApiError(404, {
        code: "not_found",
        message: "Antwortstand nicht gefunden.",
        requestId: "req-1",
      } as never),
    );
    await renderPage(`${base}?responseSelection=${snapshotId}`, client);
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Antwortstand nicht gefunden.",
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Antwortstand wählen" }),
    ).toBeTruthy();
    expect(client.listSurveyResponses).not.toHaveBeenCalled();
  });
});
