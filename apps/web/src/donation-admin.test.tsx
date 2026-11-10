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
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CurrentIdentityResponse,
  type DonationDeliveryResponse,
  type DonationListResponse,
  type DonationResponse,
  type GeneratedDocumentRecordResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  DonationAdminPage,
  InvoiceAdminPage,
  resetCommandPaletteState,
} from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import {
  donationInFlight,
  donationRows,
} from "../../../packages/features/src/donations/donation-model";
import { localIsoDate } from "../../../packages/features/src/invoices/invoice-format";
import { invoiceRows } from "../../../packages/features/src/invoices/invoice-model";
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
  cleanup();
  resetCommandPaletteState();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/admin/donations");
  vi.restoreAllMocks();
});

function donation(
  id: string,
  number: string,
  overrides: Partial<DonationResponse> = {},
): DonationResponse {
  return {
    actionId,
    cancellation: null,
    commitmentId: null,
    createdByDisplayName: "Klara Kern",
    currency: "EUR",
    donor: {
      city: "Musterstadt",
      countryCode: "DE",
      email: "spender@example.org",
      name: "Bäckerei Kern",
      partyKind: null,
      postalCode: "12345",
      streetLine1: "Sonnenstraße 2",
      twentyId: null,
    },
    id,
    note: null,
    number,
    payment: null,
    paymentWithdrawals: [],
    pledgeDeliveries: [],
    pledgeDocument: {
      filename: `Spendenzusage-${number}.pdf`,
      id: `doc-${id}`,
      sizeBytes: 38_000,
      status: "available",
    },
    pledgedAt: "2026-10-01T10:00:00Z",
    pledgedMinor: 5_000,
    replayed: false,
    source: "admin",
    status: "pledged",
    ...overrides,
  };
}

function delivery(
  donationId: string,
  status: DonationDeliveryResponse["status"],
): DonationDeliveryResponse {
  const failed = status === "failed";
  return {
    attempts: 1,
    canRetry: failed,
    donationId,
    generatedDocumentId: `doc-${donationId}`,
    id: `delivery-${donationId}`,
    lastErrorCode: failed ? "mailbox_full" : null,
    lastErrorDetail: failed ? "Postfach voll" : null,
    recipientEmail: "spender@example.org",
    requestedAt: "2026-10-02T10:00:00Z",
    sentAt: status === "sent" ? "2026-10-02T10:01:00Z" : null,
    status,
    subject: "Ihre Spendenzusage",
  };
}

const paid = donation("d-paid", "SP26-0002", {
  donor: { ...donation("x", "x").donor, name: "Café Mitte" },
  payment: {
    amountMinor: 4_000,
    note: "Überweisung",
    receivedOn: "2026-10-05",
    recordedAt: "2026-10-05T12:00:00Z",
    recordedByDisplayName: "Katrin Kolb",
  },
  status: "paid",
});

const cancelled = donation("d-cancelled", "SP26-0003", {
  cancellation: {
    cancelledAt: "2026-10-06T12:00:00Z",
    cancelledByDisplayName: "Klara Kern",
    reason: "Zusage zurückgezogen",
  },
  donor: { ...donation("x", "x").donor, name: "Druckerei Süd" },
  status: "cancelled",
});

const items: DonationResponse[] = [
  donation("d-open", "SP26-0001"),
  paid,
  cancelled,
];

function listResponse(
  overrides: Partial<DonationListResponse> = {},
): DonationListResponse {
  return {
    actionId,
    actionName: "Krapfentaxi 2026",
    currency: "EUR",
    items,
    mayManage: true,
    maySend: true,
    pledgedOpenTotalMinor: 5_000,
    receivedTotalMinor: 4_000,
    receivingBodyName: "Förderverein Lions Club Musterstadt e. V.",
    ...overrides,
  };
}

function identity(
  role: "charity_admin" | "finance_reader",
): CurrentIdentityResponse {
  return {
    actionMemberships: [
      {
        actionId,
        actionName: "Krapfentaxi 2026",
        role,
        roleLabel: role === "charity_admin" ? "Charity-Admin" : "Finanzen",
      },
    ],
    displayName: "Klara Kern",
    globalRoles: [],
    navigation: [],
    roleLabels: [],
  } as unknown as CurrentIdentityResponse;
}

function fakeClient(list: DonationListResponse) {
  return {
    listDonations: vi.fn(async () => list),
    createDonation: vi.fn(async () =>
      donation("d-new", "SP26-0004", { replayed: false }),
    ),
    recordDonationPayment: vi.fn(async () => paid),
    withdrawDonationPayment: vi.fn(async () => donation("d-paid", "SP26-0002")),
    cancelDonation: vi.fn(async () => cancelled),
    sendDonationPledge: vi.fn(async () => delivery("d-open", "queued")),
    retryDonationPledgeDelivery: vi.fn(async () =>
      delivery("d-open", "queued"),
    ),
    downloadGeneratedDocument: vi.fn(async () => new Blob()),
  };
}

function mount(
  client: ReturnType<typeof fakeClient>,
  role: "charity_admin" | "finance_reader" = "charity_admin",
  url = `/admin/donations?action=${actionId}`,
) {
  window.history.replaceState(null, "", url);
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ToastProvider>
        <HotkeyProvider>
          <DonationAdminPage
            client={client as unknown as LeonAidApiClient}
            identity={identity(role)}
          />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

async function renderPage(
  options: {
    list?: Partial<DonationListResponse>;
    role?: "charity_admin" | "finance_reader";
    view?: string;
  } = {},
) {
  const client = fakeClient(listResponse(options.list));
  mount(
    client,
    options.role,
    `/admin/donations?action=${actionId}${options.view ? `&view=${options.view}` : ""}`,
  );
  await screen.findByRole("heading", { level: 1, name: "Spenden" });
  await screen.findByTestId("donation-received-total");
  return client;
}

function rowShown(number: string) {
  return screen
    .queryAllByText(number)
    .some((element) => element.closest(".row-link"));
}

async function openRow(number: string) {
  const primary = screen
    .getAllByText(number)
    .find((element) => element.closest(".row-link"));
  if (!primary) throw new Error(`row ${number} not shown`);
  fireEvent.click(primary.closest("a")!);
  return within(await screen.findByTestId("donation-detail"));
}

type CommandCall = [
  string,
  string,
  Record<string, unknown>,
  { headers: Record<string, string> },
];

describe("donation helpers", () => {
  it("polls while a pledge PDF renders or a pledge mail is on its way", () => {
    expect(donationInFlight(donation("a", "SP26-0001"))).toBe(false);
    expect(
      donationInFlight(
        donation("a", "SP26-0001", {
          pledgeDocument: {
            filename: null,
            id: "doc",
            sizeBytes: null,
            status: "pending",
          },
        }),
      ),
    ).toBe(true);
    expect(
      donationInFlight(
        donation("a", "SP26-0001", {
          pledgeDeliveries: [delivery("a", "sending")],
        }),
      ),
    ).toBe(true);
    expect(
      donationInFlight(
        donation("a", "SP26-0001", {
          pledgeDeliveries: [delivery("a", "failed")],
        }),
      ),
    ).toBe(false);
  });

  it("derives the dispatch state from the newest pledge mail", () => {
    const [row] = donationRows([
      donation("a", "SP26-0001", {
        pledgeDeliveries: [delivery("a", "failed"), delivery("a", "sent")],
      }),
    ]);
    expect(row?.dispatch).toBe("failed");
    expect(donationRows([paid])[0]?.dispatch).toBe("not_sent");
  });
});

describe("DonationAdminPage", () => {
  it("shows the open donations with both sums and the receiving body", async () => {
    await renderPage();
    expect(screen.getByTestId("donation-received-total").textContent).toBe(
      "Eingegangen: 40,00\u00a0€",
    );
    expect(screen.getByTestId("donation-pledged-open-total").textContent).toBe(
      "Zugesagt, noch offen: 50,00\u00a0€",
    );
    expect(screen.getByTestId("donation-receiving-body").textContent).toBe(
      "Empfangende Körperschaft: Förderverein Lions Club Musterstadt e. V.",
    );
    expect(rowShown("SP26-0001")).toBe(true);
    expect(rowShown("SP26-0002")).toBe(false);
    expect(rowShown("SP26-0003")).toBe(false);
    expect(screen.queryByTestId("donation-receiving-body-missing")).toBeNull();
    expect(screen.queryByTestId("donation-read-only")).toBeNull();
  });

  it("lists paid, cancelled and all donations in their views", async () => {
    await renderPage({ view: "all" });
    expect(rowShown("SP26-0001")).toBe(true);
    expect(rowShown("SP26-0002")).toBe(true);
    expect(rowShown("SP26-0003")).toBe(true);
    // A paid row names what arrived; the trailing amount stays the pledge.
    expect(screen.getByText(/40,00 € eingegangen am/)).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "café" },
    });
    await waitFor(() => expect(rowShown("SP26-0001")).toBe(false));
    expect(rowShown("SP26-0002")).toBe(true);
  });

  it("says what is missing without a receiving body and offers no entry", async () => {
    await renderPage({ list: { items: [], receivingBodyName: null } });
    const callout = screen.getByTestId("donation-receiving-body-missing");
    expect(callout.textContent).toContain(
      "In „Organisation & Recht“ fehlt der Teil „Spenden“ mit der empfangenden Körperschaft. Ohne ihn kann keine Spende erfasst werden.",
    );
    expect(within(callout).getByRole("link").getAttribute("href")).toBe(
      "/admin/legal/donations",
    );
    expect(
      screen.queryByRole("button", { name: /Spende erfassen/ }),
    ).toBeNull();
  });

  it("records a donation with the donor, the amount and an idempotency key", async () => {
    const client = await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Spende erfassen/ }));
    const dialog = await screen.findByRole("dialog", {
      name: "Spende erfassen",
    });
    expect(dialog.textContent).toContain(
      "Die Spende erhält sofort eine Nummer und eine Spendenzusage als PDF. Sie geht an Förderverein Lions Club Musterstadt e. V.",
    );
    const form = within(dialog);
    const fill = (testId: string, value: string) =>
      fireEvent.change(form.getByTestId(testId), { target: { value } });

    // Nothing typed: the form names the gaps and sends nothing.
    fireEvent.click(form.getByTestId("create-donation"));
    expect(
      form.getByText("Bitte den Namen des Spenders eingeben."),
    ).toBeTruthy();
    expect(client.createDonation).not.toHaveBeenCalled();

    fill("donation-donor-name", " Autohaus Nord GmbH ");
    fill("donation-donor-street", "Hafenstraße 4");
    fill("donation-donor-postal-code", "12345");
    fill("donation-donor-city", "Musterstadt");
    fill("donation-amount", "0,50");
    fireEvent.click(form.getByTestId("create-donation"));
    expect(
      form.getByText(/Der Betrag liegt zwischen 1,00 € und 1\.000\.000,00 €/),
    ).toBeTruthy();
    expect(client.createDonation).not.toHaveBeenCalled();

    fill("donation-amount", "1.250,00");
    fill("donation-note", "beim Sommerfest zugesagt");
    await act(async () => {
      fireEvent.click(form.getByTestId("create-donation"));
    });
    expect(client.createDonation).toHaveBeenCalledTimes(1);
    const [calledAction, body, options] = client.createDonation.mock
      .calls[0] as unknown as [
      string,
      Record<string, unknown>,
      { headers: Record<string, string> },
    ];
    expect(calledAction).toBe(actionId);
    expect(body).toEqual({
      donor: {
        name: "Autohaus Nord GmbH",
        streetLine1: "Hafenstraße 4",
        postalCode: "12345",
        city: "Musterstadt",
        email: null,
      },
      pledgedMinor: 125_000,
      note: "beim Sommerfest zugesagt",
    });
    expect(options.headers["Idempotency-Key"]).toMatch(/^donation:create:/);
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Spende erfassen" }),
      ).toBeNull(),
    );
    expect(client.listDonations.mock.calls.length).toBeGreaterThan(1);
  });

  it("refuses a malformed donor e-mail and sends a valid one", async () => {
    const client = await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Spende erfassen/ }));
    const form = within(
      await screen.findByRole("dialog", { name: "Spende erfassen" }),
    );
    const fill = (testId: string, value: string) =>
      fireEvent.change(form.getByTestId(testId), { target: { value } });
    fill("donation-donor-name", "Erika Muster");
    fill("donation-donor-street", "Marktplatz 1");
    fill("donation-donor-postal-code", "12345");
    fill("donation-donor-city", "Musterstadt");
    fill("donation-amount", "50");
    fill("donation-donor-email", "erika@");
    fireEvent.click(form.getByTestId("create-donation"));
    expect(
      form.getByText("Bitte eine gültige E-Mail-Adresse eingeben."),
    ).toBeTruthy();
    fill("donation-donor-email", "erika@example.org");
    await act(async () => {
      fireEvent.click(form.getByTestId("create-donation"));
    });
    const [, body] = client.createDonation.mock.calls[0] as unknown as [
      string,
      Record<string, unknown>,
    ];
    expect(body).toMatchObject({
      donor: { email: "erika@example.org" },
      pledgedMinor: 5_000,
      note: null,
    });
  });

  it("prefills the pledged amount and lets the payment differ from it", async () => {
    const client = await renderPage();
    const pane = await openRow("SP26-0001");
    fireEvent.click(pane.getByTestId("open-donation-payment-form"));
    const dialog = within(
      await screen.findByRole("dialog", {
        name: "Zahlung für SP26-0001 erfassen",
      }),
    );
    const amount = dialog.getByTestId(
      "donation-payment-amount",
    ) as HTMLInputElement;
    const date = dialog.getByTestId(
      "donation-payment-date",
    ) as HTMLInputElement;
    expect(amount.value).toBe("50,00");
    expect(date.value).toBe(localIsoDate());
    expect(date.min).toBe("2026-10-01");
    expect(date.max).toBe(localIsoDate());
    expect(
      dialog.getByText(
        "Entspricht der Zusage. Der Betrag darf von der Zusage abweichen. Eine zweite Teilzahlung erfassen Sie als eigene Spende.",
      ),
    ).toBeTruthy();

    fireEvent.change(amount, { target: { value: "40,00" } });
    expect(dialog.getByText(/^10,00 € weniger als zugesagt\./)).toBeTruthy();
    fireEvent.change(amount, { target: { value: "75" } });
    expect(dialog.getByText(/^25,00 € mehr als zugesagt\./)).toBeTruthy();

    fireEvent.change(dialog.getByTestId("donation-payment-note"), {
      target: { value: " bar übergeben " },
    });
    await act(async () => {
      fireEvent.click(dialog.getByTestId("record-donation-payment"));
    });
    expect(client.recordDonationPayment).toHaveBeenCalledTimes(1);
    const [calledAction, calledDonation, body, options] = client
      .recordDonationPayment.mock.calls[0] as unknown as CommandCall;
    expect(calledAction).toBe(actionId);
    expect(calledDonation).toBe("d-open");
    expect(body).toEqual({
      amountMinor: 7_500,
      receivedOn: localIsoDate(),
      note: "bar übergeben",
    });
    expect(options.headers["Idempotency-Key"]).toMatch(/^donation:payment:/);
  });

  it("keeps the payment day between the pledge and today", async () => {
    const client = await renderPage();
    const pane = await openRow("SP26-0001");
    fireEvent.click(pane.getByTestId("open-donation-payment-form"));
    const dialog = within(
      await screen.findByRole("dialog", {
        name: "Zahlung für SP26-0001 erfassen",
      }),
    );
    const date = dialog.getByTestId("donation-payment-date");
    for (const day of ["2026-09-30", "2099-01-01", ""]) {
      fireEvent.change(date, { target: { value: day } });
      fireEvent.click(dialog.getByTestId("record-donation-payment"));
      expect(
        dialog.getByText(
          /Das Eingangsdatum liegt zwischen dem Tag der Zusage \(01\.10\.2026\) und heute\./,
        ),
      ).toBeTruthy();
    }
    fireEvent.change(dialog.getByTestId("donation-payment-amount"), {
      target: { value: "0" },
    });
    fireEvent.click(dialog.getByTestId("record-donation-payment"));
    expect(
      dialog.getByText("Der eingegangene Betrag muss größer als 0,00 € sein."),
    ).toBeTruthy();
    expect(client.recordDonationPayment).not.toHaveBeenCalled();

    // The server's own date refusal lands at the date field, in German.
    client.recordDonationPayment.mockRejectedValueOnce(
      new ApiError(409, {
        code: "donation_payment_before_pledge",
        message: "payment before pledge",
        requestId: "req-1",
      }),
    );
    fireEvent.change(dialog.getByTestId("donation-payment-amount"), {
      target: { value: "50,00" },
    });
    fireEvent.change(date, { target: { value: "2026-10-01" } });
    await act(async () => {
      fireEvent.click(dialog.getByTestId("record-donation-payment"));
    });
    expect(
      await dialog.findByText(
        "Das Eingangsdatum darf nicht vor dem Tag der Zusage liegen.",
      ),
    ).toBeTruthy();
  });

  it("takes a recorded payment back with a reason", async () => {
    const client = await renderPage({ view: "paid" });
    const pane = await openRow("SP26-0002");
    expect(pane.getByTestId("donation-stamp").textContent).toContain("Bezahlt");
    expect(pane.getByTestId("donation-payment").textContent).toContain(
      "40,00\u00a0€ (10,00\u00a0€ weniger als zugesagt)",
    );
    fireEvent.click(pane.getByTestId("open-donation-withdrawal-form"));
    const dialog = within(
      await screen.findByRole("alertdialog", {
        name: "Zahlung für SP26-0002 zurücknehmen?",
      }),
    );
    fireEvent.change(dialog.getByTestId("donation-withdrawal-reason"), {
      target: { value: "kurz" },
    });
    fireEvent.click(dialog.getByTestId("withdraw-donation-payment"));
    expect(
      dialog.getByText("Bitte einen Grund mit mindestens 8 Zeichen angeben."),
    ).toBeTruthy();
    expect(client.withdrawDonationPayment).not.toHaveBeenCalled();
    fireEvent.change(dialog.getByTestId("donation-withdrawal-reason"), {
      target: { value: " Falscher Spende zugeordnet " },
    });
    await act(async () => {
      fireEvent.click(dialog.getByTestId("withdraw-donation-payment"));
    });
    const [calledAction, calledDonation, body, options] = client
      .withdrawDonationPayment.mock.calls[0] as unknown as CommandCall;
    expect([calledAction, calledDonation]).toEqual([actionId, "d-paid"]);
    expect(body).toEqual({ reason: "Falscher Spende zugeordnet" });
    expect(options.headers["Idempotency-Key"]).toMatch(
      /^donation:payment-withdrawal:/,
    );
  });

  it("cancels an unpaid donation with a reason", async () => {
    const client = await renderPage();
    const pane = await openRow("SP26-0001");
    fireEvent.click(pane.getByTestId("open-donation-cancellation-form"));
    const dialog = within(
      await screen.findByRole("alertdialog", {
        name: "Spende SP26-0001 stornieren?",
      }),
    );
    fireEvent.change(dialog.getByTestId("donation-cancellation-reason"), {
      target: { value: "Spender hat die Zusage zurückgezogen" },
    });
    await act(async () => {
      fireEvent.click(dialog.getByTestId("cancel-donation"));
    });
    const [calledAction, calledDonation, body, options] = client.cancelDonation
      .mock.calls[0] as unknown as CommandCall;
    expect([calledAction, calledDonation]).toEqual([actionId, "d-open"]);
    expect(body).toEqual({ reason: "Spender hat die Zusage zurückgezogen" });
    expect(options.headers["Idempotency-Key"]).toMatch(
      /^donation:cancellation:/,
    );
  });

  it("offers no cancellation for a paid donation and says why", async () => {
    await renderPage({ view: "paid" });
    const pane = await openRow("SP26-0002");
    expect(pane.queryByTestId("open-donation-cancellation-form")).toBeNull();
    expect(pane.queryByTestId("open-donation-payment-form")).toBeNull();
    expect(pane.getByTestId("donation-paid-no-cancel").textContent).toContain(
      "Eine bezahlte Spende kann nicht storniert werden.",
    );
  });

  it("shows a cancelled donation without commands", async () => {
    await renderPage({ view: "cancelled" });
    const pane = await openRow("SP26-0003");
    expect(pane.getByTestId("donation-stamp").textContent).toContain(
      "Storniert",
    );
    expect(pane.getByTestId("donation-cancellation").textContent).toContain(
      "Zusage zurückgezogen",
    );
    expect(pane.queryByTestId("open-donation-payment-form")).toBeNull();
    expect(pane.queryByTestId("open-donation-cancellation-form")).toBeNull();
    expect(pane.queryByTestId("send-donation-pledge")).toBeNull();
  });

  it("shows who recorded and who withdrew earlier payments", async () => {
    await renderPage({
      list: {
        items: [
          donation("d-open", "SP26-0001", {
            paymentWithdrawals: [
              {
                amountMinor: 5_000,
                id: "w1",
                note: null,
                reason: "Falscher Spende zugeordnet",
                receivedOn: "2026-10-03",
                recordedAt: "2026-10-03T09:00:00Z",
                recordedByDisplayName: "Katrin Kolb",
                withdrawnAt: "2026-10-04T09:00:00Z",
                withdrawnByDisplayName: "Klara Kern",
              },
            ],
          }),
        ],
      },
    });
    const pane = await openRow("SP26-0001");
    const entry = pane.getByTestId("donation-payment-withdrawal").textContent;
    expect(entry).toContain("50,00\u00a0€");
    expect(entry).toContain("Katrin Kolb");
    expect(entry).toContain("Klara Kern");
    expect(entry).toContain("Falscher Spende zugeordnet");
    expect(pane.getByTestId("donation-payment").textContent).toContain(
      "Noch keine Zahlung erfasst.",
    );
  });

  it("sends the pledge once the PDF is there", async () => {
    const client = await renderPage();
    const pane = await openRow("SP26-0001");
    expect(
      pane.getByTestId("preview-donation-pledge").getAttribute("href"),
    ).toBe(
      `/api/v1/actions/${actionId}/documents/doc-d-open/download?inline=true`,
    );
    await act(async () => {
      fireEvent.click(pane.getByTestId("send-donation-pledge"));
    });
    const [calledAction, calledDonation, options] = client.sendDonationPledge
      .mock.calls[0] as unknown as [
      string,
      string,
      { headers: Record<string, string> },
    ];
    expect([calledAction, calledDonation]).toEqual([actionId, "d-open"]);
    expect(options.headers["Idempotency-Key"]).toMatch(
      /^donation:pledge-delivery:/,
    );
  });

  it("asks before a second pledge mail and retries a failed one", async () => {
    const client = await renderPage({
      list: {
        items: [
          donation("d-sent", "SP26-0005", {
            pledgeDeliveries: [delivery("d-sent", "sent")],
          }),
          donation("d-failed", "SP26-0006", {
            pledgeDeliveries: [delivery("d-failed", "failed")],
          }),
        ],
      },
    });
    let pane = await openRow("SP26-0005");
    expect(pane.queryByTestId("send-donation-pledge")).toBeNull();
    fireEvent.click(pane.getByTestId("resend-donation-pledge"));
    await act(async () => {
      fireEvent.click(pane.getByTestId("confirm-resend-donation-pledge"));
    });
    expect(client.sendDonationPledge).toHaveBeenCalledTimes(1);

    pane = await openRow("SP26-0006");
    expect(
      pane.getByTestId("donation-pledge-delivery-failed").textContent,
    ).toContain("Postfach voll");
    await act(async () => {
      fireEvent.click(pane.getByTestId("retry-donation-pledge-delivery"));
    });
    expect(
      client.retryDonationPledgeDelivery.mock.calls[0]?.slice(0, 3),
    ).toEqual([actionId, "d-failed", "delivery-d-failed"]);
  });

  it("offers no send button without a donor e-mail or while the PDF renders", async () => {
    await renderPage({
      list: {
        items: [
          donation("d-nomail", "SP26-0007", {
            donor: { ...donation("x", "x").donor, email: null },
          }),
          donation("d-pending", "SP26-0008", {
            pledgeDocument: {
              filename: null,
              id: "doc-p",
              sizeBytes: null,
              status: "pending",
            },
          }),
        ],
      },
    });
    let pane = await openRow("SP26-0007");
    expect(pane.queryByTestId("send-donation-pledge")).toBeNull();
    expect(
      pane.getByTestId("donation-donor-email-missing").textContent,
    ).toContain("Für den Versand fehlt die E-Mail-Adresse des Spenders.");

    pane = await openRow("SP26-0008");
    expect(pane.queryByTestId("send-donation-pledge")).toBeNull();
    expect(
      pane.getByTestId("donation-pledge-document").getAttribute("data-state"),
    ).toBe("pending");
    expect(pane.getByTestId("donation-pledge-document").textContent).toContain(
      "wird erzeugt",
    );
  });

  it("asks the server again while a pledge PDF is pending", async () => {
    const client = await renderPage({
      list: {
        items: [
          donation("d-pending", "SP26-0008", {
            pledgeDocument: {
              filename: null,
              id: "doc-p",
              sizeBytes: null,
              status: "pending",
            },
          }),
        ],
      },
    });
    await waitFor(
      () => expect(client.listDonations.mock.calls.length).toBeGreaterThan(1),
      { timeout: 3000 },
    );
  });

  it("links a donation that came with an order and names its source", async () => {
    await renderPage({
      list: {
        items: [
          donation("d-form", "SP26-0009", {
            commitmentId: "c-1",
            createdByDisplayName: null,
            source: "public_form",
          }),
        ],
      },
    });
    const pane = await openRow("SP26-0009");
    expect(pane.getByTestId("donation-source").textContent).toBe(
      "Öffentliches Formular",
    );
    expect(pane.getByTestId("donation-order-link").getAttribute("href")).toBe(
      `/admin/orders?action=${actionId}&open=c-1`,
    );
  });

  it("gives a finance reader everything to read and no command", async () => {
    await renderPage({
      list: {
        items: [
          donation("d-failed", "SP26-0006", {
            pledgeDeliveries: [delivery("d-failed", "failed")],
          }),
          paid,
        ],
        mayManage: false,
        maySend: false,
      },
      role: "finance_reader",
      view: "all",
    });
    expect(screen.getByTestId("donation-read-only").getAttribute("role")).toBe(
      "note",
    );
    expect(
      screen.queryByRole("button", { name: /Spende erfassen/ }),
    ).toBeNull();
    let pane = await openRow("SP26-0006");
    expect(pane.queryByTestId("open-donation-payment-form")).toBeNull();
    expect(pane.queryByTestId("open-donation-cancellation-form")).toBeNull();
    expect(pane.queryByTestId("retry-donation-pledge-delivery")).toBeNull();
    expect(pane.queryByTestId("send-donation-pledge")).toBeNull();
    expect(pane.getByTestId("preview-donation-pledge")).toBeTruthy();
    expect(pane.getByTestId("donation-pledge-delivery-attempt")).toBeTruthy();
    pane = await openRow("SP26-0002");
    expect(pane.queryByTestId("open-donation-withdrawal-form")).toBeNull();
    expect(pane.getByTestId("donation-payment").textContent).toContain(
      "Katrin Kolb",
    );
  });

  it("shows an empty state when the action takes no donations", async () => {
    const client = fakeClient(listResponse());
    client.listDonations.mockRejectedValue(
      new ApiError(409, {
        code: "donation_capability_disabled",
        message: "donations are disabled",
        requestId: "req-2",
      }),
    );
    mount(client);
    const page = await screen.findByTestId("donation-capability-disabled");
    expect(
      within(page).getByRole("heading", {
        name: "Für diese Aktion sind Spenden nicht aktiviert.",
      }),
    ).toBeTruthy();
    expect(within(page).getByRole("link", { name: "Zur Aktion" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(client.listDonations).toHaveBeenCalledTimes(1);
  });
});

describe("documents ledger with donation pledges", () => {
  const pledge: GeneratedDocumentRecordResponse = {
    buyerDisplayName: "Bäckerei Kern",
    documentNumber: "SP26-0001",
    invoiceNumber: null,
    document: {
      actionId,
      availableAt: "2026-10-01T10:01:00Z",
      commitmentId: null,
      createdAt: "2026-10-01T10:00:30Z",
      documentType: "donation_pledge_pdf",
      donationId: "d-open",
      filename: "Spendenzusage-SP26-0001.pdf",
      id: "doc-d-open",
      invoiceId: null,
      mediaType: "application/pdf",
      renderVersion: "1",
      sentAt: null,
      sizeBytes: 38_000,
      status: "available",
      twentyCompanyId: null,
      twentyPersonId: null,
      version: 1,
    },
  };

  it("keeps pledge documents out of the invoice rows", () => {
    expect(invoiceRows([], [pledge])).toEqual([]);
  });

  it("labels a pledge with its donation number and donor", async () => {
    window.history.replaceState(
      null,
      "",
      `/admin/invoices/documents?action=${actionId}`,
    );
    const client = {
      getInvoiceContext: vi.fn(async () => ({
        actionId,
        actionName: "Krapfentaxi 2026",
        endsOn: "2026-12-24",
        mayIssue: true,
        mayManageSettlements: true,
        profile: null,
        startsOn: "2026-10-01",
      })),
      listInvoices: vi.fn(async () => ({
        actionId,
        currencyTotals: [],
        items: [],
      })),
      listActionDocuments: vi.fn(async () => ({
        actionId,
        items: [pledge],
        reference: {},
      })),
    };
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ToastProvider>
          <HotkeyProvider>
            <InvoiceAdminPage
              client={client as unknown as LeonAidApiClient}
              identity={identity("charity_admin")}
            />
          </HotkeyProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
    const row = within(await screen.findByTestId("document-row"));
    const link = row.getByRole("link", {
      name: "Spendenzusage SP26-0001 · Bäckerei Kern",
    });
    expect(link.getAttribute("href")).toBe(
      `/admin/donations?action=${actionId}&open=d-open`,
    );
    expect(row.getAllByRole("cell")[1]?.textContent).toBe("Spendenzusage");
  });
});
