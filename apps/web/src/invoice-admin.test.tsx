import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
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
  localIsoDate,
  parseAmountMinor,
  relativeDay,
  shortDate,
} from "../../../packages/features/src/invoices/invoice-format";
import {
  invoiceListStatus,
  invoiceRows,
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
    cancellationDeliveries: [],
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
    kind: "invoice",
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

function sentDelivery(invoiceId: string): InvoiceDeliveryResponse {
  return {
    ...failedDelivery(invoiceId),
    canRetry: false,
    lastErrorCode: null,
    lastErrorDetail: null,
    messageId: "<m1@example.org>",
    sentAt: "2026-10-02T10:01:00Z",
    status: "sent",
  };
}

type Cancellation = NonNullable<InvoiceRecordResponse["cancellation"]>;

/** A cancelled invoice as the current server sends it. */
function cancelledInvoice(
  id: string,
  number: string,
  cancellation: Partial<Cancellation> = {},
  cancellationDeliveries: InvoiceDeliveryResponse[] = [],
): InvoiceRecordResponse {
  return {
    ...invoice(id, number, {
      status: "cancelled",
      cancellation: {
        actionId,
        id: `x-${id}`,
        invoiceId: id,
        issuedOn: "2026-10-06",
        number: "KT26-0009",
        originalStatus: "issued",
        reason: "Doppelt erfasst",
        receivedMinor: 0,
        refundNote: null,
        refundOpen: false,
        refundSettledAt: null,
        refundSettledByDisplayName: null,
        refundSettledOn: null,
        refundWithdrawals: [],
        replayed: false,
        requestedAt: "2026-10-06T12:00:00Z",
        requestedByDisplayName: "Klara Kern",
        requestedByUserId: "u1",
        ...cancellation,
      },
    }),
    cancellationDeliveries,
  };
}

function cancellationDocumentFor(
  invoiceId: string,
  status: "pending" | "available" = "available",
): GeneratedDocumentRecordResponse {
  const base = documentFor(invoiceId, "KT26-0004");
  return {
    ...base,
    documentNumber: "KT26-0009",
    document: {
      ...base.document,
      availableAt: status === "available" ? "2026-10-06T12:01:00Z" : null,
      documentType: "invoice_cancellation_pdf",
      filename: "Stornorechnung-KT26-0009.pdf",
      id: `dx-${invoiceId}`,
      status,
    },
  };
}

function documentFor(invoiceId: string, number: string) {
  return {
    buyerDisplayName: "Bäckerei Kern",
    documentNumber: null,
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
      issuedOn: null,
      number: null,
      originalStatus: "issued",
      reason: "Doppelt erfasst",
      receivedMinor: 0,
      refundNote: null,
      refundOpen: false,
      refundSettledAt: null,
      refundSettledByDisplayName: null,
      refundSettledOn: null,
      refundWithdrawals: [],
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

function fakeClient(
  manage: boolean,
  items: readonly InvoiceRecordResponse[] = records,
  extraDocuments: readonly GeneratedDocumentRecordResponse[] = [],
  mayIssue: boolean = manage,
) {
  const context: InvoiceContextResponse = {
    actionId,
    actionName: "Adventskalender 2026",
    endsOn: "2026-12-24",
    mayIssue,
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
      items,
    })),
    listActionDocuments: vi.fn(async () => ({
      actionId,
      // Newest first, as the server lists them.
      items: [
        ...extraDocuments,
        ...items.map((record) =>
          documentFor(record.invoice.id, record.invoice.number),
        ),
      ],
      reference: {},
    })),
    recordInvoicePayment: vi.fn(async () => ({})),
    reverseInvoicePayment: vi.fn(async () => ({})),
    cancelInvoice: vi.fn(async (): Promise<Partial<Cancellation>> => ({})),
    retryInvoiceDelivery: vi.fn(async () => ({})),
    sendInvoice: vi.fn(async () => ({})),
    sendInvoiceCancellation: vi.fn(async () => ({})),
    retryInvoiceCancellationDelivery: vi.fn(async () => ({})),
    issueInvoiceCancellationDocument: vi.fn(
      async (): Promise<Partial<Cancellation>> => ({ number: "KT26-0011" }),
    ),
    settleInvoiceCancellationRefund: vi.fn(async () => ({})),
    withdrawInvoiceCancellationRefund: vi.fn(async () => ({})),
    downloadGeneratedDocument: vi.fn(async () => new Blob()),
  };
  return client;
}

async function renderPage(
  options: {
    manage?: boolean;
    /** Server right `mayIssue` when it differs from `manage`. */
    mayIssue?: boolean;
    url?: string;
    items?: readonly InvoiceRecordResponse[];
    documents?: readonly GeneratedDocumentRecordResponse[];
  } = {},
) {
  window.history.replaceState(
    null,
    "",
    options.url ?? `/admin/invoices?action=${actionId}`,
  );
  const client = fakeClient(
    options.manage ?? true,
    options.items,
    options.documents,
    options.mayIssue,
  );
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

function entry(
  id: string,
  amountMinor: number,
  receivedOn: string,
  options: { reversed?: boolean } = {},
): NonNullable<InvoiceRecordResponse["payments"]>[number] {
  return {
    actionId,
    amountMinor,
    currency: "EUR",
    id,
    invoiceId: "i",
    note: null,
    receivedOn,
    recordedAt: `${receivedOn}T12:00:00Z`,
    recordedByDisplayName: "Finn Finanzen",
    recordedByUserId: "u7",
    reference: "Bankumsatz",
    replayed: false,
    reversal: options.reversed
      ? {
          actionId,
          id: `r-${id}`,
          invoiceId: "i",
          paymentId: id,
          reason: "Lastschrift zurückgegeben",
          replayed: false,
          reversedAt: "2026-10-07T09:00:00Z",
          reversedByDisplayName: "Finn Finanzen",
          reversedByUserId: "u7",
        }
      : null,
  };
}

/** A record as the current server sends it, with every payment entry. */
function settled(
  id: string,
  number: string,
  payments: NonNullable<InvoiceRecordResponse["payments"]>,
): InvoiceRecordResponse {
  const paidMinor = payments
    .filter((payment) => !payment.reversal)
    .reduce((sum, payment) => sum + payment.amountMinor, 0);
  const base = invoice(id, number);
  return {
    ...base,
    invoice: {
      ...base.invoice,
      status: paidMinor >= 14_400 ? "paid" : "issued",
    },
    openMinor: Math.max(14_400 - paidMinor, 0),
    overpaidMinor: Math.max(paidMinor - 14_400, 0),
    paidMinor,
    payment: payments.filter((payment) => !payment.reversal).at(-1) ?? null,
    payments,
    settlementStatus:
      paidMinor > 14_400
        ? "overpaid"
        : paidMinor === 14_400
          ? "paid"
          : paidMinor === 0
            ? "open"
            : "partially_paid",
    settlementVersion: payments.reduce(
      (sum, payment) => sum + (payment.reversal ? 2 : 1),
      0,
    ),
  };
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

  it("prefills the remainder so a full payment stays one click", async () => {
    const client = await renderPage();
    const pane = await openRow("KT26-0003");
    fireEvent.click(pane.getByTestId("open-payment-form"));
    const dialog = await screen.findByRole("dialog", {
      name: "Zahlung für KT26-0003 erfassen",
    });
    const amount = within(dialog).getByTestId(
      "payment-amount",
    ) as HTMLInputElement;
    expect(amount.value).toBe("144,00");
    expect(
      within(dialog).getByText("Vollständige Zahlung des offenen Betrags."),
    ).toBeTruthy();
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("record-payment"));
    });
    expect(client.recordInvoicePayment).toHaveBeenCalledTimes(1);
    const [calledAction, calledInvoice, body, options] = client
      .recordInvoicePayment.mock.calls[0] as unknown as [
      string,
      string,
      Record<string, unknown>,
      { headers: Record<string, string> },
    ];
    expect(calledAction).toBe(actionId);
    expect(calledInvoice).toBe("i-open");
    expect(body).toMatchObject({
      amountMinor: 14_400,
      currency: "EUR",
      reference: "KT26-0003",
      note: null,
      expectedSettlementVersion: 0,
    });
    expect(options.headers["Idempotency-Key"]).toMatch(/^poc095:payment:/);
  });

  it("records a partial and an over payment with live remainder hints", async () => {
    const client = await renderPage();
    const pane = await openRow("KT26-0003");
    fireEvent.click(pane.getByTestId("open-payment-form"));
    const dialog = await screen.findByRole("dialog", {
      name: "Zahlung für KT26-0003 erfassen",
    });
    const amount = within(dialog).getByTestId("payment-amount");
    fireEvent.change(amount, { target: { value: "0" } });
    fireEvent.click(within(dialog).getByTestId("record-payment"));
    expect(within(dialog).getByText(/größer als 0,00/)).toBeTruthy();
    fireEvent.change(amount, { target: { value: "150,00" } });
    expect(within(dialog).getByText(/Überzahlung um 6,00/)).toBeTruthy();
    fireEvent.change(amount, { target: { value: "100,00" } });
    expect(
      within(dialog).getByText(/Danach bleiben 44,00\s€ offen/),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByTestId("payment-note"), {
      target: { value: "Rest folgt im Dezember" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("record-payment"));
    });
    expect(client.recordInvoicePayment).toHaveBeenCalledWith(
      actionId,
      "i-open",
      expect.objectContaining({
        amountMinor: 10_000,
        note: "Rest folgt im Dezember",
      }),
      expect.anything(),
    );
  });

  it("cancels only with a reason of at least eight characters", async () => {
    const client = await renderPage();
    const pane = await openRow("KT26-0003");
    fireEvent.click(pane.getByTestId("open-cancellation-form"));
    const dialog = await screen.findByRole("alertdialog", {
      name: "KT26-0003 stornieren?",
    });
    expect(dialog.textContent).toContain(
      "LeonAid stellt dazu eine Stornorechnung aus",
    );
    expect(dialog.textContent).toContain(
      "erfassen Sie danach eine neue Bestellung und stellen deren Rechnung aus",
    );
    // Never sent and nothing received: no send option, no refund note.
    expect(
      within(dialog).queryByTestId("send-cancellation-with-cancel"),
    ).toBeNull();
    expect(within(dialog).queryByTestId("cancellation-received")).toBeNull();
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

  it("offers to send the cancellation invoice when the invoice was sent", async () => {
    const sent = invoice("i-sent", "KT26-0012", {
      deliveries: [sentDelivery("i-sent")],
    });
    const client = await renderPage({ items: [sent] });
    client.cancelInvoice.mockResolvedValueOnce({ number: "KT26-0013" });
    const pane = await openRow("KT26-0012");
    fireEvent.click(pane.getByTestId("open-cancellation-form"));
    const dialog = await screen.findByRole("alertdialog", {
      name: "KT26-0012 stornieren?",
    });
    const checkbox = within(dialog).getByRole("checkbox", {
      name: "Stornorechnung gleich senden",
    }) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    expect(dialog.textContent).toContain("per E-Mail an einkauf@example.org");
    fireEvent.change(within(dialog).getByTestId("cancellation-reason"), {
      target: { value: "Sponsor hat doppelt bestellt" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("cancel-invoice"));
    });
    expect(client.cancelInvoice).toHaveBeenCalledWith(
      actionId,
      "i-sent",
      { reason: "Sponsor hat doppelt bestellt", sendCancellation: true },
      expect.anything(),
    );
    expect(
      await screen.findByText(
        "KT26-0012 storniert. Stornorechnung KT26-0013 ausgestellt.",
      ),
    ).toBeTruthy();
  });

  it("cancels without sending when the box is unchecked", async () => {
    const sent = invoice("i-sent", "KT26-0012", {
      deliveries: [sentDelivery("i-sent")],
    });
    const client = await renderPage({ items: [sent] });
    const pane = await openRow("KT26-0012");
    fireEvent.click(pane.getByTestId("open-cancellation-form"));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByTestId("send-cancellation-with-cancel"),
    );
    fireEvent.change(within(dialog).getByTestId("cancellation-reason"), {
      target: { value: "Sponsor hat doppelt bestellt" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("cancel-invoice"));
    });
    expect(client.cancelInvoice).toHaveBeenCalledWith(
      actionId,
      "i-sent",
      { reason: "Sponsor hat doppelt bestellt", sendCancellation: false },
      expect.anything(),
    );
  });

  it("hides the send option from a manager who may not send", async () => {
    const sent = invoice("i-sent", "KT26-0012", {
      deliveries: [sentDelivery("i-sent")],
    });
    await renderPage({ items: [sent], mayIssue: false });
    const pane = await openRow("KT26-0012");
    fireEvent.click(pane.getByTestId("open-cancellation-form"));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).queryByTestId("send-cancellation-with-cancel"),
    ).toBeNull();
  });

  it("explains the refund when the invoice to cancel received money", async () => {
    const paid = settled("i-paid2", "KT26-0014", [
      entry("p-g", 14_400, "2026-10-04"),
    ]);
    await renderPage({
      items: [paid],
      url: `/admin/invoices?action=${actionId}&view=paid`,
    });
    const pane = await openRow("KT26-0014");
    fireEvent.click(pane.getByTestId("open-cancellation-form"));
    const dialog = await screen.findByRole("alertdialog");
    const note = within(dialog).getByTestId("cancellation-received");
    expect(note.textContent).toMatch(/144,00\s€ eingegangen/);
    expect(note.textContent).toContain("Die Zahlung bleibt erfasst");
    expect(note.textContent).toContain("„Erstattung erledigt“");
  });

  it("shows the cancellation invoice with number, date, PDF and delivery", async () => {
    const cancelled = cancelledInvoice("i-x", "KT26-0004");
    const client = await renderPage({
      items: [cancelled],
      documents: [cancellationDocumentFor("i-x")],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    expect(rowLink("KT26-0004").textContent).toContain(
      "storniert · Stornorechnung KT26-0009",
    );
    expect(rowLink("KT26-0004").parentElement!.textContent).not.toContain(
      "Erstattung offen",
    );
    const pane = await openRow("KT26-0004");
    const section = within(pane.getByTestId("cancellation-invoice"));
    expect(section.getByText("KT26-0009")).toBeTruthy();
    expect(section.getByText("06.10.2026")).toBeTruthy();
    expect(section.queryByTestId("issue-cancellation-document")).toBeNull();
    expect(section.queryByTestId("cancellation-refund")).toBeNull();
    // Each PDF keeps its own row: the invoice's and the cancellation's.
    expect(pane.getByTestId("invoice-document").textContent).toContain(
      "Rechnung-KT26-0004.pdf",
    );
    expect(section.getByTestId("cancellation-document").textContent).toContain(
      "Stornorechnung-KT26-0009.pdf",
    );
    expect(
      section.getByTestId("preview-cancellation-document").getAttribute("href"),
    ).toContain("/documents/dx-i-x/download");

    const delivery = within(pane.getByTestId("cancellation-delivery"));
    expect(delivery.getByText("Noch nicht versendet")).toBeTruthy();
    // The cancelled invoice itself is no longer sent.
    expect(pane.queryByTestId("send-invoice")).toBeNull();
    await act(async () => {
      fireEvent.click(delivery.getByTestId("send-cancellation"));
    });
    expect(client.sendInvoiceCancellation).toHaveBeenCalledWith(
      actionId,
      "i-x",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Idempotency-Key": expect.stringMatching(
            /^invoice:cancellation-delivery:/,
          ),
        }),
      }),
    );
  });

  it("waits for the PDF of the cancellation invoice before sending", async () => {
    await renderPage({
      items: [cancelledInvoice("i-x", "KT26-0004")],
      documents: [cancellationDocumentFor("i-x", "pending")],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    const pane = await openRow("KT26-0004");
    const pdf = pane.getByTestId("cancellation-document");
    expect(pdf.getAttribute("data-state")).toBe("pending");
    expect(pdf.textContent).toContain("wird gerade erzeugt");
    expect(pane.queryByTestId("send-cancellation")).toBeNull();
    expect(
      pane.getByText(/sobald das PDF der Stornorechnung bereitsteht/),
    ).toBeTruthy();
  });

  it("retries a failed delivery of the cancellation invoice", async () => {
    const failed = {
      ...failedDelivery("i-x"),
      kind: "invoice_cancellation" as const,
      subject: "Stornorechnung KT26-0009",
    };
    const client = await renderPage({
      items: [cancelledInvoice("i-x", "KT26-0004", {}, [failed])],
      documents: [cancellationDocumentFor("i-x")],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    const pane = await openRow("KT26-0004");
    expect(
      pane.getByText(/Versand der Stornorechnung an .* fehlgeschlagen/),
    ).toBeTruthy();
    expect(
      pane.getByTestId("cancellation-delivery").getAttribute("data-state"),
    ).toBe("failed");
    await act(async () => {
      fireEvent.click(pane.getByTestId("retry-cancellation-delivery"));
    });
    expect(client.retryInvoiceCancellationDelivery).toHaveBeenCalledWith(
      actionId,
      "i-x",
      "delivery-i-x",
    );
    expect(client.retryInvoiceDelivery).not.toHaveBeenCalled();
  });

  it("issues the cancellation invoice of an older cancellation", async () => {
    // records[3] is a cancellation from before the release: no number.
    const client = await renderPage({
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    expect(rowLink("KT26-0004").textContent).toContain(
      "storniert · Doppelt erfasst",
    );
    const pane = await openRow("KT26-0004");
    const section = within(pane.getByTestId("cancellation-invoice"));
    expect(
      section.getByText(/bevor LeonAid Stornorechnungen ausgestellt hat/),
    ).toBeTruthy();
    expect(pane.queryByTestId("cancellation-delivery")).toBeNull();
    expect(section.queryByTestId("cancellation-document")).toBeNull();
    await act(async () => {
      fireEvent.click(
        section.getByRole("button", { name: "Stornorechnung ausstellen" }),
      );
    });
    expect(client.issueInvoiceCancellationDocument).toHaveBeenCalledWith(
      actionId,
      "i-cancelled",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Idempotency-Key": expect.stringMatching(
            /^invoice:cancellation-document:/,
          ),
        }),
      }),
    );
    expect(
      await screen.findByText("Stornorechnung KT26-0011 ausgestellt."),
    ).toBeTruthy();
  });

  it("marks an open refund in the list and settles it", async () => {
    const refundOpen = cancelledInvoice("i-r", "KT26-0004", {
      originalStatus: "paid",
      receivedMinor: 7_200,
      refundOpen: true,
    });
    const client = await renderPage({
      items: [refundOpen],
      documents: [cancellationDocumentFor("i-r")],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    expect(rowLink("KT26-0004").parentElement!.textContent).toContain(
      "Erstattung offen",
    );
    const pane = await openRow("KT26-0004");
    expect(pane.getByTestId("invoice-refund-open").textContent).toMatch(
      /Erstattung offen: Erhalten: 72,00\s€/,
    );
    expect(
      pane.getByTestId("cancellation-received-amount").textContent,
    ).toContain("72,00");
    expect(pane.getByTestId("cancellation-refund").textContent).toBe(
      "Erstattung offen",
    );
    fireEvent.click(pane.getByRole("button", { name: "Erstattung erledigt" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Erstattung für KT26-0004 erledigt?",
    });
    expect(dialog.textContent).toContain("LeonAid bucht keine Erstattung");
    const date = within(dialog).getByTestId("refund-date") as HTMLInputElement;
    expect(date.value).toBe(localIsoDate());
    expect(date.max).toBe(localIsoDate());
    // Not in the future and not before the invoice existed; a day before
    // the cancellation is fine (the club may have paid back first).
    expect(date.min).toBe("2026-10-01");
    fireEvent.change(date, { target: { value: "2999-01-01" } });
    fireEvent.click(within(dialog).getByTestId("settle-refund"));
    expect(
      within(dialog).getByText(
        "Das Datum liegt zwischen dem Rechnungsdatum und heute.",
      ),
    ).toBeTruthy();
    expect(client.settleInvoiceCancellationRefund).not.toHaveBeenCalled();
    fireEvent.change(date, { target: { value: "2026-10-08" } });
    fireEvent.change(within(dialog).getByTestId("refund-note"), {
      target: { value: "Rücküberweisung vom Vereinskonto" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("settle-refund"));
    });
    expect(client.settleInvoiceCancellationRefund).toHaveBeenCalledWith(
      actionId,
      "i-r",
      { settledOn: "2026-10-08", note: "Rücküberweisung vom Vereinskonto" },
      {
        headers: {
          "Idempotency-Key": expect.stringMatching(/^poc095:refund/),
        },
      },
    );
    expect(
      await screen.findByText(
        "Erstattung für KT26-0004 als erledigt vermerkt.",
      ),
    ).toBeTruthy();
  });

  it("shows a settled refund with day, person and note", async () => {
    const settledRefund = cancelledInvoice("i-r", "KT26-0004", {
      originalStatus: "paid",
      receivedMinor: 7_200,
      refundNote: "Rücküberweisung vom Vereinskonto",
      refundOpen: false,
      refundSettledAt: "2026-10-08T09:00:00Z",
      refundSettledByDisplayName: "Finn Finanzen",
      refundSettledOn: "2026-10-08",
    });
    await renderPage({
      items: [settledRefund],
      documents: [cancellationDocumentFor("i-r")],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    expect(rowLink("KT26-0004").parentElement!.textContent).not.toContain(
      "Erstattung offen",
    );
    const pane = await openRow("KT26-0004");
    expect(pane.queryByTestId("invoice-refund-open")).toBeNull();
    expect(pane.queryByTestId("open-refund-form")).toBeNull();
    expect(pane.getByTestId("cancellation-refund").textContent).toBe(
      "Erstattung erledigt am 08.10.2026 · Finn Finanzen",
    );
    expect(pane.getByText("Rücküberweisung vom Vereinskonto")).toBeTruthy();
  });

  it("takes a refund marker back with a reason", async () => {
    const settledRefund = cancelledInvoice("i-r", "KT26-0004", {
      originalStatus: "paid",
      receivedMinor: 7_200,
      refundSettledAt: "2026-10-08T09:00:00Z",
      refundSettledByDisplayName: "Finn Finanzen",
      refundSettledOn: "2026-10-08",
    });
    const client = await renderPage({
      items: [settledRefund],
      documents: [cancellationDocumentFor("i-r")],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    const pane = await openRow("KT26-0004");
    fireEvent.click(pane.getByTestId("open-refund-withdrawal-form"));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Erstattung für KT26-0004 zurücknehmen?",
    });
    // No reason, no command.
    fireEvent.click(within(dialog).getByTestId("withdraw-refund"));
    expect(client.withdrawInvoiceCancellationRefund).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByTestId("refund-withdrawal-reason"), {
      target: { value: "Falsche Rechnung angeklickt" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("withdraw-refund"));
    });
    expect(client.withdrawInvoiceCancellationRefund).toHaveBeenCalledWith(
      actionId,
      "i-r",
      { reason: "Falsche Rechnung angeklickt" },
      {
        headers: {
          "Idempotency-Key": expect.stringMatching(/^poc095:refund-withdrawal/),
        },
      },
    );
    expect(
      await screen.findByText("Erstattung für KT26-0004 ist wieder offen."),
    ).toBeTruthy();
  });

  it("shows who set and who withdrew an earlier refund marker", async () => {
    const reopened = cancelledInvoice("i-r", "KT26-0004", {
      originalStatus: "paid",
      receivedMinor: 7_200,
      refundOpen: true,
      refundWithdrawals: [
        {
          id: "w1",
          note: null,
          reason: "Falsche Rechnung angeklickt",
          settledAt: "2026-10-08T09:00:00Z",
          settledByDisplayName: "Finn Finanzen",
          settledOn: "2026-10-08",
          withdrawnAt: "2026-10-09T10:00:00Z",
          withdrawnByDisplayName: "Klara Kern",
        },
      ],
    });
    await renderPage({
      items: [reopened],
      documents: [cancellationDocumentFor("i-r")],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    const pane = await openRow("KT26-0004");
    const text = pane.getByTestId("cancellation-refund-withdrawal").textContent;
    expect(text).toContain("Vermerk vom 08.10.2026 (Finn Finanzen)");
    expect(text).toContain("von Klara Kern: Falsche Rechnung angeklickt");
    expect(pane.queryByTestId("open-refund-withdrawal-form")).toBeNull();
  });

  it("lists a failed mail of the cancellation invoice as failed dispatch", () => {
    const failed = { ...failedDelivery("i-x"), kind: "invoice_cancellation" };
    const cancelled = cancelledInvoice("i-x", "KT26-0004", {}, [
      failed as InvoiceDeliveryResponse,
    ]);
    // The invoice's own mail had arrived; what counts now is its cancellation.
    const [row] = invoiceRows([cancelled], [], "2026-10-10");
    expect(row!.dispatch).toBe("failed");
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

  it("shows a partial payment as open remainder and reverses an entry", async () => {
    const partial = settled("i-part", "KT26-0005", [
      entry("p-a", 5_000, "2026-10-04"),
      entry("p-b", 2_000, "2026-10-06", { reversed: true }),
    ]);
    const client = await renderPage({ items: [partial] });
    expect(invoiceListStatus(partial, "2026-11-03")).toBe("partial");
    expect(rowLink("KT26-0005").textContent).toMatch(/94,00\s€ offen/);
    // The "Offen" view groups by status: the partial invoice has its own.
    expect(screen.getAllByText("Teilweise bezahlt").length).toBeGreaterThan(0);
    const pane = await openRow("KT26-0005");
    expect(pane.getByTestId("invoice-paid-amount").textContent).toContain(
      "50,00",
    );
    expect(pane.getByTestId("invoice-open-amount").textContent).toContain(
      "94,00",
    );
    expect(pane.getByText(/Teilweise bezahlt\./)).toBeTruthy();
    const entries = pane.getAllByTestId("payment-entry");
    expect(entries).toHaveLength(2);
    expect(within(entries[1]!).getByText(/Lastschrift zurück/)).toBeTruthy();
    expect(within(entries[1]!).queryByTestId("open-reversal-form")).toBeNull();

    fireEvent.click(pane.getByTestId("open-payment-form"));
    const payDialog = await screen.findByRole("dialog", {
      name: "Zahlung für KT26-0005 erfassen",
    });
    expect(
      (within(payDialog).getByTestId("payment-amount") as HTMLInputElement)
        .value,
    ).toBe("94,00");
    fireEvent.click(
      within(payDialog).getByRole("button", { name: "Abbrechen" }),
    );

    fireEvent.click(within(entries[0]!).getByTestId("open-reversal-form"));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Zahlung für KT26-0005 zurückbuchen?",
    });
    fireEvent.change(within(dialog).getByTestId("reversal-reason"), {
      target: { value: "kurz" },
    });
    fireEvent.click(within(dialog).getByTestId("reverse-payment"));
    expect(within(dialog).getByText(/mindestens 8 Zeichen/)).toBeTruthy();
    expect(client.reverseInvoicePayment).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByTestId("reversal-reason"), {
      target: { value: "Falscher Sponsor zugeordnet" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("reverse-payment"));
    });
    expect(client.reverseInvoicePayment).toHaveBeenCalledWith(
      actionId,
      "i-part",
      "p-a",
      { reason: "Falscher Sponsor zugeordnet", expectedSettlementVersion: 3 },
      expect.objectContaining({
        headers: expect.objectContaining({
          "Idempotency-Key": expect.stringMatching(/^invoice:reversal:/),
        }),
      }),
    );
  });

  it("books a later installment after a lost response under a new key", async () => {
    // First installment: the server books it, but the response is lost.
    const before = settled("i-rate", "KT26-0007", []);
    let client = await renderPage({ items: [before] });
    client.recordInvoicePayment.mockRejectedValueOnce(new TypeError("offline"));
    let pane = await openRow("KT26-0007");
    fireEvent.click(pane.getByTestId("open-payment-form"));
    let dialog = await screen.findByRole("dialog", {
      name: "Zahlung für KT26-0007 erfassen",
    });
    fireEvent.change(within(dialog).getByTestId("payment-amount"), {
      target: { value: "72,00" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("record-payment"));
    });
    const lostKey = (
      client.recordInvoicePayment.mock.calls[0] as unknown as [
        string,
        string,
        unknown,
        { headers: Record<string, string> },
      ]
    )[3].headers["Idempotency-Key"];
    cleanup();

    // After a reload the entry is there; the same amount again is a new
    // installment, not a replay of the lost request.
    const after = settled("i-rate", "KT26-0007", [
      entry("p-rate-1", 7_200, "2026-10-04"),
    ]);
    client = await renderPage({ items: [after] });
    client.recordInvoicePayment.mockResolvedValueOnce({ replayed: false });
    pane = await openRow("KT26-0007");
    fireEvent.click(pane.getByTestId("open-payment-form"));
    dialog = await screen.findByRole("dialog", {
      name: "Zahlung für KT26-0007 erfassen",
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("record-payment"));
    });
    const [, , body, options] = client.recordInvoicePayment.mock
      .calls[0] as unknown as [
      string,
      string,
      { amountMinor: number; expectedSettlementVersion: number },
      { headers: Record<string, string> },
    ];
    expect(body).toMatchObject({
      amountMinor: 7_200,
      expectedSettlementVersion: 1,
    });
    expect(options.headers["Idempotency-Key"]).not.toBe(lostKey);
  });

  it("tells the user when a payment was already booked", async () => {
    const client = await renderPage();
    client.recordInvoicePayment.mockResolvedValueOnce({ replayed: true });
    const pane = await openRow("KT26-0003");
    fireEvent.click(pane.getByTestId("open-payment-form"));
    const dialog = await screen.findByRole("dialog", {
      name: "Zahlung für KT26-0003 erfassen",
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByTestId("record-payment"));
    });
    expect(
      await screen.findByText("Diese Zahlung war bereits erfasst."),
    ).toBeTruthy();
  });

  it("states the real open change when reversing on an overpaid invoice", async () => {
    // 360 € gross here is 144 €: paid 144 + 100 = 244, overpaid 100.
    const overpaid = settled("i-over2", "KT26-0008", [
      entry("p-e", 14_400, "2026-10-04"),
      entry("p-f", 10_000, "2026-10-05"),
    ]);
    await renderPage({
      items: [overpaid],
      url: `/admin/invoices?action=${actionId}&view=paid`,
    });
    const pane = await openRow("KT26-0008");
    const entries = pane.getAllByTestId("payment-entry");
    fireEvent.click(within(entries[1]!).getByTestId("open-reversal-form"));
    let dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(
      "Der offene Betrag bleibt unverändert",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Abbrechen" }));
    fireEvent.click(within(entries[0]!).getByTestId("open-reversal-form"));
    dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toMatch(/steigt um 44,00\s€/);
  });

  it("stamps an overpaid invoice and asks to refund the difference", async () => {
    const overpaid = settled("i-over", "KT26-0006", [
      entry("p-c", 14_400, "2026-10-04"),
      entry("p-d", 14_400, "2026-10-05"),
    ]);
    await renderPage({
      items: [overpaid],
      url: `/admin/invoices?action=${actionId}&view=paid`,
    });
    expect(invoiceListStatus(overpaid, "2026-11-03")).toBe("overpaid");
    const pane = await openRow("KT26-0006");
    expect(pane.getByTestId("invoice-stamp").textContent).toContain(
      "Überzahlt",
    );
    expect(pane.getByTestId("invoice-overpaid").textContent).toContain(
      "Differenz erstatten",
    );
    expect(pane.getByTestId("invoice-overpaid-amount").textContent).toContain(
      "144,00",
    );
    expect(pane.getByTestId("open-payment-form").textContent).toContain(
      "Weitere Zahlung erfassen",
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
    // The shared ReadOnlyNotice: a note, not a live status.
    expect(screen.getByTestId("invoice-read-only").getAttribute("role")).toBe(
      "note",
    );
    const pane = await openRow("KT26-0003");
    expect(pane.queryByTestId("open-payment-form")).toBeNull();
    expect(pane.queryByTestId("open-cancellation-form")).toBeNull();
    expect(pane.queryByTestId("retry-invoice-delivery")).toBeNull();
    expect(pane.getByTestId("preview-document")).toBeTruthy();
  });

  it("gives a finance reader no cancellation invoice commands", async () => {
    const refundOpen = cancelledInvoice("i-r", "KT26-0005", {
      number: null,
      issuedOn: null,
      receivedMinor: 7_200,
      refundOpen: true,
    });
    await renderPage({
      manage: false,
      items: [refundOpen],
      url: `/admin/invoices?action=${actionId}&view=cancelled`,
    });
    const pane = await openRow("KT26-0005");
    expect(pane.getByTestId("invoice-refund-open")).toBeTruthy();
    expect(pane.queryByTestId("open-refund-form")).toBeNull();
    expect(pane.queryByTestId("issue-cancellation-document")).toBeNull();
    expect(pane.getByTestId("cancellation-refund").textContent).toBe(
      "Erstattung offen",
    );
  });
});
