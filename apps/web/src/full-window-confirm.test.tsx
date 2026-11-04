import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type {
  CommitmentResponse,
  DeliveryConfigurationResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { ApiError } from "@leonaid/api-client";
import { CompleteDraft } from "../../../packages/features/src/commitments/complete-draft";
import { DeliveryCompletion } from "../../../packages/features/src/commitments/delivery-completion";
import { fullWindowSelected } from "../../../packages/features/src/commitments/delivery-fields";

const actionId = "20000000-0000-4000-8000-000000000001";

beforeAll(() => {
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

function configuration(fullyBooked: boolean): DeliveryConfigurationResponse {
  return {
    actionId,
    enabled: true,
    revision: 2,
    timezone: "Europe/Berlin",
    windows: [
      {
        deliveryOn: "2099-12-04",
        endsAt: "10:00:00",
        fullyBooked,
        id: "w1",
        retired: false,
        startsAt: "08:00:00",
      },
    ],
  };
}

const order = {
  actionId,
  deliveryContact: null,
  deliveryRecipient: {
    city: "Test",
    countryCode: "DE",
    postalCode: "12345",
    recipientName: "Warehouse",
    streetLine1: "Delivery 2",
  },
  deliveryWindowId: "w1",
  id: "c1",
  invoiceRecipient: null,
} as unknown as CommitmentResponse;

function renderDraft(client: Partial<LeonAidApiClient>) {
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onCompleted = vi.fn();
  render(
    <QueryClientProvider client={queries}>
      <CompleteDraft
        client={client as LeonAidApiClient}
        onCompleted={onCompleted}
        order={order}
      />
    </QueryClientProvider>,
  );
  return onCompleted;
}

function context(full: boolean) {
  return vi.fn(async () => ({
    actionId,
    actionName: "Test",
    deliveryConfiguration: configuration(full),
    offerings: [],
  })) as unknown as LeonAidApiClient["getCommitmentCaptureContext"];
}

describe("booking a window marked ausgebucht", () => {
  it("only a still bookable full window asks", () => {
    expect(fullWindowSelected(configuration(true), "w1")?.id).toBe("w1");
    expect(fullWindowSelected(configuration(false), "w1")).toBeUndefined();
    expect(fullWindowSelected(configuration(true), "")).toBeUndefined();
  });

  it("asks first and then sends the confirmation", async () => {
    const completeCommitment = vi.fn(async () => order);
    const onCompleted = renderDraft({
      completeCommitment,
      getCommitmentCaptureContext: context(true),
    });
    expect(await screen.findByText(/\(ausgebucht\)/)).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Entwurf prüfbereit abschließen" }),
    );
    const dialog = within(await screen.findByRole("alertdialog"));
    expect(completeCommitment).not.toHaveBeenCalled();
    fireEvent.click(dialog.getByRole("button", { name: "Trotzdem eintragen" }));
    await waitFor(() => expect(onCompleted).toHaveBeenCalled());
    expect(completeCommitment).toHaveBeenCalledWith(
      actionId,
      "c1",
      expect.objectContaining({
        allowFullWindow: true,
        deliveryWindowId: "w1",
      }),
      expect.anything(),
    );
  });

  it("asks when the window was switched meanwhile", async () => {
    const completeCommitment = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(409, {
          code: "delivery_window_full",
          message: "Dieses Lieferfenster ist ausgebucht.",
          requestId: "r1",
        }),
      )
      .mockResolvedValueOnce(order);
    const onCompleted = renderDraft({
      completeCommitment,
      getCommitmentCaptureContext: context(false),
    });
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Entwurf prüfbereit abschließen",
      }),
    );
    const dialog = within(await screen.findByRole("alertdialog"));
    expect(completeCommitment).toHaveBeenLastCalledWith(
      actionId,
      "c1",
      expect.objectContaining({ allowFullWindow: false }),
      expect.anything(),
    );
    fireEvent.click(dialog.getByRole("button", { name: "Trotzdem eintragen" }));
    await waitFor(() => expect(onCompleted).toHaveBeenCalled());
    const keys = completeCommitment.mock.calls.map(
      (call) =>
        (call[3] as { headers: Record<string, string> }).headers[
          "Idempotency-Key"
        ],
    );
    // The confirmation reuses the refused attempt's key.
    expect(new Set(keys).size).toBe(1);
  });

  it("asks when a manager completes a draft that carries a full window", async () => {
    const draft = {
      ...order,
      buyer: { displayName: "Buyer", partyKind: "company", twentyId: "t1" },
      deliveryCompletionVersion: "a".repeat(64),
      deliveryWindowSnapshot: {
        windowId: "w1",
        startsAt: "2099-12-04T07:00:00+00:00",
        endsAt: "2099-12-04T09:00:00+00:00",
        timezone: "Europe/Berlin",
      },
      invoiceRecipient: {
        city: "Test",
        countryCode: "DE",
        email: null,
        postalCode: "12345",
        recipientName: "Billing",
        streetLine1: "Invoice 1",
      },
      lines: [],
      status: "draft",
    } as unknown as CommitmentResponse;
    const completeCommitmentDelivery = vi.fn(async () => ({
      ...draft,
      status: "review_ready",
    }));
    const queries = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const onSaved = vi.fn();
    render(
      <QueryClientProvider client={queries}>
        <DeliveryCompletion
          client={
            {
              completeCommitmentDelivery,
              getDeliveryConfiguration: vi.fn(async () => configuration(true)),
            } as unknown as LeonAidApiClient
          }
          onSaved={onSaved}
          order={draft}
        />
      </QueryClientProvider>,
    );
    const save = await screen.findByRole("button", {
      name: "Angaben speichern",
    });
    await waitFor(() =>
      expect((save as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(save);
    const dialog = within(await screen.findByRole("alertdialog"));
    expect(completeCommitmentDelivery).not.toHaveBeenCalled();
    fireEvent.click(dialog.getByRole("button", { name: "Trotzdem eintragen" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(completeCommitmentDelivery).toHaveBeenCalledWith(
      actionId,
      "c1",
      expect.objectContaining({
        allowFullWindow: true,
        deliveryWindowId: "w1",
      }),
      expect.anything(),
    );
  });
});
