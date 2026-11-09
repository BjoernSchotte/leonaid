import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CommitmentResponse, LeonAidApiClient } from "@leonaid/api-client";
import { DeliveryCompletion } from "../../../packages/features/src/commitments/delivery-completion";

const actionId = "20000000-0000-4000-8000-000000000001";

describe("driver note on the manager completion form", () => {
  it("completion form round-trips the note", async () => {
    const draft = {
      actionId,
      buyer: { displayName: "Buyer", partyKind: "company", twentyId: "t1" },
      deliveryCompletionVersion: "a".repeat(64),
      deliveryContact: {
        name: null,
        phone: null,
        driverNote: "Klingel defekt",
      },
      deliveryRecipient: {
        city: "Test",
        countryCode: "DE",
        postalCode: "12345",
        recipientName: "Warehouse",
        streetLine1: "Delivery 2",
      },
      deliveryWindowId: "w1",
      deliveryWindowSnapshot: {
        windowId: "w1",
        startsAt: "2099-12-04T07:00:00+00:00",
        endsAt: "2099-12-04T09:00:00+00:00",
        timezone: "Europe/Berlin",
      },
      id: "c1",
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
    const onSaved = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <DeliveryCompletion
          client={
            {
              completeCommitmentDelivery,
              getDeliveryConfiguration: vi.fn(async () => ({
                actionId,
                enabled: true,
                revision: 1,
                startPoint: null,
                timezone: "Europe/Berlin",
                windows: [
                  {
                    deliveryOn: "2099-12-04",
                    endsAt: "10:00:00",
                    fullyBooked: false,
                    id: "w1",
                    retired: false,
                    startsAt: "08:00:00",
                  },
                ],
              })),
            } as unknown as LeonAidApiClient
          }
          onSaved={onSaved}
          order={draft}
        />
      </QueryClientProvider>,
    );
    const field = (await screen.findByLabelText(
      /Hinweis für den Fahrer/,
    )) as HTMLInputElement;
    expect(field.value).toBe("Klingel defekt");
    fireEvent.change(field, { target: { value: " Hintereingang " } });
    fireEvent.click(screen.getByRole("button", { name: "Angaben speichern" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(completeCommitmentDelivery).toHaveBeenCalledWith(
      actionId,
      "c1",
      expect.objectContaining({
        deliveryContact: {
          driverNote: "Hintereingang",
          name: null,
          phone: null,
        },
      }),
      expect.anything(),
    );
  });
});
