import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CommitmentResponse, LeonAidApiClient } from "@leonaid/api-client";
import {
  BuyerMailNotice,
  buyerMailList,
} from "../../../packages/features/src/commitments/buyer-mail-notice";
import { CompleteDraft } from "../../../packages/features/src/commitments/complete-draft";
import { DeliveryCompletion } from "../../../packages/features/src/commitments/delivery-completion";
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
      donationReceivingBody: null,
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
  it("says that no confirmation goes out any more, and why", () => {
    render(
      <BuyerMailNotice
        address="Sie"
        confirmationNotDue="action_closed"
        deliveryDayMail
        email="einkauf@sonnenseite.invalid"
        internalOrderMails
      />,
    );
    expect(screen.getByTestId("buyer-mail-notice").textContent).toBe(
      "Für diese Bestellung geht keine Bestellbestätigung mehr hinaus: " +
        "Die Aktion ist abgeschlossen. Eine Stornierung ginge an " +
        "einkauf@sonnenseite.invalid (Adresse des Sponsors aus dem CRM).",
    );
    cleanup();
    // Only the delivery-day mail is switched on: it is over as well.
    render(
      <BuyerMailNotice
        confirmationNotDue="window_over"
        deliveryDayMail
        email="einkauf@sonnenseite.invalid"
      />,
    );
    expect(screen.queryByTestId("buyer-mail-notice")).toBeNull();
  });
});

describe("the notice in the web form Angaben ergänzen", () => {
  const draft = {
    actionId: "a1",
    buyer: {
      displayName: "Bäckerei Sonnenseite KG",
      email: "einkauf@sonnenseite.invalid",
      partyKind: "company",
      twentyId: "t1",
    },
    deliveryCompletionVersion: 1,
    deliveryContact: null,
    deliveryRecipient: {
      city: "Test",
      countryCode: "DE",
      postalCode: "12345",
      recipientName: "Lager",
      streetLine1: "Lieferweg 2",
    },
    deliveryWindowId: null,
    deliveryWindowSnapshot: null,
    id: "c1",
    invoiceRecipient: {
      city: "Test",
      countryCode: "DE",
      email: null,
      postalCode: "12345",
      recipientName: "Rechnung",
      streetLine1: "Rechnungsweg 1",
    },
    lines: [],
    status: "draft",
  } as unknown as CommitmentResponse;

  function renderForm(
    completion: { confirmationDue: boolean; reason: string | null } | null,
  ) {
    const listBuyerMails = vi.fn(async () => ({
      commitmentId: "c1",
      completion,
      mails: [],
    }));
    const client = {
      getBuyerMailConfiguration: vi.fn(async () => ({
        actionId: "a1",
        deliveryDayMail: false,
        deliveryDaySendTime: "07:00",
        internalOrderMails: true,
        revision: 2,
      })),
      getDeliveryConfiguration: vi.fn(async () => ({
        actionId: "a1",
        enabled: true,
        revision: 1,
        startPoint: null,
        timezone: "Europe/Berlin",
        windows: [
          {
            deliveryOn: "2099-12-04",
            endsAt: "10:00:00",
            fullyBooked: false,
            id: "w-next",
            retired: false,
            startsAt: "08:00:00",
          },
          {
            deliveryOn: "2020-12-04",
            endsAt: "10:00:00",
            fullyBooked: false,
            id: "w-over",
            retired: false,
            startsAt: "08:00:00",
          },
        ],
      })),
      listBuyerMails,
    } as unknown as LeonAidApiClient;
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <DeliveryCompletion client={client} onSaved={vi.fn()} order={draft} />
      </QueryClientProvider>,
    );
    return { listBuyerMails };
  }

  it("announces the confirmation when the server says one is due", async () => {
    const { listBuyerMails } = renderForm({
      confirmationDue: true,
      reason: null,
    });
    const notice = await screen.findByTestId("buyer-mail-notice");
    expect(listBuyerMails).toHaveBeenCalledWith("a1", "c1");
    expect(notice.textContent).toBe(
      "E-Mails zu dieser Bestellung gehen an einkauf@sonnenseite.invalid " +
        "(Adresse des Sponsors aus dem CRM): die Bestellbestätigung und " +
        "eine Stornierung. Klären Sie mit dem Käufer, ob die Adresse " +
        "stimmt, bevor Sie speichern.",
    );
  });

  it.each([
    ["action_closed", "Die Aktion ist abgeschlossen."],
    [
      "delivery_recorded",
      "Die Lieferung ist schon als geliefert oder nicht zugestellt erfasst.",
    ],
    ["window_over", "Das Lieferfenster ist vorbei."],
  ])(
    "announces no confirmation when the server says none is due: %s",
    async (reason, text) => {
      renderForm({ confirmationDue: false, reason });
      const notice = await screen.findByTestId("buyer-mail-notice");
      expect(notice.textContent).toBe(
        `Für diese Bestellung geht keine Bestellbestätigung mehr hinaus: ${text} ` +
          "Eine Stornierung ginge an einkauf@sonnenseite.invalid (Adresse des " +
          "Sponsors aus dem CRM).",
      );
      expect(notice.textContent).not.toContain("gehen an");
    },
  );

  it("announces none for a window of the past that the form selects", async () => {
    renderForm({ confirmationDue: true, reason: null });
    const notice = await screen.findByTestId("buyer-mail-notice");
    expect(notice.textContent).toContain("die Bestellbestätigung");
    const past = within(await screen.findByTestId("delivery-window-past"));
    fireEvent.click(past.getByRole("radio"));
    await waitFor(() =>
      expect(screen.getByTestId("buyer-mail-notice").textContent).toContain(
        "keine Bestellbestätigung mehr hinaus: Das Lieferfenster ist vorbei.",
      ),
    );
  });

  it("shows nothing while the rule is unknown", async () => {
    const client = {
      getBuyerMailConfiguration: vi.fn(async () => ({
        actionId: "a1",
        deliveryDayMail: false,
        deliveryDaySendTime: "07:00",
        internalOrderMails: true,
        revision: 2,
      })),
      getDeliveryConfiguration: vi.fn(async () => {
        throw new Error("offline");
      }),
      listBuyerMails: vi.fn(async () => {
        throw new Error("offline");
      }),
    } as unknown as LeonAidApiClient;
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <DeliveryCompletion client={client} onSaved={vi.fn()} order={draft} />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Angaben speichern" });
    await waitFor(() => expect(client.listBuyerMails).toHaveBeenCalled());
    expect(screen.queryByTestId("buyer-mail-notice")).toBeNull();
  });
});
