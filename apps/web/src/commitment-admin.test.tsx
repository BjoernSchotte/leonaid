import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommitmentListResponse,
  CommitmentRecordResponse,
  CommitmentResponse,
  CurrentIdentityResponse,
  InvoiceContextResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import {
  CommitmentAdminPage,
  legacyOrdersSearch,
  resetCommandPaletteState,
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
  navigation: [],
  roleLabels: [],
  sessionExpiresAt: "2026-11-04T10:00:00Z",
  sessionLastSeenAt: "2026-11-03T10:00:00Z",
  userId: "10000000-0000-4000-8000-000000000002",
};

function fakeClient() {
  return {
    listCommitments: vi.fn(async () => list),
    getDeliveryConfiguration: vi.fn(async () => ({
      actionId,
      enabled: false,
      revision: 1,
      timezone: "Europe/Berlin",
      windows: [],
    })),
    getInvoiceContext: vi.fn(async () => invoiceContext),
    issueInvoice: vi.fn(async () => ({
      commitmentId: "c1",
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
