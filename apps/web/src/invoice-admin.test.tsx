import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type {
  CurrentIdentityResponse,
  GeneratedDocumentRecordResponse,
  InvoiceContextResponse,
  InvoiceDeliveryResponse,
  InvoiceRecordResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { InvoiceAdminPage, resetCommandPaletteState } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import {
  parseAmountMinor,
  relativeDay,
  shortDate,
} from "../../../packages/features/src/invoices/invoice-format";
import {
  invoiceListStatus,
  migrateLegacyStatusParam,
} from "../../../packages/features/src/invoices/invoice-model";
import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const actionId = "20000000-0000-4000-8000-000000000001";

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
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/admin/invoices");
  vi.restoreAllMocks();
});

function invoice(
  id: string,
  number: string,
  overrides: {
    readonly status?: InvoiceRecordResponse["invoice"]["status"];
    readonly dueOn?: string;
    readonly openMinor?: number;
    readonly payment?: InvoiceRecordResponse["payment"];
    readonly cancellation?: InvoiceRecordResponse["cancellation"];
    readonly deliveries?: InvoiceDeliveryResponse[];
    readonly buyer?: string;
  } = {},
): InvoiceRecordResponse {
  const status = overrides.status ?? "issued";
  return {
    buyerDisplayName: overrides.buyer ?? "Bäckerei Kern",
    cancellation: overrides.cancellation ?? null,
    deliveries: overrides.deliveries ?? [],
    openMinor:
      overrides.openMinor ??
      (status === "paid" || status === "cancelled" ? 0 : 14_400),
    payment: overrides.payment ?? null,
    invoice: {
      actionId,
      approvedByUserId: "u1",
      commitmentId: `c-${id}`,
      currency: "EUR",
      dueOn: overrides.dueOn ?? "2099-01-15",
      grossMinor: 14_400,
      id,
      issuedAt: "2026-10-01T10:00:00Z",
      issuer: {
        city: "Beispielstadt",
        countryCode: "DE",
        email: "kasse@example.org",
        legalName: "Förderverein Lions Beispiel e. V.",
        postalCode: "10115",
        streetLine1: "Hauptstraße 1",
        taxIdentifier: "27/123/45678",
      },
      lines: [
        {
          currency: "EUR",
          description: "Adventskalender",
          grossMinor: 14_400,
          netMinor: 14_400,
          quantity: 24,
          taxMinor: 0,
          taxRateBasisPoints: 0,
          unit: "piece",
          unitPriceGrossMinor: 600,
        },
      ],
      netMinor: 14_400,
      number,
      paymentDetails: {
        accountHolder: "Förderverein",
        bic: null,
        iban: "DE02120300000000202051",
      },
      paymentReference: number,
      recipient: {
        city: "Beispielstadt",
        countryCode: "DE",
        email: "einkauf@example.org",
        postalCode: "10243",
        recipientName: "Bäckerei Kern GmbH",
        streetLine1: "Sonnenstraße 2",
      },
      replayed: false,
      serviceOn: "2026-10-01",
      status,
      taxMinor: 0,
      taxNote: "Keine USt. (§ 19 UStG)",
      taxTreatment: "small_business",
    },
  };
}

function failedDelivery(invoiceId: string): InvoiceDeliveryResponse {
  return {
    actionId,
    attempts: 1,
    canRetry: true,
    generatedDocumentId: `d-${invoiceId}`,
    id: `delivery-${invoiceId}`,
    invoiceId,
    lastErrorCode: "mailbox_full",
    lastErrorDetail: "Postfach voll",
    messageId: null,
    recipientEmail: "einkauf@example.org",
    requestedAt: "2026-10-02T10:00:00Z",
    sentAt: null,
    status: "failed",
    subject: "Ihre Rechnung",
  };
}

function documentFor(invoiceId: string, number: string) {
  return {
    buyerDisplayName: "Bäckerei Kern",
    invoiceNumber: number,
    document: {
      actionId,
      availableAt: "2026-10-01T10:01:00Z",
      commitmentId: null,
      createdAt: "2026-10-01T10:00:30Z",
      documentType: "invoice_pdf",
      filename: `Rechnung-${number}.pdf`,
      id: `d-${invoiceId}`,
      invoiceId,
      mediaType: "application/pdf",
      renderVersion: "1",
      sentAt: null,
      sizeBytes: 42_000,
      status: "available",
      twentyCompanyId: null,
      twentyPersonId: null,
      version: 1,
    },
  } satisfies GeneratedDocumentRecordResponse;
}

const records: InvoiceRecordResponse[] = [
  invoice("i-open", "KT26-0003", {
    deliveries: [failedDelivery("i-open")],
  }),
  invoice("i-overdue", "KT26-0002", {
    dueOn: "2020-01-01",
    buyer: "Autohaus Nord",
  }),
  invoice("i-paid", "KT26-0001", {
    status: "paid",
    buyer: "Café Mitte",
    payment: {
      actionId,
      amountMinor: 14_400,
      currency: "EUR",
      id: "p1",
      invoiceId: "i-paid",
      receivedOn: "2026-10-05",
      recordedAt: "2026-10-05T12:00:00Z",
      recordedByDisplayName: "Katrin Kolb",
      recordedByUserId: "u2",
      reference: "KT26-0001",
      replayed: false,
    },
  }),
  invoice("i-cancelled", "KT26-0004", {
    status: "cancelled",
    buyer: "Druckerei Süd",
    cancellation: {
      actionId,
      id: "x1",
      invoiceId: "i-cancelled",
      originalStatus: "issued",
      reason: "Doppelt erfasst",
      replayed: false,
      requestedAt: "2026-10-06T12:00:00Z",
      requestedByDisplayName: "Klara Kern",
      requestedByUserId: "u1",
    },
  }),
];

function identity(
  role: "charity_admin" | "finance_reader",
): CurrentIdentityResponse {
  return {
    actionMemberships: [
      {
        actionId,
        actionName: "Adventskalender 2026",
        role,
        roleLabel: role === "charity_admin" ? "Charity-Admin" : "Finanzen",
      },
    ],
    displayName: "Klara Kern",
    email: "klara@example.org",
    freshLoginAt: "2026-11-03T10:00:00Z",
    freshUntil: "2026-11-03T10:10:00Z",
    globalRoles: [],
    navigation: [],
    roleLabels: [],
    sessionExpiresAt: "2026-11-04T10:00:00Z",
  } as unknown as CurrentIdentityResponse;
}

function fakeClient(manage: boolean) {
  const context: InvoiceContextResponse = {
    actionId,
    actionName: "Adventskalender 2026",
    endsOn: "2026-12-24",
    mayIssue: manage,
    mayManageSettlements: manage,
    profile: null,
    startsOn: "2026-10-01",
  };
  const client = {
    getInvoiceContext: vi.fn(async () => context),
    listInvoices: vi.fn(async () => ({
      actionId,
      currencyTotals: [
        { currency: "EUR", grossMinor: 57_600, openMinor: 28_800 },
      ],
      items: records,
    })),
    listActionDocuments: vi.fn(async () => ({
      actionId,
      items: records.map((record) =>
        documentFor(record.invoice.id, record.invoice.number),
      ),
      reference: {},
    })),
    recordInvoicePayment: vi.fn(async () => ({})),
    cancelInvoice: vi.fn(async () => ({})),
    retryInvoiceDelivery: vi.fn(async () => ({})),
    sendInvoice: vi.fn(async () => ({})),
    downloadGeneratedDocument: vi.fn(async () => new Blob()),
  };
  return client;
}

async function renderPage(options: { manage?: boolean; url?: string } = {}) {
  window.history.replaceState(
    null,
    "",
    options.url ?? `/admin/invoices?action=${actionId}`,
  );
  const client = fakeClient(options.manage ?? true);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <HotkeyProvider>
          <InvoiceAdminPage
            client={client as unknown as LeonAidApiClient}
            identity={identity(
              options.manage === false ? "finance_reader" : "charity_admin",
            )}
          />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { level: 1, name: "Rechnungen" });
  await screen.findByTestId("invoice-open-total");
  return client;
}

function rowLink(number: string) {
  const primary = screen
    .getAllByText(number)
    .find((element) => element.closest(".row-link"));
  if (!primary) throw new Error(`row ${number} not shown`);
  return primary.closest("a")!;
}

async function openRow(number: string) {
  fireEvent.click(rowLink(number));
  return within(await screen.findByTestId("invoice-detail"));
}

describe("invoice helpers", () => {
  it("parses German and point decimal amounts", () => {
    expect(parseAmountMinor("144,00")).toBe(14_400);
    expect(parseAmountMinor("1.234,50 €")).toBe(123_450);
    expect(parseAmountMinor("359.99")).toBe(35_999);
    expect(parseAmountMinor("1.234")).toBe(123_400);
    expect(parseAmountMinor("144")).toBe(14_400);
    expect(parseAmountMinor("")).toBeNull();
    expect(parseAmountMinor("abc")).toBeNull();
    expect(parseAmountMinor("1,2,3")).toBeNull();
  });

  it("derives overdue from the due day and keeps server states", () => {
    expect(invoiceListStatus(records[0]!, "2026-11-03")).toBe("open");
    expect(invoiceListStatus(records[1]!, "2026-11-03")).toBe("overdue");
    expect(invoiceListStatus(records[2]!, "2026-11-03")).toBe("paid");
    expect(invoiceListStatus(records[3]!, "2026-11-03")).toBe("cancelled");
  });

  it("formats short and relative days as the prototype does", () => {
    expect(shortDate("2026-11-05", "2026-11-03")).toBe("05.11.");
    expect(shortDate("2025-11-05", "2026-11-03")).toBe("05.11.2025");
    expect(relativeDay("2026-11-03", "2026-11-03")).toBe("Heute");
    expect(relativeDay("2026-11-04", "2026-11-03")).toBe("Morgen");
    expect(relativeDay("2026-11-06", "2026-11-03")).toBe("in 3 Tagen");
    expect(relativeDay("2026-10-31", "2026-11-03")).toBe("vor 3 Tagen");
    expect(relativeDay("2026-12-24", "2026-11-03")).toBe("24.12.");
  });

  it("rewrites the old status filter to a list view", () => {
    window.history.replaceState(
      null,
      "",
      `/admin/invoices?action=${actionId}&status=paid`,
    );
    migrateLegacyStatusParam();
    expect(window.location.search).toBe(`?action=${actionId}&view=paid`);
    window.history.replaceState(null, "", "/admin/invoices?status=open");
    migrateLegacyStatusParam();
    expect(window.location.search).toBe("");
  });
});

describe("InvoiceAdminPage", () => {
  it("shows the open view with the server's open total and read-only status", async () => {
    await renderPage();
    expect(screen.getByTestId("invoice-open-total").textContent).toContain(
      "288,00",
    );
    expect(rowLink("KT26-0003")).toBeTruthy();
    expect(rowLink("KT26-0002")).toBeTruthy();
    expect(
      screen.queryAllByText("KT26-0001").some((el) => el.closest(".row-link")),
    ).toBe(false);
    // Status is never an inline edit: no chip button and no pane property.
    expect(document.querySelector('[data-chip="status"]')).toBeNull();
    const pane = await openRow("KT26-0003");
    expect(document.querySelector(".pane-props")).toBeNull();
    expect(pane.getByRole("button", { name: "Zahlung erfassen" })).toBeTruthy();
  });

  it("maps the old ?status= link to the matching view", async () => {
    await renderPage({ url: `/admin/invoices?action=${actionId}&status=paid` });
    expect(window.location.search).toContain("view=paid");
    expect(rowLink("KT26-0001")).toBeTruthy();
    expect(
      screen.queryAllByText("KT26-0003").some((el) => el.closest(".row-link")),
    ).toBe(false);
  });

  it("records only the exact full payment, with the invoice reference by default", async () => {
    const client = await renderPage();
    const pane = await openRow("KT26-0003");
    fireEvent.click(pane.getByTestId("open-payment-form"));
    const dialog = await screen.findByRole("dialog", {
      name: "Zahlung für KT26-0003 erfassen",
    });
    const amount = within(dialog).getByTestId("payment-amount");
    fireEvent.change(amount, { target: { value: "100,00" } });
    fireEvent.click(within(dialog).getByTestId("record-payment"));
    expect(
      within(dialog).getByText(/Nur die exakte Vollzahlung von 144,00/),
    ).toBeTruthy();
    expect(client.recordInvoicePayment).not.toHaveBeenCalled();

    fireEvent.change(amount, { target: { value: "144,00" } });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("record-payment"));
    });
    expect(client.recordInvoicePayment).toHaveBeenCalledTimes(1);
    const [calledAction, calledInvoice, body, options] = client
      .recordInvoicePayment.mock.calls[0] as unknown as [
      string,
      string,
      { amountMinor: number; reference: string; currency: string },
      { headers: Record<string, string> },
    ];
    expect(calledAction).toBe(actionId);
    expect(calledInvoice).toBe("i-open");
    expect(body).toMatchObject({
      amountMinor: 14_400,
      currency: "EUR",
      reference: "KT26-0003",
    });
    expect(options.headers["Idempotency-Key"]).toMatch(/^poc095:payment:/);
  });

  it("cancels only with a reason of at least eight characters", async () => {
    const client = await renderPage();
    const pane = await openRow("KT26-0003");
    fireEvent.click(pane.getByTestId("open-cancellation-form"));
    const dialog = await screen.findByRole("alertdialog", {
      name: "KT26-0003 stornieren?",
    });
    fireEvent.change(within(dialog).getByTestId("cancellation-reason"), {
      target: { value: "kurz" },
    });
    fireEvent.click(within(dialog).getByTestId("cancel-invoice"));
    expect(within(dialog).getByText(/mindestens 8 Zeichen/)).toBeTruthy();
    expect(client.cancelInvoice).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByTestId("cancellation-reason"), {
      target: { value: "Sponsor hat doppelt bestellt" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("cancel-invoice"));
    });
    expect(client.cancelInvoice).toHaveBeenCalledWith(
      actionId,
      "i-open",
      { reason: "Sponsor hat doppelt bestellt" },
      expect.objectContaining({
        headers: expect.objectContaining({
          "Idempotency-Key": expect.stringMatching(/^poc095:cancellation:/),
        }),
      }),
    );
  });

  it("resends a failed delivery through the explicit retry command", async () => {
    const client = await renderPage();
    const pane = await openRow("KT26-0003");
    expect(pane.getByText(/fehlgeschlagen: Postfach voll/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(pane.getByTestId("retry-invoice-delivery"));
    });
    expect(client.retryInvoiceDelivery).toHaveBeenCalledWith(
      actionId,
      "i-open",
      "delivery-i-open",
    );
  });

  it("stamps cancelled and paid invoices", async () => {
    await renderPage({ url: `/admin/invoices?action=${actionId}&view=all` });
    let pane = await openRow("KT26-0004");
    expect(pane.getByTestId("invoice-stamp").textContent).toContain(
      "Storniert",
    );
    expect(pane.queryByTestId("open-payment-form")).toBeNull();
    pane = await openRow("KT26-0001");
    expect(pane.getByTestId("invoice-stamp").textContent).toContain("Bezahlt");
  });

  it("gives a finance reader no commands and a read-only notice", async () => {
    await renderPage({ manage: false });
    expect(screen.getByTestId("invoice-read-only")).toBeTruthy();
    const pane = await openRow("KT26-0003");
    expect(pane.queryByTestId("open-payment-form")).toBeNull();
    expect(pane.queryByTestId("open-cancellation-form")).toBeNull();
    expect(pane.queryByTestId("retry-invoice-delivery")).toBeNull();
    expect(pane.getByTestId("preview-document")).toBeTruthy();
  });
});
