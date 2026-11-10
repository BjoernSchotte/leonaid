import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommitmentListResponse,
  CommitmentRecordResponse,
  CommitmentResponse,
  CurrentIdentityResponse,
  InvoiceContextResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { ApiError } from "@leonaid/api-client";
import {
  CommitmentAdminPage,
  legacyOrdersSearch,
  releaseSelection,
  resetCommandPaletteState,
  runRelease,
} from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

const actionId = "20000000-0000-4000-8000-000000000001";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  // jsdom has no showModal(); enough for the Modal's open/close.
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    if (!this.open) return;
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

beforeEach(() => {
  resetCommandPaletteState();
  window.sessionStorage.clear();
});

function order(
  id: string,
  buyer: string,
  status: CommitmentResponse["status"],
  extra: Partial<CommitmentResponse> = {},
): CommitmentRecordResponse {
  return {
    buyerMailDue: false,
    capturedByDisplayName: "Anna Akquise",
    createdAt: `2026-11-0${id.slice(-1)}T09:00:00Z`,
    commitment: {
      actionId,
      buyer: {
        displayName: buyer,
        email: null,
        partyKind: "company",
        twentyId: `t-${id}`,
      },
      currency: "EUR",
      deliveryCompletionVersion: "v1",
      id,
      invoiceRecipient: {
        city: "Augsburg",
        countryCode: "DE",
        email: null,
        postalCode: "86150",
        recipientName: buyer,
        streetLine1: "Löwenweg 12",
      },
      publicReference: `LA-${id.toUpperCase().padStart(32, "0")}`,
      lines: [
        {
          boxCount: 2,
          currency: "EUR",
          description: "Krapfenbox",
          id: `l-${id}`,
          lineTotalMinor: 7200,
          offeringId: "o1",
          pieceCount: 48,
          piecesPerUnit: 24,
          quantity: 2,
          unit: "box",
          unitPriceMinor: 3600,
        },
      ],
      quantities: [{ quantity: 2, unit: "box" }],
      replayed: false,
      source: "acquisition",
      status,
      totalBoxes: 2,
      totalMinor: 7200,
      totalPieces: 48,
      ...extra,
    },
  };
}

const rows = [
  order("c1", "Musterwerk GmbH", "review_ready"),
  order("c2", "Bäckerei Kern", "draft", { invoiceRecipient: null }),
  order("c3", "Autohaus Nord", "invoiced"),
  order("c4", "Café Mitte", "review_ready", { source: "public_form" }),
];

const list: CommitmentListResponse = {
  actionId,
  currencyTotals: [{ currency: "EUR", totalMinor: 28800 }],
  items: rows,
  quantities: [{ quantity: 8, unit: "box" }],
  totalBoxes: 8,
  totalPieces: 192,
};

const invoiceContext: InvoiceContextResponse = {
  actionId,
  actionName: "Krapfentaxi",
  endsOn: "2026-11-30",
  mayIssue: true,
  mayManageSettlements: true,
  startsOn: "2026-11-01",
  profile: {
    confirmedAt: "2026-10-01T00:00:00Z",
    issuer: {
      city: "Augsburg",
      legalName: "Lions Hilfswerk e. V.",
      postalCode: "86150",
      streetLine1: "Rathausplatz 1",
      taxIdentifier: "DE123",
    },
    legalConfigurationVersionId: null,
    nextInvoiceNumber: "KT26-0004",
    paymentDetails: null,
    paymentTermsDays: 14,
    readyToIssue: true,
    taxNote: "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.",
    taxRateBasisPoints: 0,
    taxTreatment: "small_business",
  } as InvoiceContextResponse["profile"],
};

const identity: CurrentIdentityResponse = {
  actionMemberships: [
    { actionId, actionName: "Krapfentaxi", role: "charity_admin" },
  ] as CurrentIdentityResponse["actionMemberships"],
  displayName: "Klara Kern",
  email: "klara@example.org",
  freshLoginAt: "2026-11-03T10:00:00Z",
  freshUntil: "2026-11-03T10:10:00Z",
  globalRoles: [],
  installation: { clubName: "Lions Club Musterstadt" },
  navigation: [],
  roleLabels: [],
  sessionExpiresAt: "2026-11-04T10:00:00Z",
  sessionLastSeenAt: "2026-11-03T10:00:00Z",
  landingPath: "/admin/",
  userId: "10000000-0000-4000-8000-000000000002",
};

function fakeClient() {
  return {
    listCommitments: vi.fn(async () => list),
    listBuyerMails: vi.fn(async (_action: string, commitmentId: string) => ({
      commitmentId,
      completion: null,
      mails: [
        {
          canResend: false,
          kind: "confirmation",
          reason: "switched_off",
          sentAt: null,
          state: "not_due",
        },
      ],
    })),
    getDeliveryConfiguration: vi.fn(async () => ({
      actionId,
      enabled: false,
      revision: 1,
      timezone: "Europe/Berlin",
      windows: [],
    })),
    getInvoiceContext: vi.fn(async () => invoiceContext),
    issueInvoice: vi.fn(async (_action: string, commitmentId: string) => ({
      commitmentId,
      currency: "EUR",
      grossMinor: 7200,
      id: `inv-${commitmentId}`,
      number: "KT26-0004",
    })),
  } as unknown as LeonAidApiClient & {
    issueInvoice: ReturnType<typeof vi.fn>;
  };
}

async function renderPage(search: string, client = fakeClient()) {
  window.history.replaceState(null, "", `/admin/orders${search}`);
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queries}>
      <ToastProvider>
        <HotkeyProvider>
          <CommitmentAdminPage client={client} identity={identity} />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findByTestId("commitment-totals");
  return client;
}

const rowNames = () =>
  [...document.querySelectorAll("[data-order-id]")].map(
    (element) => element.textContent,
  );

describe("legacy orders URLs", () => {
  it("maps a status tab to the list view's filter", () => {
    expect(legacyOrdersSearch("?status=review_ready&action=a")).toBe(
      "?action=a&view=all&f.status=review_ready",
    );
    expect(legacyOrdersSearch("?status=all")).toBe("?view=all");
    expect(legacyOrdersSearch("?status=bogus")).toBe("");
    // The list's own state wins over the old parameter.
    expect(legacyOrdersSearch("?view=todo&status=invoiced")).toBe("?view=todo");
  });

  it("opens the order an activity or invoice link names", () => {
    expect(legacyOrdersSearch("?commitment=c1")).toBe("?open=c1");
    // `invoice` stays first: the fresh sign-in returns to this URL.
    expect(legacyOrdersSearch("?invoice=c1&action=a")).toBe(
      "?invoice=c1&action=a&open=c1",
    );
    expect(legacyOrdersSearch("?invoice=c1&open=c1")).toBeNull();
    expect(legacyOrdersSearch("?action=a")).toBeNull();
  });
});

describe("orders list", () => {
  it("opens on Zu prüfen: review-ready and draft orders, grouped by status", async () => {
    await renderPage("");
    expect(rowNames()).toEqual([
      "Café Mitte",
      "Musterwerk GmbH",
      "Bäckerei Kern",
    ]);
    expect(
      screen.getByRole("button", { name: "Zu prüfen", pressed: true }),
    ).toBeTruthy();
    const totals = screen.getByTestId("commitment-totals");
    expect(totals.dataset.totalMinor).toBe("28800");
    expect(totals.dataset.totalBoxes).toBe("8");
    expect(totals.textContent).toContain("288,00");
    // The order lacking an invoice address is flagged.
    expect(screen.getAllByRole("img", { name: "Angaben fehlen" })).toHaveLength(
      1,
    );
  });

  it("keeps the old status links working", async () => {
    await renderPage(`?action=${actionId}&status=invoiced`);
    expect(rowNames()).toEqual(["Autohaus Nord"]);
    expect(new URLSearchParams(window.location.search).get("status")).toBe(
      null,
    );
  });

  it("offers no inline status edit: the server's commands change it", async () => {
    await renderPage("");
    const row = screen
      .getByText("Musterwerk GmbH")
      .closest("li") as HTMLElement;
    expect(within(row).queryByRole("button", { name: /ändern/ })).toBeNull();
    act(() => {
      (within(row).getByRole("link") as HTMLElement).focus();
    });
    fireEvent.keyDown(document.activeElement!, { key: "s" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("restores the invoice review from ?invoice= and issues with an idempotency key", async () => {
    const client = await renderPage(`?invoice=c1&action=${actionId}`);
    const review = await screen.findByTestId("invoice-review");
    expect(review.textContent).toContain("KT26-0004");
    expect(new URLSearchParams(window.location.search).get("open")).toBe("c1");
    fireEvent.click(within(review).getByTestId("issue-invoice"));
    await screen.findByText("Rechnung KT26-0004 ist verbindlich freigegeben.");
    expect(client.issueInvoice).toHaveBeenCalledWith(
      actionId,
      "c1",
      { serviceOn: "2026-11-30" },
      {
        headers: {
          "Idempotency-Key": expect.stringMatching(/^poc090:/),
        },
      },
    );
    expect(new URLSearchParams(window.location.search).get("invoice")).toBe(
      null,
    );
    expect(screen.queryByTestId("invoice-review")).toBeNull();
  });

  it("opens the review from the pane's next step and closes it with the pane", async () => {
    await renderPage("?open=c1");
    fireEvent.click(await screen.findByTestId("review-invoice"));
    expect(await screen.findByTestId("invoice-review")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("invoice")).toBe(
      "c1",
    );
    fireEvent.click(screen.getByRole("button", { name: "Prüfung schließen" }));
    expect(screen.queryByTestId("invoice-review")).toBeNull();
    expect(new URLSearchParams(window.location.search).get("invoice")).toBe(
      null,
    );
  });

  it("keeps one primary in the next step and steps aside while editing", async () => {
    await renderPage("?open=c1");
    const review = await screen.findByTestId("review-invoice");
    const block = review.closest(".next-step") as HTMLElement;
    // One primary action, the alternative is a ghost (DESIGN.md).
    expect(block.querySelectorAll(".btn-primary")).toHaveLength(1);
    const edit = within(block).getByTestId("commitment-edit-details");
    expect(edit.classList.contains("btn-ghost")).toBe(true);
    fireEvent.click(edit);
    // The form's save is now the one primary: the block steps aside.
    expect(screen.queryByTestId("review-invoice")).toBeNull();
    fireEvent.click(await screen.findByTestId("commitment-edit-close"));
    expect(await screen.findByTestId("review-invoice")).toBeTruthy();
  });

  it("shows a read-only note instead of the review when the server says so", async () => {
    const client = fakeClient();
    (client.getInvoiceContext as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...invoiceContext,
      mayIssue: false,
    });
    await renderPage("?open=c1", client);
    expect(await screen.findByText(/Nur lesen\./)).toBeTruthy();
    expect(screen.queryByTestId("review-invoice")).toBeNull();
  });
});

const apiError = (status: number, code: string, message = code) =>
  new ApiError(status, { code, message, requestId: "" });

describe("bulk invoice release", () => {
  it("lets through what the single review would, and says why not", () => {
    const delivered = {
      deliveryRecipient: {
        city: "Augsburg",
        postalCode: "86150",
        recipientName: "Lager",
        streetLine1: "Lagerweg 1",
      },
      deliveryWindowId: "w1",
    };
    const ready = order("c5", "Lieferbar GmbH", "review_ready", delivered);
    const noWindow = order("c6", "Ohne Fenster", "review_ready");
    const selection = releaseSelection(
      [ready, rows[1]!, rows[2]!, noWindow],
      true,
    );
    expect(selection.eligible.map((row) => row.commitment.id)).toEqual(["c5"]);
    expect(
      selection.skipped.map(({ row, reason }) => [row.commitment.id, reason]),
    ).toEqual([
      ["c2", "status"],
      ["c3", "status"],
      ["c6", "delivery"],
    ]);
    // Without delivery planning the window is not required.
    expect(releaseSelection([noWindow], false).eligible).toHaveLength(1);
    expect(
      releaseSelection(
        [
          order("c7", "Ohne Adresse", "review_ready", {
            invoiceRecipient: null,
          }),
        ],
        false,
      ).skipped[0]?.reason,
    ).toBe("recipient");
  });

  it("goes on after a refused order and stops on missing rights", async () => {
    const invoice = (id: string) =>
      ({ commitmentId: id, number: `KT-${id}` }) as never;
    const mixed = await runRelease(["a", "b", "c"], async (id) => {
      if (id === "b")
        throw apiError(409, "invoice_commitment_not_review_ready");
      return invoice(id);
    });
    expect([...mixed.outcomes.values()].map((item) => item.kind)).toEqual([
      "issued",
      "failed",
      "issued",
    ]);
    expect(mixed.stop).toBeNull();

    const forbidden = await runRelease(["a", "b"], async () => {
      throw apiError(403, "invoice_issue_required", "Nur Charity-Admins");
    });
    expect(forbidden.stop).toEqual({
      kind: "forbidden",
      message: "Nur Charity-Admins",
    });
    expect(forbidden.outcomes.get("b")).toEqual({ kind: "not-run" });

    const fresh = await runRelease(["a", "b"], async () => {
      throw apiError(403, "fresh_login_required");
    });
    expect(fresh.stop).toEqual({ kind: "fresh-login" });
    expect([...fresh.outcomes.values()].map((item) => item.kind)).toEqual([
      "not-run",
      "not-run",
    ]);

    const issue = vi.fn(async (id: string) => {
      if (id === "b") throw new TypeError("Failed to fetch");
      return invoice(id);
    });
    const lost = await runRelease(["a", "b", "c"], issue);
    expect([...lost.outcomes.values()].map((item) => item.kind)).toEqual([
      "issued",
      "unconfirmed",
      "not-run",
    ]);
    expect(lost.stop).toEqual({ kind: "network" });
    expect(issue).toHaveBeenCalledTimes(2);
  });

  it("reviews the checked orders and issues each once with its own key", async () => {
    const client = await renderPage("?view=all");
    const check = (name: string) =>
      fireEvent.click(
        screen.getByRole("checkbox", { name: new RegExp(`^${name} ·`) }),
      );
    check("Musterwerk GmbH");
    check("Bäckerei Kern");
    const open = await screen.findByTestId("bulk-release-open");
    expect(open.textContent).toContain("1 von 2 freigebbar");
    fireEvent.click(open);
    const dialog = await screen.findByTestId("bulk-release");
    expect(
      [...dialog.querySelectorAll("[data-release-id]")].map((row) =>
        row.getAttribute("data-release-id"),
      ),
    ).toEqual(["c1"]);
    // Each row names its order by the order number, not by a part of the id.
    expect(dialog.querySelector("[data-release-id]")?.textContent).toContain(
      "LA-000000000000000000000000000000C1",
    );
    expect(dialog.textContent).toContain("Bäckerei Kern (nicht prüfbereit)");
    expect(within(dialog).getByTestId("bulk-release-total").textContent).toBe(
      "72,00\u00a0€",
    );
    fireEvent.change(within(dialog).getByLabelText("Leistungsdatum"), {
      target: { value: "2026-11-20" },
    });
    const submit = screen.getByTestId("bulk-release-submit");
    expect(submit.textContent).toContain("1 Rechnung verbindlich ausstellen");
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(
      await screen.findByRole("heading", { name: "Ergebnis der Freigabe" }),
    ).toBeTruthy();
    expect(screen.getByTestId("bulk-release-issued").textContent).toContain(
      "KT26-0004",
    );
    expect(client.issueInvoice).toHaveBeenCalledTimes(1);
    expect(client.issueInvoice).toHaveBeenCalledWith(
      actionId,
      "c1",
      { serviceOn: "2026-11-20" },
      {
        headers: { "Idempotency-Key": expect.stringMatching(/^poc090:/) },
        // A hanging request ends instead of locking the dialog.
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("offers no bulk release where the server refuses issuing", async () => {
    const client = fakeClient();
    (client.getInvoiceContext as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...invoiceContext,
      mayIssue: false,
    });
    await renderPage("?view=all", client);
    fireEvent.click(
      screen.getByRole("checkbox", { name: /^Musterwerk GmbH ·/ }),
    );
    expect(await screen.findByText("1 ausgewählt")).toBeTruthy();
    expect(screen.queryByTestId("bulk-release-open")).toBeNull();
  });

  it("reports a refused order and still issues the others", async () => {
    const client = fakeClient();
    client.issueInvoice.mockImplementation(
      async (_action: string, commitmentId: string) => {
        if (commitmentId === "c4")
          throw apiError(
            409,
            "invoice_delivery_incomplete",
            "Lieferung fehlt.",
          );
        return {
          commitmentId,
          currency: "EUR",
          grossMinor: 7200,
          id: `inv-${commitmentId}`,
          number: `KT-${commitmentId}`,
          replayed: commitmentId === "c1",
          serviceOn: "2026-11-02",
        };
      },
    );
    await renderPage("?view=all", client);
    for (const name of ["Musterwerk GmbH", "Café Mitte"])
      fireEvent.click(
        screen.getByRole("checkbox", { name: new RegExp(`^${name} ·`) }),
      );
    fireEvent.click(await screen.findByTestId("bulk-release-open"));
    fireEvent.click(await screen.findByTestId("bulk-release-submit"));
    const issued = await screen.findByTestId("bulk-release-issued");
    expect(issued.textContent).toContain("KT-c1");
    expect(issued.textContent).toContain(
      "war bereits ausgestellt, keine zweite Rechnung; Leistungsdatum 02.11.2026",
    );
    expect(screen.getByTestId("bulk-release-failed").textContent).toContain(
      "Café Mitte: Lieferung fehlt.",
    );
    expect(client.issueInvoice).toHaveBeenCalledTimes(2);
  });

  it("resumes a release that stopped for the fresh sign-in", async () => {
    window.sessionStorage.setItem(
      `leonaid.bulk-release.${actionId}`,
      JSON.stringify({
        ids: ["c1", "c3"],
        serviceOn: "2026-11-12",
        savedAt: Date.now(),
      }),
    );
    await renderPage("?view=all");
    const dialog = await screen.findByTestId("bulk-release");
    expect(
      [...dialog.querySelectorAll("[data-release-id]")].map((row) =>
        row.getAttribute("data-release-id"),
      ),
    ).toEqual(["c1"]);
    expect(
      (within(dialog).getByLabelText("Leistungsdatum") as HTMLInputElement)
        .value,
    ).toBe("2026-11-12");
    // Read once: a reload does not reopen it.
    expect(
      window.sessionStorage.getItem(`leonaid.bulk-release.${actionId}`),
    ).toBeNull();
  });

  it("treats gateway errors and foreign pages as a lost answer, not a refusal", async () => {
    for (const cause of [
      apiError(502, "http_502"),
      apiError(503, "http_503"),
      apiError(504, "http_504"),
      apiError(200, "unexpected_response_type"),
    ]) {
      const issue = vi.fn(async (id: string) => {
        if (id === "b") throw cause;
        return { commitmentId: id, number: `KT-${id}` } as never;
      });
      const run = await runRelease(["a", "b", "c"], issue);
      expect([...run.outcomes.values()].map((item) => item.kind)).toEqual([
        "issued",
        "unconfirmed",
        "not-run",
      ]);
      expect(run.stop).toEqual({ kind: "network" });
      expect(issue).toHaveBeenCalledTimes(2);
    }
  });

  it("explains a key already used with other data", async () => {
    const run = await runRelease(["a"], async () => {
      throw apiError(409, "idempotency_conflict");
    });
    expect(run.outcomes.get("a")).toEqual({
      kind: "failed",
      message: expect.stringContaining("anderen Leistungsdatum"),
    });
    expect(run.stop).toBeNull();
  });

  it("sends the same key and date again after a lost answer", async () => {
    const client = fakeClient();
    let lost = false;
    client.issueInvoice.mockImplementation(
      async (_action: string, commitmentId: string) => {
        if (commitmentId === "c4" && !lost) {
          lost = true;
          throw new TypeError("Failed to fetch");
        }
        return {
          commitmentId,
          currency: "EUR",
          grossMinor: 7200,
          id: `inv-${commitmentId}`,
          number: `KT-${commitmentId}`,
          replayed: commitmentId === "c4",
          serviceOn: "2026-11-20",
        };
      },
    );
    await renderPage("?view=all", client);
    for (const name of ["Musterwerk GmbH", "Café Mitte"])
      fireEvent.click(
        screen.getByRole("checkbox", { name: new RegExp(`^${name} ·`) }),
      );
    fireEvent.click(await screen.findByTestId("bulk-release-open"));
    const dialog = await screen.findByTestId("bulk-release");
    fireEvent.change(within(dialog).getByLabelText("Leistungsdatum"), {
      target: { value: "2026-11-20" },
    });
    fireEvent.click(screen.getByTestId("bulk-release-submit"));
    const unfinished = await screen.findByTestId("bulk-release-unfinished");
    // List order: Café Mitte (c4) is newer and goes first; c1 is not sent.
    expect(unfinished.textContent).toContain("Café Mitte: Keine Antwort");
    expect(unfinished.textContent).toContain(
      "Musterwerk GmbH: nicht gesendet.",
    );
    expect(client.issueInvoice).toHaveBeenCalledTimes(1);

    fireEvent.click(
      screen.getByRole("button", { name: "2 Rechnungen erneut senden" }),
    );
    const issued = await screen.findByText("Ausgestellt (2)");
    expect(issued).toBeTruthy();
    expect(screen.queryByTestId("bulk-release-unfinished")).toBeNull();
    const calls = client.issueInvoice.mock.calls.filter(
      ([, id]) => id === "c4",
    );
    expect(calls).toHaveLength(2);
    const [first, second] = calls;
    expect(second![2]).toEqual(first![2]);
    expect(second![2]).toEqual({ serviceOn: "2026-11-20" });
    expect(second![3].headers["Idempotency-Key"]).toBe(
      first![3].headers["Idempotency-Key"],
    );
    expect(first![3].headers["Idempotency-Key"]).toMatch(/^poc090:/);
    expect(screen.getByTestId("bulk-release-issued").textContent).toContain(
      "Café Mitte",
    );
  });

  it("names the invoices issued before the fresh sign-in", async () => {
    window.sessionStorage.setItem(
      `leonaid.bulk-release.${actionId}`,
      JSON.stringify({
        ids: ["c1"],
        serviceOn: "2026-11-12",
        issued: [{ id: "c4", number: "KT26-0009", buyer: "Café Mitte" }],
        savedAt: Date.now(),
      }),
    );
    await renderPage("?view=all");
    expect(
      (await screen.findByTestId("bulk-release-issued-before")).textContent,
    ).toBe("KT26-0009 (Café Mitte)");
  });

  it("keeps the key in memory when sessionStorage fails", async () => {
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("quota", "QuotaExceededError");
      });
    const client = fakeClient();
    let lost = false;
    client.issueInvoice.mockImplementation(
      async (_action: string, commitmentId: string) => {
        if (!lost) {
          lost = true;
          throw new TypeError("Failed to fetch");
        }
        return {
          commitmentId,
          currency: "EUR",
          grossMinor: 7200,
          id: `inv-${commitmentId}`,
          number: "KT26-0010",
          replayed: true,
          serviceOn: "2026-11-30",
        };
      },
    );
    try {
      await renderPage("?view=all", client);
      fireEvent.click(
        screen.getByRole("checkbox", { name: /^Musterwerk GmbH ·/ }),
      );
      fireEvent.click(await screen.findByTestId("bulk-release-open"));
      fireEvent.click(await screen.findByTestId("bulk-release-submit"));
      fireEvent.click(
        await screen.findByRole("button", { name: "1 Rechnung erneut senden" }),
      );
      await screen.findByText("Ausgestellt (1)");
      const [first, second] = client.issueInvoice.mock.calls;
      expect(second![3].headers["Idempotency-Key"]).toBe(
        first![3].headers["Idempotency-Key"],
      );
    } finally {
      setItem.mockRestore();
    }
  });

  it("treats a timeout or rate limit on the way as a lost answer", async () => {
    for (const cause of [
      apiError(408, "http_408"),
      apiError(429, "rate_limited"),
    ]) {
      const run = await runRelease(["a", "b"], async (id) => {
        if (id === "a") throw cause;
        return { commitmentId: id, number: `KT-${id}` } as never;
      });
      expect([...run.outcomes.values()].map((item) => item.kind)).toEqual([
        "unconfirmed",
        "not-run",
      ]);
      expect(run.stop).toEqual({ kind: "network" });
    }
  });

  it("drops a key the server refused as already used, keeps lost ones", async () => {
    const client = fakeClient();
    client.issueInvoice.mockImplementation(async () => {
      throw apiError(409, "idempotency_conflict");
    });
    await renderPage("?view=all", client);
    const release = async () => {
      fireEvent.click(
        screen.getByRole("checkbox", { name: /^Musterwerk GmbH ·/ }),
      );
      fireEvent.click(await screen.findByTestId("bulk-release-open"));
      fireEvent.click(await screen.findByTestId("bulk-release-submit"));
      await screen.findByTestId("bulk-release-failed");
      fireEvent.click(
        within(document.querySelector<HTMLElement>(".modal-footer")!).getByRole(
          "button",
          { name: "Schließen" },
        ),
      );
    };
    await release();
    expect(
      window.sessionStorage.getItem("leonaid.invoice-command.c1"),
    ).toBeNull();
    await release();
    const keys = client.issueInvoice.mock.calls.map(
      (call) => call[3].headers["Idempotency-Key"],
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe(keys[1]);

    // A lost answer keeps the key for the retry.
    client.issueInvoice.mockImplementation(async () => {
      throw new TypeError("Failed to fetch");
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: /^Musterwerk GmbH ·/ }),
    );
    fireEvent.click(await screen.findByTestId("bulk-release-open"));
    fireEvent.click(await screen.findByTestId("bulk-release-submit"));
    await screen.findByTestId("bulk-release-unfinished");
    expect(window.sessionStorage.getItem("leonaid.invoice-command.c1")).toBe(
      client.issueInvoice.mock.calls[2]![3].headers["Idempotency-Key"],
    );
  });

  it("gives the single review a fresh key after a key conflict", async () => {
    const client = fakeClient();
    client.issueInvoice.mockRejectedValueOnce(
      apiError(409, "idempotency_conflict", "Vorgangs-ID schon verwendet."),
    );
    await renderPage(`?invoice=c1&action=${actionId}`, client);
    const review = await screen.findByTestId("invoice-review");
    fireEvent.click(within(review).getByTestId("issue-invoice"));
    await within(review).findByText(/Vorgangs-ID schon verwendet/);
    fireEvent.click(within(review).getByTestId("issue-invoice"));
    await screen.findByText("Rechnung KT26-0004 ist verbindlich freigegeben.");
    const keys = client.issueInvoice.mock.calls.map(
      (call) => call[3].headers["Idempotency-Key"],
    );
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toBe(keys[1]);
  });
});

describe("order cancellation", () => {
  const issuedInvoice = (number: string, paymentRecorded = false) => ({
    id: "inv-c3",
    number,
    paidMinor: paymentRecorded ? 3000 : 0,
    paymentRecorded,
    recipientEmail: null as string | null,
    // A partial payment leaves the invoice open (ADR-0014).
    status: "issued" as const,
  });

  function clientWith(items: CommitmentRecordResponse[]) {
    const client = fakeClient();
    (client.listCommitments as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...list,
      items,
    });
    const cancel = vi.fn(
      async (
        _action: string,
        commitmentId: string,
        _body?: unknown,
        _options?: unknown,
      ) => ({
        cancellation: {
          id: "cx1",
          invoiceNumber: commitmentId === "c3" ? "KT26-0001" : null,
          invoiceCancellationNumber: commitmentId === "c3" ? "KT26-0005" : null,
          previousStatus: "review_ready",
          reason: "Sponsor hat die Bestellung zurückgezogen",
          requestedAt: "2026-11-05T10:15:00Z",
        },
        commitment: { id: commitmentId, status: "cancelled" },
        replayed: false,
      }),
    );
    Object.assign(client, { cancelCommitment: cancel });
    return { client, cancel };
  }

  const reasonField = (dialog: HTMLElement) =>
    within(dialog).getByTestId(
      "order-cancellation-reason",
    ) as HTMLTextAreaElement;
  const noteField = (dialog: HTMLElement) =>
    within(dialog).getByTestId(
      "order-cancellation-note",
    ) as HTMLTextAreaElement;

  it("cancels with reason, note, version and key and says the buyer is not e-mailed", async () => {
    const { client, cancel } = clientWith(rows);
    await renderPage("?view=all&open=c1", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(
      "LeonAid benachrichtigt den Besteller nicht automatisch.",
    );
    // No invoice yet: nothing about an invoice.
    expect(dialog.textContent).not.toContain("mitstorniert");
    fireEvent.change(reasonField(dialog), { target: { value: "zu kurz" } });
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    expect(
      await within(dialog).findByText(
        "Bitte geben Sie einen Grund mit mindestens 8 Zeichen an.",
      ),
    ).toBeTruthy();
    expect(cancel).not.toHaveBeenCalled();
    fireEvent.change(reasonField(dialog), {
      target: { value: " Sponsor hat die Bestellung zurückgezogen " },
    });
    fireEvent.change(noteField(dialog), {
      target: { value: "Rückruf am Montag." },
    });
    const listCalls = (client.listCommitments as ReturnType<typeof vi.fn>).mock
      .calls.length;
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    await screen.findByText("Bestellung storniert.");
    expect(cancel).toHaveBeenCalledWith(
      actionId,
      "c1",
      {
        expectedVersion: "v1",
        note: "Rückruf am Montag.",
        reason: "Sponsor hat die Bestellung zurückgezogen",
      },
      {
        headers: {
          "Idempotency-Key": expect.stringMatching(/^order-cancellation:/),
        },
      },
    );
    expect(
      (client.listCommitments as ReturnType<typeof vi.fn>).mock.calls.length,
    ).toBeGreaterThan(listCalls);
    // The key is used up: a new cancellation would get a new one.
    expect(
      window.sessionStorage.getItem("leonaid.order-cancellation.c1"),
    ).toBeNull();
  });

  it("tells that the buyer gets an e-mail when the server says so", async () => {
    // The server decides (buyerMailDue); here an order a member entered,
    // in an action that sends mails for such orders.
    const notified = {
      ...order("c4", "Café Mitte", "review_ready", {
        buyer: {
          displayName: "Café Mitte",
          email: "kasse@cafe-mitte.leonaid.invalid",
          partyKind: "company",
          twentyId: "t-c4",
        },
        source: "admin",
      }),
      buyerMailDue: true,
    };
    const { client } = clientWith([notified]);
    await renderPage("?view=all&open=c4", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(
      "Der Besteller erhält eine E-Mail über die Stornierung, ohne Grund und Notiz.",
    );
    expect(dialog.textContent).not.toContain("nicht automatisch");
  });

  it("does not copy the rule: a public order without buyerMailDue is not announced", async () => {
    const erased = order("c4", "Café Mitte", "review_ready", {
      buyer: {
        displayName: "Café Mitte",
        email: "kasse@cafe-mitte.leonaid.invalid",
        partyKind: "company",
        twentyId: "t-c4",
      },
      source: "public_form",
    });
    const { client } = clientWith([erased]);
    await renderPage("?view=all&open=c4", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(
      "LeonAid benachrichtigt den Besteller nicht automatisch.",
    );
  });

  it("names the open invoice it cancels with the order", async () => {
    const withInvoice = { ...rows[2]!, invoice: issuedInvoice("KT26-0001") };
    const { client, cancel } = clientWith([withInvoice]);
    await renderPage("?view=all&open=c3", client);
    // The pane links the invoice in the journal.
    const link = await screen.findByRole("link", { name: "KT26-0001" });
    expect(link.getAttribute("href")).toBe(
      `/admin/invoices?action=${actionId}&view=all&open=inv-c3`,
    );
    fireEvent.click(screen.getByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(
      "Rechnung KT26-0001 wird mitstorniert.",
    );
    expect(dialog.textContent).toContain("Nummer, Daten und PDF");
    expect(dialog.textContent).toContain(
      "LeonAid stellt dazu eine Stornorechnung aus.",
    );
    fireEvent.change(reasonField(dialog), {
      target: { value: "Sponsor hat die Bestellung zurückgezogen" },
    });
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    await screen.findByText(
      "Rechnung KT26-0001 ist ebenfalls storniert. Stornorechnung KT26-0005 wurde ausgestellt.",
    );
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("offers to send the cancellation invoice when the invoice was mailed", async () => {
    // The address is the one frozen on the invoice: the order's own
    // recipient has none here, and the server sends to the invoice's.
    const mailed = {
      ...rows[2]!,
      invoice: {
        ...issuedInvoice("KT26-0001"),
        recipientEmail: "einkauf@example.org",
        status: "sent" as const,
      },
    };
    const { client, cancel } = clientWith([mailed]);
    await renderPage("?view=all&open=c3", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    const box = within(dialog).getByTestId(
      "send-invoice-cancellation-with-order",
    ) as HTMLInputElement;
    // On by default: the buyer who got the invoice gets its cancellation.
    expect(box.checked).toBe(true);
    expect(dialog.textContent).toContain("einkauf@example.org");
    // The note about mails is true next to the option, ticked or not.
    expect(dialog.textContent).toContain(
      "Der Rechnungsempfänger erhält die Stornorechnung per E-Mail.",
    );
    expect(dialog.textContent).not.toContain(
      "LeonAid benachrichtigt den Besteller nicht automatisch.",
    );
    fireEvent.click(box);
    expect(dialog.textContent).toContain(
      "LeonAid benachrichtigt den Besteller nicht automatisch.",
    );
    fireEvent.click(box);
    fireEvent.change(reasonField(dialog), {
      target: { value: "Sponsor hat die Bestellung zurückgezogen" },
    });
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    await screen.findByText("Bestellung storniert.");
    expect(cancel.mock.calls[0]![2]).toMatchObject({
      sendInvoiceCancellation: true,
    });
  });

  it("does not offer to send when the invoice itself has no address", async () => {
    // The order got an address later; the sent invoice has none. Offering
    // the send would make the server refuse the whole cancellation.
    const { client, cancel } = clientWith([
      {
        ...rows[2]!,
        commitment: {
          ...rows[2]!.commitment,
          invoiceRecipient: {
            ...rows[2]!.commitment.invoiceRecipient!,
            email: "neu@example.org",
          },
        },
        invoice: { ...issuedInvoice("KT26-0001"), status: "sent" as const },
      },
    ]);
    await renderPage("?view=all&open=c3", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).queryByTestId("send-invoice-cancellation-with-order"),
    ).toBeNull();
    fireEvent.change(reasonField(dialog), {
      target: { value: "Sponsor hat die Bestellung zurückgezogen" },
    });
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    await screen.findByText("Bestellung storniert.");
    expect(cancel.mock.calls[0]![2]).not.toHaveProperty(
      "sendInvoiceCancellation",
    );
  });

  it("explains why a delivered order cannot be cancelled", async () => {
    const { client, cancel } = clientWith([{ ...rows[0]!, delivered: true }]);
    await renderPage("?view=all&open=c1", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "bereits geliefert",
    );
    expect(
      (within(dialog).getByTestId("cancel-order") as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      within(dialog).queryByTestId("order-cancellation-reason"),
    ).toBeNull();
    expect(cancel).not.toHaveBeenCalled();
  });

  it("asks to take back a booked payment first", async () => {
    const paid = { ...rows[2]!, invoice: issuedInvoice("KT26-0002", true) };
    const { client, cancel } = clientWith([paid]);
    await renderPage("?view=all&open=c3", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "Zur Rechnung KT26-0002 ist eine Zahlung erfasst. Buchen Sie die Zahlung in der Rechnung erst zurück (Zahlung zurückbuchen)",
    );
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    expect(cancel).not.toHaveBeenCalled();
  });

  it("shows the server's refusal and reloads the list", async () => {
    const { client, cancel } = clientWith(rows);
    cancel.mockRejectedValueOnce(
      apiError(
        409,
        "commitment_cancellation_conflict",
        "Die Bestellung wurde inzwischen geändert.",
      ),
    );
    await renderPage("?view=all&open=c1", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.change(reasonField(dialog), {
      target: { value: "Sponsor hat die Bestellung zurückgezogen" },
    });
    const listCalls = (client.listCommitments as ReturnType<typeof vi.fn>).mock
      .calls.length;
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    await within(dialog).findByText(/inzwischen geändert/);
    expect(
      (client.listCommitments as ReturnType<typeof vi.fn>).mock.calls.length,
    ).toBeGreaterThan(listCalls);
    // What was typed stays for the next attempt.
    expect(reasonField(dialog).value).toBe(
      "Sponsor hat die Bestellung zurückgezogen",
    );
  });

  it("keeps what was typed across the fresh sign-in", async () => {
    const withInvoice = { ...rows[2]!, invoice: issuedInvoice("KT26-0001") };
    const { client, cancel } = clientWith([withInvoice]);
    cancel.mockRejectedValueOnce(
      apiError(401, "fresh_login_required", "Anmeldung bestätigen"),
    );
    await renderPage("?view=all&open=c3", client);
    fireEvent.click(await screen.findByTestId("open-order-cancellation"));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.change(reasonField(dialog), {
      target: { value: "Sponsor hat die Bestellung zurückgezogen" },
    });
    fireEvent.change(noteField(dialog), {
      target: { value: "Notiz vor der Anmeldung" },
    });
    fireEvent.click(within(dialog).getByTestId("cancel-order"));
    await within(dialog).findByText(
      "Für diese Änderung wird Ihre Anmeldung erneut bestätigt.",
    );
    const key = window.sessionStorage.getItem("leonaid.order-cancellation.c3");
    expect(key).toMatch(/^order-cancellation:/);
    // Back from /fresh-login: the pane reopens the dialog with the draft.
    cleanup();
    await renderPage("?view=all&open=c3", client);
    const restored = await screen.findByRole("alertdialog");
    expect(reasonField(restored).value).toBe(
      "Sponsor hat die Bestellung zurückgezogen",
    );
    expect(noteField(restored).value).toBe("Notiz vor der Anmeldung");
    fireEvent.click(within(restored).getByTestId("cancel-order"));
    await screen.findByText("Bestellung storniert.");
    // The same command, the same key: the server applies it once.
    expect(cancel.mock.calls[1]![3]).toEqual({
      headers: { "Idempotency-Key": key },
    });
  });

  it("shows a cancelled order with stamp, reason, note and history, without the action", async () => {
    const cancelled: CommitmentRecordResponse = {
      ...rows[0]!,
      commitment: { ...rows[0]!.commitment, status: "cancelled" },
      cancellation: {
        id: "cx1",
        invoiceCancellationNumber: null,
        invoiceNumber: null,
        note: "Rückruf am Montag.\nKunde informiert.",
        previousStatus: "review_ready",
        reason: "Sponsor hat die Bestellung zurückgezogen.",
        requestedAt: "2026-11-05T10:15:00Z",
        requestedByDisplayName: "Klara Kern",
      },
    };
    const { client } = clientWith([cancelled, rows[1]!]);
    await renderPage("?view=all&open=c1", client);
    const stamp = await screen.findByTestId("order-stamp");
    expect(stamp.textContent).toContain("Storniert");
    expect(stamp.textContent).toContain(
      "Grund: Sponsor hat die Bestellung zurückgezogen. Die Bestellung bleibt",
    );
    const section = screen.getByTestId("order-cancellation");
    expect(section.textContent).toContain("Rückruf am Montag.");
    expect(section.textContent).toContain("Es gab keine Rechnung.");
    expect(screen.getByText("Storniert von Klara Kern")).toBeTruthy();
    expect(screen.queryByTestId("open-order-cancellation")).toBeNull();
    // The list keeps it, struck through, with the status "Storniert".
    const row = document
      .querySelector('[data-order-id="c1"]')!
      .closest("li") as HTMLElement;
    expect(row.querySelector(".is-struck")).toBeTruthy();
  });
});

describe("order number and buyer mails in the order pane", () => {
  type Mail = Awaited<
    ReturnType<LeonAidApiClient["listBuyerMails"]>
  >["mails"][number];

  function clientWithMails(mails: Mail[]) {
    const client = fakeClient();
    const listBuyerMails = vi.fn(
      async (_action: string, commitmentId: string) => ({
        commitmentId,
        completion: null,
        mails,
      }),
    );
    const resendBuyerMail = vi.fn(
      async (
        _action: string,
        _commitmentId: string,
        kind: Mail["kind"],
        _options?: unknown,
      ): Promise<Mail & { replayed: boolean }> => ({
        canResend: false,
        kind,
        reason: null,
        replayed: false,
        sentAt: "2026-11-05T10:15:00Z",
        state: "queued",
      }),
    );
    Object.assign(client, { listBuyerMails, resendBuyerMail });
    return { client, listBuyerMails, resendBuyerMail };
  }

  it("shows the order number and finds the order by it", async () => {
    await renderPage("?view=all&open=c1");
    const pane = await screen.findByRole("complementary");
    expect(pane.textContent).toContain(
      "BestellnummerLA-000000000000000000000000000000C1",
    );
    cleanup();
    await renderPage("?view=all&q=LA-000000000000000000000000000000C3");
    expect(rowNames().join(" ")).toContain("Autohaus Nord");
    expect(rowNames().join(" ")).not.toContain("Musterwerk GmbH");
  });

  it("says why no mail is due and offers no resend", async () => {
    const { client, listBuyerMails } = clientWithMails([
      {
        canResend: false,
        kind: "confirmation",
        reason: "switched_off",
        sentAt: null,
        state: "not_due",
      },
    ]);
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    await within(block).findByText("Bestellbestätigung");
    expect(listBuyerMails).toHaveBeenCalledWith(actionId, "c1");
    expect(block.textContent).toContain("Nicht fällig");
    expect(block.textContent).toContain(
      "E-Mails für Bestellungen, die Mitglieder erfassen, sind in der Aktion ausgeschaltet.",
    );
    expect(within(block).queryByRole("button")).toBeNull();
  });

  it("sends a sent mail again once, with an idempotency key", async () => {
    const { client, listBuyerMails, resendBuyerMail } = clientWithMails([
      {
        canResend: true,
        kind: "confirmation",
        reason: null,
        sentAt: "2026-11-04T08:30:00Z",
        state: "sent",
      },
      {
        canResend: false,
        kind: "cancellation",
        reason: "recipient_limit",
        sentAt: null,
        state: "failed",
      },
    ]);
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    const button = await within(block).findByTestId(
      "buyer-mail-resend-confirmation",
    );
    expect(block.textContent).toContain("Gesendet am 04.11.2026, 09:30");
    expect(block.textContent).toContain("Fehlgeschlagen");
    expect(block.textContent).toContain(
      "An dieses Postfach gingen in der letzten Stunde zu viele E-Mails.",
    );
    // Only where the server allows it.
    expect(
      within(block).queryByTestId("buyer-mail-resend-cancellation"),
    ).toBeNull();
    const calls = listBuyerMails.mock.calls.length;
    fireEvent.click(button);
    await screen.findByText("Bestellbestätigung wird erneut gesendet.");
    expect(resendBuyerMail).toHaveBeenCalledTimes(1);
    expect(resendBuyerMail).toHaveBeenCalledWith(
      actionId,
      "c1",
      "confirmation",
      {
        headers: {
          "Idempotency-Key": expect.stringMatching(/^buyer-mail-resend:/),
        },
      },
    );
    // The block reloads, and the key is used up.
    expect(listBuyerMails.mock.calls.length).toBeGreaterThan(calls);
    expect(
      window.sessionStorage.getItem(
        "leonaid.buyer-mail-resend.c1.confirmation",
      ),
    ).toBeNull();
  });

  it("shows the server's refusal of a resend", async () => {
    const { client, resendBuyerMail } = clientWithMails([
      {
        canResend: true,
        kind: "confirmation",
        reason: null,
        sentAt: "2026-11-04T08:30:00Z",
        state: "sent",
      },
    ]);
    resendBuyerMail.mockRejectedValue(
      new ApiError(409, {
        code: "buyer_mail_already_queued",
        message: "Diese E-Mail wartet bereits auf den Versand.",
        requestId: "req-1",
      }),
    );
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    fireEvent.click(
      await within(block).findByTestId("buyer-mail-resend-confirmation"),
    );
    expect(
      await within(block).findByText(
        /Diese E-Mail wartet bereits auf den Versand\./,
      ),
    ).toBeTruthy();
  });
});

describe("buyer mails: first send, lost answer and the other states", () => {
  type Mail = Awaited<
    ReturnType<LeonAidApiClient["listBuyerMails"]>
  >["mails"][number];

  function clientWithMails(mails: Mail[], replayed = false) {
    const client = fakeClient();
    const listBuyerMails = vi.fn(
      async (_action: string, commitmentId: string) => ({
        commitmentId,
        completion: null,
        mails,
      }),
    );
    const resendBuyerMail = vi.fn(
      async (
        _action: string,
        _commitmentId: string,
        kind: Mail["kind"],
        _options?: unknown,
      ) => ({
        canResend: false,
        kind,
        reason: null,
        replayed,
        sentAt: null,
        state: "queued" as const,
      }),
    );
    Object.assign(client, { listBuyerMails, resendBuyerMail });
    return { client, listBuyerMails, resendBuyerMail };
  }

  const neverSent: Mail = {
    canResend: true,
    kind: "confirmation",
    reason: "not_requested",
    sentAt: null,
    state: "not_due",
  };

  it("offers Senden for a mail that is due and never went out", async () => {
    const { client, resendBuyerMail } = clientWithMails([neverSent]);
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    const button = await within(block).findByRole("button", {
      name: "Bestellbestätigung senden",
    });
    expect(button.textContent).toBe("Senden");
    // Due and sendable: the badge does not say "Nicht fällig".
    expect(block.textContent).toContain("Nicht gesendet");
    expect(block.textContent).not.toContain("Nicht fällig");
    // The server does not know why: the text claims no reason.
    expect(block.textContent).toContain(
      "Für diese Bestellung ist noch keine E-Mail hinausgegangen.",
    );
    expect(block.textContent).not.toContain("ausgeschaltet");
    fireEvent.click(button);
    await screen.findByText("Bestellbestätigung wird gesendet.");
    expect(resendBuyerMail).toHaveBeenCalledTimes(1);
  });

  it("offers Senden after a job that ended without a mail", async () => {
    const { client } = clientWithMails([
      { ...neverSent, reason: "not_sent", state: "skipped" },
    ]);
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    await within(block).findByRole("button", {
      name: "Bestellbestätigung senden",
    });
    expect(block.textContent).toContain("Nicht gesendet");
    expect(block.textContent).toContain("Die E-Mail ist nicht hinausgegangen.");
  });

  it("says that a repeated click after a lost answer sent nothing new", async () => {
    const { client } = clientWithMails(
      [
        {
          ...neverSent,
          sentAt: "2026-11-04T08:30:00Z",
          state: "sent",
          reason: null,
        },
      ],
      true,
    );
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    fireEvent.click(
      await within(block).findByRole("button", {
        name: "Bestellbestätigung erneut senden",
      }),
    );
    await screen.findByText(
      "Bestellbestätigung: Der Auftrag von vorhin ist angekommen. Es geht keine weitere E-Mail hinaus.",
    );
    expect(screen.queryByText(/wird erneut gesendet/)).toBeNull();
  });

  it("keeps the key after a lost answer and drops it after a refusal", async () => {
    const { client, resendBuyerMail } = clientWithMails([
      {
        ...neverSent,
        sentAt: "2026-11-04T08:30:00Z",
        state: "sent",
        reason: null,
      },
    ]);
    resendBuyerMail.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    const button = await within(block).findByRole("button", {
      name: "Bestellbestätigung erneut senden",
    });
    fireEvent.click(button);
    await within(block).findByText(/konnte gerade nicht gespeichert werden/);
    const kept = window.sessionStorage.getItem(
      "leonaid.buyer-mail-resend.c1.confirmation",
    );
    expect(kept).toMatch(/^buyer-mail-resend:/);
    // The next click sends the same key: the server replays, no second mail.
    fireEvent.click(
      await within(block).findByRole("button", {
        name: "Bestellbestätigung erneut senden",
      }),
    );
    await waitFor(() => expect(resendBuyerMail).toHaveBeenCalledTimes(2));
    const keys = resendBuyerMail.mock.calls.map(
      (call) =>
        (call[3] as { headers: Record<string, string> }).headers[
          "Idempotency-Key"
        ],
    );
    expect(keys).toEqual([kept, kept]);
  });

  it("says that a confirmation came too late and is not sent any more", async () => {
    // R1: queued in time, reached by the worker after the window.
    const { client } = clientWithMails([
      {
        canResend: false,
        kind: "confirmation",
        reason: "window_over",
        sentAt: null,
        state: "failed",
      },
    ]);
    await renderPage("?view=all&open=c1", client);
    const block = await screen.findByTestId("buyer-mails");
    await within(block).findByText("Bestellbestätigung");
    expect(block.textContent).toContain("Fehlgeschlagen");
    expect(block.textContent).toContain(
      "Die E-Mail kam nicht rechtzeitig hinaus und wird nicht mehr gesendet. Das Lieferfenster ist vorbei.",
    );
    expect(within(block).queryByRole("button")).toBeNull();
  });

  it("shows a waiting mail without a button and asks again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { client, listBuyerMails } = clientWithMails([
        {
          canResend: false,
          kind: "confirmation",
          reason: null,
          sentAt: "2026-11-04T08:30:00Z",
          state: "queued",
        },
      ]);
      await renderPage("?view=all&open=c1", client);
      const block = await screen.findByTestId("buyer-mails");
      await within(block).findByText("Wartet");
      expect(block.textContent).toContain(
        "Wartet auf den Versand. Zuletzt gesendet am 04.11.2026, 09:30.",
      );
      expect(within(block).queryByRole("button")).toBeNull();
      const calls = listBuyerMails.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5100);
      });
      expect(listBuyerMails.mock.calls.length).toBeGreaterThan(calls);
      // Not for ever: after two minutes the block stops asking.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5 * 60_000);
      });
      const settled = listBuyerMails.mock.calls.length;
      expect(settled).toBeLessThanOrEqual(calls + 25);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(listBuyerMails.mock.calls.length).toBe(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("names the reasons a confirmation comes too late", async () => {
    for (const [reason, text] of [
      ["delivery_recorded", "Die Lieferung ist schon als geliefert"],
      ["window_over", "Das Lieferfenster ist vorbei."],
      ["action_closed", "Die Aktion ist abgeschlossen."],
    ] as const) {
      const { client } = clientWithMails([
        { ...neverSent, canResend: false, reason },
      ]);
      await renderPage("?view=all&open=c1", client);
      const block = await screen.findByTestId("buyer-mails");
      await within(block).findByText("Bestellbestätigung");
      expect(block.textContent).toContain(text);
      expect(within(block).queryByRole("button")).toBeNull();
      cleanup();
    }
  });
});
