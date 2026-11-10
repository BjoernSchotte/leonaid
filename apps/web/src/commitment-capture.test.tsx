/*
 * The extra donation in the order capture of the acquisition app
 * (specs/mails-documents-donations-push §8.6): offered only when the
 * action names a receiving body, sent in `donationAmountMinor`, kept in the
 * request the offline queue stores.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CommitmentCaptureContextResponse,
  type CreateCommitmentRequest,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";

import { CommitmentCapturePage } from "../../../packages/features/src/commitments/commitment-capture";
import {
  parseDonationInput,
  donationRequestPart,
} from "../../../packages/features/src/commitments/order-donation";
import type { QueueController } from "../../../packages/features/src/offline/controller";
import {
  OfflineRuntimeContext,
  type OfflineRuntime,
} from "../../../packages/features/src/offline/runtime";

const actionId = "20000000-0000-4000-8000-000000000001";
const RECEIVING_BODY = "Lions Hilfswerk Beispielstadt e. V.";

const identity = {
  userId: "00000000-0000-4000-8000-0000000000aa",
  displayName: "Anna Akquise",
  globalRoles: [],
  actionMemberships: [
    { actionId, actionName: "Krapfentaxi 2026", role: "acquirer" },
  ],
  navigation: [],
} as unknown as CurrentIdentityResponse;

function context(
  donationReceivingBody: string | null,
): CommitmentCaptureContextResponse {
  return {
    actionId,
    actionName: "Krapfentaxi 2026",
    deliveryConfiguration: null,
    deliveryDayMail: false,
    donationReceivingBody,
    internalOrderMails: false,
    offerings: [
      {
        allowedQuantityUnits: ["box"],
        availableFrom: null,
        availableUntil: null,
        code: "BOX-12",
        currency: "EUR",
        id: "o1",
        name: "Krapfenbox",
        piecesPerUnit: 12,
        status: "active",
        unit: "box",
        unitPriceMinor: 2400,
      },
    ] as unknown as CommitmentCaptureContextResponse["offerings"],
  };
}

function fakeClient(donationReceivingBody: string | null) {
  const createCommitment = vi.fn(
    async (_action: string, body: CreateCommitmentRequest) => ({
      actionId,
      buyer: body.buyer,
      currency: "EUR",
      deliveryCompletionVersion: "v1",
      id: "c1",
      invoiceRecipient: body.invoiceRecipient ?? null,
      lines: [],
      publicReference: "LA-1",
      quantities: [{ quantity: 1, unit: "box" }],
      replayed: false,
      source: "acquisition",
      status: body.readyForReview ? "review_ready" : "draft",
      totalBoxes: 1,
      totalMinor: 2400,
      totalPieces: 12,
    }),
  );
  const client = {
    createCommitment,
    getAcquisitionActivityBoard: vi.fn(async () => ({
      actionId,
      activities: [],
      generatedAt: "2026-11-07T12:00:00Z",
      workItems: [
        {
          assignedAcquirers: [],
          assignmentId: "as1",
          city: "Augsburg",
          contactName: null,
          dueAt: null,
          email: "einkauf@kern.invalid",
          nextAction: null,
          partyDisplayName: "Bäckerei Kern",
          partyId: "party",
          partyKind: "company",
          phone: null,
          postalCode: "86150",
          priority: 0,
          revision: 1,
          status: "contacted",
          suppressedChannels: [],
          urgency: "none",
        },
      ],
    })),
    getCommitmentCaptureContext: vi.fn(async () =>
      context(donationReceivingBody),
    ),
  };
  return { client: client as unknown as LeonAidApiClient, createCommitment };
}

function renderCapture(client: LeonAidApiClient, runtime?: OfflineRuntime) {
  window.history.replaceState(
    null,
    "",
    `/app/commitments/new?action=${actionId}&assignment=as1`,
  );
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const page = <CommitmentCapturePage client={client} identity={identity} />;
  render(
    <QueryClientProvider client={queries}>
      {runtime ? (
        <OfflineRuntimeContext.Provider value={runtime}>
          {page}
        </OfflineRuntimeContext.Provider>
      ) : (
        page
      )}
    </QueryClientProvider>,
  );
}

const donationField = () =>
  screen.getByTestId("capture-donation-amount") as HTMLInputElement;

/** Step 1 → 2 → 3 with a complete invoice recipient. */
async function toReview() {
  fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
  fireEvent.change(await screen.findByTestId("commitment-street"), {
    target: { value: "Löwenweg 12" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
  return screen.findByTestId("commitment-save-ready");
}

beforeEach(() => {
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
});

describe("the donation amount as typed", () => {
  it("reads euro amounts between 1,00 and 10.000,00 and nothing else", () => {
    expect(parseDonationInput("")).toEqual({ kind: "empty" });
    expect(parseDonationInput("  ")).toEqual({ kind: "empty" });
    expect(parseDonationInput("25")).toEqual({ kind: "amount", minor: 2500 });
    expect(parseDonationInput("25,5")).toEqual({ kind: "amount", minor: 2550 });
    expect(parseDonationInput("25.50 €")).toEqual({
      kind: "amount",
      minor: 2550,
    });
    expect(parseDonationInput("10.000,00")).toEqual({
      kind: "amount",
      minor: 1_000_000,
    });
    for (const text of ["0,99", "10.000,01", "-5", "abc", "5,555"]) {
      expect(parseDonationInput(text)).toEqual({ kind: "invalid" });
    }
    expect(donationRequestPart({ kind: "amount", minor: 2550 })).toEqual({
      donationAmountMinor: 2550,
    });
    expect(donationRequestPart({ kind: "empty" })).toEqual({});
    expect(donationRequestPart({ kind: "invalid" })).toEqual({});
  });
});

describe("order capture: extra donation", () => {
  it("offers the field with the receiving body and sends the amount", async () => {
    const { client, createCommitment } = fakeClient(RECEIVING_BODY);
    renderCapture(client);
    const field = await screen.findByTestId("capture-donation-amount");
    const label = document.querySelector(`label[for="${field.id}"]`)!;
    expect(label.textContent).toBe("Zusatzspende in € (optional)");
    const hint = document.getElementById(`${field.id}-hint`)!;
    expect(hint.textContent).toBe(
      `Freiwillig und zusätzlich zur Bestellung. Empfänger ist ${RECEIVING_BODY}. Spender ist der Rechnungsempfänger. Er erhält eine eigene Spendenzusage; die Spende steht nicht auf der Rechnung.`,
    );
    fireEvent.change(field, { target: { value: "25,50" } });
    // The order's sum stays the order's; the donation has its own line.
    expect(screen.getByTestId("commitment-preview-total").textContent).toBe(
      "Summe 24,00\u00a0€",
    );
    expect(screen.getByTestId("capture-donation-line").textContent).toBe(
      "Spende: 25,50\u00a0€ (nicht in der Summe)",
    );
    fireEvent.click(await toReview());
    expect(screen.getByTestId("capture-donation-review").textContent).toContain(
      `25,50\u00a0€ an ${RECEIVING_BODY}, eigene Spendenzusage, nicht Teil der Rechnung`,
    );
    await screen.findByTestId("commitment-success");
    expect(createCommitment).toHaveBeenCalledTimes(1);
    expect(createCommitment.mock.calls[0]![1]).toMatchObject({
      donationAmountMinor: 2550,
      invoiceRecipient: {
        city: "Augsburg",
        postalCode: "86150",
        recipientName: "Bäckerei Kern",
        streetLine1: "Löwenweg 12",
      },
      lines: [{ offeringId: "o1", quantity: 1, quotedUnitPriceMinor: 2400 }],
      readyForReview: true,
      source: "acquisition",
    });
    expect(screen.getByTestId("capture-donation-note").textContent).toBe(
      "Zusatzspende: 25,50\u00a0€. Sie erhält eine eigene Spendenzusage und steht nicht auf der Rechnung.",
    );
  });

  it("sends no donation when the field stays empty", async () => {
    const { client, createCommitment } = fakeClient(RECEIVING_BODY);
    renderCapture(client);
    await screen.findByTestId("capture-donation-amount");
    fireEvent.click(await toReview());
    await screen.findByTestId("commitment-success");
    expect(
      "donationAmountMinor" in
        (createCommitment.mock.calls[0]![1] as unknown as object),
    ).toBe(false);
    expect(screen.queryByTestId("capture-donation-note")).toBeNull();
  });

  it("shows no field where the action offers no donation", async () => {
    const { client, createCommitment } = fakeClient(null);
    renderCapture(client);
    await screen.findByTestId("commitment-preview-total");
    expect(screen.queryByTestId("capture-donation-amount")).toBeNull();
    fireEvent.click(await toReview());
    expect(screen.queryByTestId("capture-donation-review")).toBeNull();
    await screen.findByTestId("commitment-success");
    expect(
      "donationAmountMinor" in
        (createCommitment.mock.calls[0]![1] as unknown as object),
    ).toBe(false);
  });

  it("keeps an amount out of range on the first step", async () => {
    const { client } = fakeClient(RECEIVING_BODY);
    renderCapture(client);
    fireEvent.change(await screen.findByTestId("capture-donation-amount"), {
      target: { value: "0,50" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
    expect(
      await screen.findByText(
        "Bitte gib einen Betrag zwischen 1,00 € und 10.000,00 € ein oder lass das Feld leer.",
      ),
    ).toBeTruthy();
    expect(donationField().getAttribute("aria-invalid")).toBe("true");
    expect(screen.queryByTestId("commitment-street")).toBeNull();
    expect(screen.queryByTestId("capture-donation-line")).toBeNull();
    // Corrected: the way on is free.
    fireEvent.change(donationField(), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
    await screen.findByTestId("commitment-street");
  });

  it("shows the server's refusal at the invoice recipient: the recipient is the donor", async () => {
    const { client, createCommitment } = fakeClient(RECEIVING_BODY);
    createCommitment.mockRejectedValueOnce(
      new ApiError(422, {
        code: "commitment_donation_recipient_required",
        details: null,
        message:
          "Eine Bestellung mit Spende braucht einen vollständigen Rechnungsempfänger.",
        requestId: "r1",
      }),
    );
    renderCapture(client);
    fireEvent.change(await screen.findByTestId("capture-donation-amount"), {
      target: { value: "10" },
    });
    fireEvent.click(await toReview());
    // Back on the step with the invoice fields, with the server's words.
    await screen.findByTestId("commitment-street");
    expect(document.getElementById("commitment-step-error")!.textContent).toBe(
      "Eine Bestellung mit Spende braucht einen vollständigen Rechnungsempfänger.",
    );
    expect(screen.queryByTestId("commitment-save-ready")).toBeNull();
    // The amount stays; the next save sends it again.
    fireEvent.click(screen.getByRole("button", { name: "Weiter" }));
    fireEvent.click(await screen.findByTestId("commitment-save-ready"));
    await screen.findByTestId("commitment-success");
    expect(createCommitment.mock.calls[1]![1]).toMatchObject({
      donationAmountMinor: 1000,
    });
  });

  it("puts the donation into the request the offline queue stores", async () => {
    const { client, createCommitment } = fakeClient(RECEIVING_BODY);
    const submit = vi.fn(async () => ({
      entryId: "e1",
      error: null,
      reason: "offline" as const,
      state: "queued" as const,
    }));
    renderCapture(client, {
      enabled: true,
      queue: { submit } as unknown as QueueController,
      store: null,
    });
    fireEvent.change(await screen.findByTestId("capture-donation-amount"), {
      target: { value: "1.000" },
    });
    fireEvent.click(await toReview());
    await screen.findByTestId("commitment-queued");
    expect(createCommitment).not.toHaveBeenCalled();
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit.mock.calls[0]).toMatchObject([
      {
        actionId,
        assignmentId: "as1",
        kind: "commitment",
        request: { donationAmountMinor: 100_000, readyForReview: true },
      },
    ]);
    expect(screen.getByTestId("capture-donation-note").textContent).toContain(
      "Zusatzspende: 1.000,00\u00a0€.",
    );
  });
});
