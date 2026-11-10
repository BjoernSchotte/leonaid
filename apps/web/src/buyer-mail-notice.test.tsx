import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CommitmentResponse, LeonAidApiClient } from "@leonaid/api-client";
import {
  BuyerMailNotice,
  buyerMailList,
} from "../../../packages/features/src/commitments/buyer-mail-notice";
import { CompleteDraft } from "../../../packages/features/src/commitments/complete-draft";
import { minimizeCaptureContext } from "../../../packages/features/src/offline/read-cache";

afterEach(cleanup);

describe("where the buyer's mails of a recorded order go", () => {
  it("shows the address and what goes there, so the member checks it", () => {
    render(
      <BuyerMailNotice
        deliveryDayMail
        email=" einkauf@sonnenseite.invalid "
        internalOrderMails
      />,
    );
    const notice = screen.getByTestId("buyer-mail-notice");
    expect(notice.textContent).toBe(
      "E-Mails zu dieser Bestellung gehen an einkauf@sonnenseite.invalid " +
        "(Adresse des Sponsors aus dem CRM): die Bestellbestätigung, am " +
        "Liefertag der Hinweis auf das Lieferfenster und eine Stornierung. " +
        "Frag den Käufer, ob die Adresse stimmt. Ist sie falsch, lass sie " +
        "vor dem Speichern im CRM ändern.",
    );
  });

  it("lists only the mails the action sends", () => {
    expect(buyerMailList(true, false)).toBe(
      "die Bestellbestätigung und eine Stornierung",
    );
    expect(buyerMailList(false, true)).toBe(
      "am Liefertag der Hinweis auf das Lieferfenster",
    );
  });

  it("says that a sponsor without an address gets no mail", () => {
    render(<BuyerMailNotice email={null} internalOrderMails />);
    expect(screen.getByTestId("buyer-mail-notice").textContent).toBe(
      "Für diesen Sponsor ist keine E-Mail-Adresse hinterlegt. Der Käufer " +
        "erhält keine E-Mails zu dieser Bestellung.",
    );
  });

  it("stays silent while the action sends no mails for recorded orders", () => {
    render(<BuyerMailNotice email="einkauf@sonnenseite.invalid" />);
    expect(screen.queryByTestId("buyer-mail-notice")).toBeNull();
  });

  it("keeps the switches in the device copy of the capture context", () => {
    const context = {
      actionId: "a1",
      actionName: "Test",
      deliveryConfiguration: null,
      deliveryDayMail: true,
      internalOrderMails: true,
      offerings: [],
    };
    expect(minimizeCaptureContext(context)).toEqual(context);
    // A copy from before the fields existed shows no notice.
    const old = { ...context } as Partial<typeof context>;
    delete old.internalOrderMails;
    delete old.deliveryDayMail;
    expect(minimizeCaptureContext(old as typeof context)).toMatchObject({
      deliveryDayMail: false,
      internalOrderMails: false,
    });
  });

  it("shows the notice before a draft is completed", async () => {
    const order = {
      actionId: "a1",
      buyer: {
        displayName: "Bäckerei Sonnenseite KG",
        email: "einkauf@sonnenseite.invalid",
        partyKind: "company",
        twentyId: "t1",
      },
      deliveryContact: null,
      deliveryRecipient: null,
      deliveryWindowId: null,
      id: "c1",
      invoiceRecipient: null,
    } as unknown as CommitmentResponse;
    const client = {
      getCommitmentCaptureContext: vi.fn(async () => ({
        actionId: "a1",
        actionName: "Test",
        deliveryConfiguration: null,
        deliveryDayMail: false,
        internalOrderMails: true,
        offerings: [],
      })),
    } as unknown as LeonAidApiClient;
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CompleteDraft client={client} onCompleted={vi.fn()} order={order} />
      </QueryClientProvider>,
    );
    expect(
      (await screen.findByTestId("buyer-mail-notice")).textContent,
    ).toContain("gehen an einkauf@sonnenseite.invalid");
  });
});
