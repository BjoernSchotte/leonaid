import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
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
  type ActionManagementResponse,
  type BuyerMailConfigurationRequest,
  type BuyerMailConfigurationResponse,
  type CharityActionConfigurationResponse,
  type CharityActionResponse,
  type CurrentIdentityResponse,
  type DeliveryConfigurationResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { FeatureFlagProvider, ManageActionPage } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { actionLocation } from "../../../packages/features/src/action-admin/manage-action";
import { windowLabel } from "../../../packages/features/src/action-admin/delivery-section";
import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const actionId = "20000000-0000-4000-8000-000000000001";

beforeAll(() => {
  installDialogPolyfill();
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
  window.history.replaceState(null, "", "/admin/actions");
  vi.restoreAllMocks();
});

function action(
  overrides: Partial<CharityActionResponse> = {},
): CharityActionResponse {
  return {
    archiveSlug: "krapfentaxi-2026",
    beneficiaries: [
      {
        id: "b1",
        organizationName: "Kinderhospiz Beispielstadt",
        publicDescription: "Begleitet Familien.",
        sortOrder: 0,
      },
    ],
    capabilities: ["acquisition", "offerings", "ordering", "delivery"],
    carrierName: "Lions Hilfswerk Beispielstadt e. V.",
    endsOn: "2099-11-15",
    goal: {
      actualValue: "900",
      currency: "EUR",
      goalValue: "1000",
      unit: null,
    },
    id: actionId,
    isPublished: true,
    name: "Krapfentaxi 2099",
    presentationTheme: null,
    publicationEndsAt: null,
    publicationStartsAt: null,
    purpose: "Krapfen für den guten Zweck.",
    revision: 7,
    startsOn: "2099-09-01",
    status: "draft",
    ...overrides,
  };
}

function management(
  overrides: Partial<CharityActionResponse> = {},
  allowedTransitions: ActionManagementResponse["allowedTransitions"] = [
    "scheduled",
  ],
): ActionManagementResponse {
  return {
    action: action(overrides),
    administratorOptions: [
      {
        displayName: "Klara Kern",
        email: "klara@leonaid.invalid",
        isAvailable: true,
        isResponsible: true,
        userId: "u1",
      },
    ],
    allowedTransitions,
    publicAlias: "krapfentaxi",
  };
}

const configuration: CharityActionConfigurationResponse = {
  action: action(),
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
  ],
  orderForm: null,
  template: {
    copiedFromActionId: null,
    displayName: "Krapfentaxi",
    key: "krapfentaxi",
    version: 3,
  },
};

const delivery: DeliveryConfigurationResponse = {
  actionId,
  enabled: true,
  revision: 4,
  startPoint: null,
  timezone: "Europe/Berlin",
  windows: [
    {
      deliveryOn: "2099-11-12",
      endsAt: "11:00:00",
      fullyBooked: false,
      id: "w1",
      retired: false,
      startsAt: "09:00:00",
    },
  ],
};

const buyerMails: BuyerMailConfigurationResponse = {
  actionId,
  deliveryDayMail: false,
  deliveryDaySendTime: "07:00",
  internalOrderMails: false,
  revision: 3,
};

function fakeClient(state: ActionManagementResponse = management()) {
  return {
    getCharityActionManagement: vi.fn(async () => state),
    getCharityActionConfiguration: vi.fn(async () => configuration),
    listActionTemplates: vi.fn(async () => ({
      items: [
        {
          capabilities: ["ordering"],
          description: "Krapfen ausliefern.",
          displayName: "Krapfentaxi",
          hasOrderForm: true,
          key: "krapfentaxi",
          offeringCount: 2,
          presentationTheme: null,
          version: 3,
        },
      ],
    })),
    getDeliveryConfiguration: vi.fn(async () => delivery),
    saveDeliveryConfiguration: vi.fn(async () => delivery),
    setDeliveryWindowFullyBooked: vi.fn(async () => ({
      ...delivery,
      windows: delivery.windows.map((item) => ({ ...item, fullyBooked: true })),
    })),
    listCommitments: vi.fn(async () => ({
      actionId,
      currencyTotals: [],
      items: [
        {
          capturedByDisplayName: null,
          createdAt: "2099-10-01T10:00:00Z",
          commitment: {
            deliveryWindowId: "w1",
            status: "confirmed",
            totalBoxes: 6,
          },
        },
        {
          capturedByDisplayName: null,
          createdAt: "2099-10-01T10:00:00Z",
          commitment: {
            deliveryWindowId: "w1",
            status: "cancelled",
            totalBoxes: 9,
          },
        },
      ],
      quantities: [],
      totalBoxes: 6,
      totalPieces: 0,
    })),
    getActionPublicUrls: vi.fn(async () => ({
      canonicalUrl: "https://krapfentaxi.org/" as string | null,
      editions: [
        {
          atRoot: true,
          campaignPage: false,
          editionUrl: "https://krapfentaxi.org/2099/",
          hostStatus: "active",
          hostname: "krapfentaxi.org",
          isPrimary: true,
          segment: "2099",
        },
      ],
    })),
    listCampaignAliases: vi.fn(async () => ({
      actionId,
      canonicalPath: "/campaigns/krapfentaxi-2099/",
      items: [
        {
          actionId,
          alias: "krapfentaxi",
          aliasId: "a1",
          enabled: true,
          isPrimary: true,
          revision: 1,
        },
        {
          actionId,
          alias: "krapfen-flyer",
          aliasId: "a2",
          enabled: true,
          isPrimary: false,
          revision: 2,
        },
      ],
      targets: [
        {
          actionId,
          canonicalPath: "/campaigns/krapfentaxi-2099/",
          name: "Krapfentaxi 2099",
        },
      ],
    })),
    resolvePublicActionAlias: vi.fn(async () => ({ redirectPath: "/x" })),
    transitionCharityAction: vi.fn(async () => action({ status: "scheduled" })),
    copyCharityAction: vi.fn(async () => ({
      ...configuration,
      action: action({ id: "new-id" }),
    })),
    setCharityActionDetails: vi.fn(
      async (_id: string, body: { revision: number; name: string }) =>
        action({ name: body.name, revision: body.revision + 1 }),
    ),
    setCharityActionGoal: vi.fn(
      async (_id: string, body: { revision: number }) =>
        action({ revision: body.revision + 1 }),
    ),
    setCharityActionPublication: vi.fn(),
    updateCampaignAlias: vi.fn(),
    getBuyerMailConfiguration: vi.fn(
      async (): Promise<BuyerMailConfigurationResponse> => buyerMails,
    ),
    saveBuyerMailConfiguration: vi.fn(
      async (
        _id: string,
        body: BuyerMailConfigurationRequest,
      ): Promise<BuyerMailConfigurationResponse> => ({
        actionId,
        deliveryDayMail: body.deliveryDayMail,
        deliveryDaySendTime: body.deliveryDaySendTime,
        internalOrderMails: body.internalOrderMails,
        revision: body.expectedRevision + 1,
      }),
    ),
  };
}

async function renderPage(
  hash = "",
  client: ReturnType<typeof fakeClient> = fakeClient(),
  {
    tours = false,
    editorHref,
  }: { readonly tours?: boolean; readonly editorHref?: string } = {},
) {
  window.history.replaceState(null, "", `/admin/actions/${actionId}${hash}`);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const page = (
    <ManageActionPage
      actionId={actionId}
      client={client as unknown as LeonAidApiClient}
      editorHref={editorHref}
    />
  );
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <HotkeyProvider>
          {tours ? (
            <FeatureFlagProvider
              client={
                {
                  ...client,
                  getFeatureFlagEvaluations: vi.fn(async () => ({
                    flags: [{ enabled: true, key: "delivery.tours" }],
                  })),
                } as unknown as LeonAidApiClient
              }
              identity={
                {
                  actionMemberships: [],
                  globalRoles: ["charity_admin"],
                  userId: "klara",
                } as unknown as CurrentIdentityResponse
              }
              surface="web"
            >
              {page}
            </FeatureFlagProvider>
          ) : (
            page
          )}
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findByTestId("management-title");
  lastQueryClient = queryClient;
  return client;
}

let lastQueryClient: QueryClient | undefined;

describe("action detail: CMS editor link", () => {
  it("links to the editor only when the installation runs the CMS", async () => {
    await renderPage();
    // Without the CMS /_emdash has no upstream: no link instead of a 502.
    expect(
      screen.queryByRole("link", { name: "Microsite bearbeiten" }),
    ).toBeNull();
    cleanup();

    const href = `/_emdash/admin/campaigns/${actionId}`;
    await renderPage("", fakeClient(), { editorHref: href });
    expect(
      screen
        .getByRole("link", { name: "Microsite bearbeiten" })
        .getAttribute("href"),
    ).toBe(href);
  });
});

describe("action detail: drafts and revisions", () => {
  it("keeps Esc in a form field: no navigation", async () => {
    const assign = vi.fn();
    await renderPage("#aliases");
    const field = await screen.findByTestId("publication-alias");
    const { pathname, search, hash } = window.location;
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname,
      search,
      hash,
    } as Location);
    field.focus();
    fireEvent.keyDown(field, { key: "Escape" });
    expect(assign).not.toHaveBeenCalled();
    field.blur();
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/admin/actions"));
  });

  it("asks before leaving the edit mode with unsaved input", async () => {
    await renderPage("#overview/edit");
    fireEvent.change(screen.getByTestId("manage-name"), {
      target: { value: "Neuer Name" },
    });
    fireEvent.click(screen.getByTestId("action-edit-done"));
    const ask = within(
      await screen.findByRole("alertdialog", { name: "Entwurf verwerfen?" }),
    );
    fireEvent.click(ask.getByRole("button", { name: "Weiter bearbeiten" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect((screen.getByTestId("manage-name") as HTMLInputElement).value).toBe(
      "Neuer Name",
    );
    // A number key asks too; "Verwerfen" leaves.
    fireEvent.keyDown(document.body, { key: "3" });
    fireEvent.click(
      within(
        await screen.findByRole("alertdialog", { name: "Entwurf verwerfen?" }),
      ).getByRole("button", { name: "Verwerfen" }),
    );
    await screen.findByTestId("alias-list");
    expect(screen.queryByTestId("manage-name")).toBeNull();
  });

  it("sends the page's own newer revision after its own save", async () => {
    const client = await renderPage("#overview/edit");
    fireEvent.change(screen.getByTestId("manage-name"), {
      target: { value: "Neuer Name" },
    });
    fireEvent.click(screen.getByTestId("save-details"));
    await waitFor(() =>
      expect(client.setCharityActionDetails).toHaveBeenCalledWith(
        actionId,
        expect.objectContaining({ revision: 7 }),
      ),
    );
    fireEvent.change(screen.getByTestId("manage-actual"), {
      target: { value: "950" },
    });
    fireEvent.click(screen.getByTestId("save-goal"));
    await waitFor(() =>
      expect(client.setCharityActionGoal).toHaveBeenCalledWith(
        actionId,
        expect.objectContaining({ revision: 8 }),
      ),
    );
  });

  it("keeps the draft's revision when someone else changed the action", async () => {
    const client = fakeClient();
    await renderPage("#overview/edit", client);
    fireEvent.change(screen.getByTestId("manage-name"), {
      target: { value: "Meine Änderung" },
    });
    // A refetch (window focus) brings another admin's revision 9.
    client.getCharityActionManagement.mockResolvedValue(
      management({ revision: 9, name: "Fremde Änderung" }),
    );
    await lastQueryClient!.invalidateQueries();
    await waitFor(() =>
      expect(client.getCharityActionManagement).toHaveBeenCalledTimes(2),
    );
    client.setCharityActionDetails.mockRejectedValueOnce(
      new ApiError(409, {
        code: "action_revision_conflict",
        message: "Konflikt",
        requestId: "r9",
      }),
    );
    fireEvent.click(screen.getByTestId("save-details"));
    await waitFor(() =>
      expect(client.setCharityActionDetails).toHaveBeenCalledWith(
        actionId,
        expect.objectContaining({ name: "Meine Änderung", revision: 7 }),
      ),
    );
    // "Aktuellen Stand laden" replaces the draft with the current state.
    fireEvent.click(await screen.findByTestId("section-reload"));
    expect((screen.getByTestId("manage-name") as HTMLInputElement).value).toBe(
      "Fremde Änderung",
    );
  });

  it("retries an alias change with the fresh revision after a conflict", async () => {
    const client = fakeClient();
    client.updateCampaignAlias
      .mockRejectedValueOnce(
        new ApiError(409, {
          code: "campaign_alias_revision_conflict",
          message: "Konflikt",
          requestId: "r2",
        }),
      )
      .mockResolvedValueOnce({
        actionId,
        alias: "krapfen-flyer",
        aliasId: "a2",
        enabled: false,
        removed: false,
        revision: 4,
      });
    await renderPage("#aliases", client);
    fireEvent.click(
      await screen.findByRole("button", { name: "/krapfen-flyer bearbeiten" }),
    );
    const dialog = within(
      screen.getByRole("dialog", { name: "/krapfen-flyer bearbeiten" }),
    );
    fireEvent.change(dialog.getByTestId("alias-enabled"), {
      target: { value: "disabled" },
    });
    // Meanwhile the alias has revision 3 on the server.
    const fresh = await client.listCampaignAliases();
    client.listCampaignAliases.mockResolvedValue({
      ...fresh,
      items: fresh.items.map((item) =>
        item.aliasId === "a2" ? { ...item, revision: 3 } : item,
      ),
    });
    const loads = client.listCampaignAliases.mock.calls.length;
    fireEvent.click(dialog.getByTestId("alias-save"));
    expect(
      await dialog.findByText(/Ihre Eingaben bleiben erhalten/),
    ).toBeTruthy();
    await waitFor(() =>
      expect(client.listCampaignAliases.mock.calls.length).toBeGreaterThan(
        loads,
      ),
    );
    fireEvent.click(dialog.getByTestId("alias-save"));
    await waitFor(() =>
      expect(client.updateCampaignAlias).toHaveBeenLastCalledWith(
        actionId,
        "a2",
        expect.objectContaining({ revision: 3, enabled: false }),
      ),
    );
  });

  it("shows the overview for #delivery without delivery and names it", async () => {
    await renderPage(
      "#delivery",
      fakeClient(management({ capabilities: ["ordering"] })),
    );
    await waitFor(() => expect(window.location.hash).toBe("#overview"));
    expect(screen.getByTestId("action-overview")).toBeTruthy();
  });

  it("keeps the public alias read-only once the action is completed", async () => {
    await renderPage(
      "#aliases",
      fakeClient(management({ status: "completed" }, ["archived"])),
    );
    expect(
      (await screen.findByTestId("aliases-read-only")).textContent,
    ).toContain("Nach dem Abschluss");
    // Inside the disabled fieldset: not editable.
    expect(screen.getByTestId("publication-alias").matches(":disabled")).toBe(
      true,
    );
    expect(
      screen
        .getByRole("button", { name: "Öffentliche Seite speichern" })
        .matches(":disabled"),
    ).toBe(true);
  });

  it("names retired windows instead of asking for the first one", async () => {
    const client = fakeClient();
    client.getDeliveryConfiguration.mockResolvedValue({
      ...delivery,
      windows: delivery.windows.map((item) => ({ ...item, retired: true })),
    });
    await renderPage("#delivery", client);
    const next = await screen.findByTestId("delivery-next-step");
    expect(next.textContent).toContain("Alle Lieferfenster sind stillgelegt.");
    expect(next.textContent).not.toContain("Erstes Lieferfenster");
  });

  it("shows the action's public addresses read only (multi-domain §7.1)", async () => {
    const client = fakeClient();
    await renderPage("#aliases", client);
    const section = await screen.findByTestId("action-public-urls");
    expect(section.textContent).toContain("https://krapfentaxi.org/");
    expect(section.textContent).toContain("krapfentaxi.org/2099/");
    expect(section.textContent).toContain("aktuell auf /");
    // R41: the host shows nothing without a published CMS page.
    expect(section.textContent).toContain(
      "Keine veröffentlichte Kampagnenseite",
    );
    expect(within(section).queryByRole("button")).toBeNull();
  });

  it("names an action without public address (multi-domain §6.6)", async () => {
    const client = fakeClient();
    client.getActionPublicUrls.mockResolvedValue({
      canonicalUrl: null,
      editions: [],
    });
    await renderPage("#aliases", client);
    expect(
      (await screen.findByTestId("action-public-urls")).textContent,
    ).toContain("Nicht öffentlich erreichbar");
  });

  it("marks the aliases of an archived action as read-only", async () => {
    await renderPage(
      "#aliases",
      fakeClient(management({ status: "archived" }, [])),
    );
    expect(
      (await screen.findByTestId("aliases-read-only")).textContent,
    ).toContain("Nur lesen.");
    expect(screen.queryByTestId("alias-add")).toBeNull();
  });
});

describe("action location", () => {
  it("maps tabs, edit mode and the former panel hashes", () => {
    expect(actionLocation("")).toEqual({ tab: "overview", editing: false });
    expect(actionLocation("#delivery")).toEqual({
      tab: "delivery",
      editing: false,
    });
    expect(actionLocation("#overview/edit")).toEqual({
      tab: "overview",
      editing: true,
    });
    for (const legacy of ["#basics", "#goal", "#team", "#administrators"]) {
      expect(actionLocation(legacy)).toEqual({
        tab: "overview",
        editing: true,
      });
    }
    expect(actionLocation("#public").tab).toBe("aliases");
    expect(actionLocation("#status")).toEqual({
      tab: "overview",
      editing: false,
    });
  });

  it("labels a delivery window like the prototype", () => {
    expect(
      windowLabel({
        deliveryOn: "2099-11-12",
        startsAt: "09:00:00",
        endsAt: "11:00:00",
      }),
    ).toMatch(/^[A-Za-z]{2} 12\.11\. · 09:00–11:00 Uhr$/);
  });
});

describe("action detail", () => {
  it("shows the overview, the status and the next step", async () => {
    const client = await renderPage();
    expect(screen.getByTestId("management-status").textContent).toBe("Entwurf");
    expect(
      screen
        .getByRole("tab", { name: /Überblick/ })
        .getAttribute("aria-selected"),
    ).toBe("true");
    const overview = within(screen.getByTestId("action-overview"));
    expect(overview.getByText("Krapfen für den guten Zweck.")).toBeTruthy();
    expect(overview.getByText("/krapfentaxi")).toBeTruthy();
    const step = within(screen.getByTestId("action-next-step"));
    expect(step.getByText("Nächster Schritt:")).toBeTruthy();
    fireEvent.click(step.getByTestId("transition-scheduled"));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Aktion einplanen",
      }),
    );
    await waitFor(() =>
      expect(client.transitionCharityAction).toHaveBeenCalledWith(actionId, {
        revision: 7,
        targetStatus: "scheduled",
      }),
    );
  });

  it("opens the edit forms with Bearbeiten and keeps the hash", async () => {
    await renderPage();
    expect(screen.queryByTestId("manage-name")).toBeNull();
    fireEvent.click(screen.getByTestId("action-edit"));
    expect((screen.getByTestId("manage-name") as HTMLInputElement).value).toBe(
      "Krapfentaxi 2099",
    );
    expect(window.location.hash).toBe("#overview/edit");
    fireEvent.click(screen.getByTestId("action-edit-done"));
    expect(screen.queryByTestId("manage-name")).toBeNull();
  });

  it("switches the buyer mails for internal orders at once, with the row's revision", async () => {
    const client = await renderPage("#overview/edit");
    const section = await screen.findByTestId("buyer-mail-section");
    expect(section.textContent).toContain("E-Mails an Käufer");
    // The switch says what the buyer gets and when.
    expect(section.textContent).toContain(
      "Der Käufer erhält eine Bestellbestätigung, sobald die Bestellung prüfbereit ist, und eine Nachricht, wenn sie storniert wird.",
    );
    const toggle = within(section).getByRole("switch", {
      name: "E-Mails für Bestellungen, die Mitglieder erfassen",
    }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(within(section).getByText("Aus")).toBeTruthy();
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(client.saveBuyerMailConfiguration).toHaveBeenCalledWith(actionId, {
        deliveryDayMail: false,
        deliveryDaySendTime: "07:00",
        expectedRevision: 3,
        internalOrderMails: true,
      }),
    );
    await within(section).findByText("An");
    expect(
      (
        within(section).getByRole("switch", {
          name: "E-Mails für Bestellungen, die Mitglieder erfassen",
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
    // The next change sends the revision the server answered with.
    fireEvent.click(within(section).getByRole("switch"));
    await waitFor(() =>
      expect(client.saveBuyerMailConfiguration).toHaveBeenLastCalledWith(
        actionId,
        expect.objectContaining({
          expectedRevision: 4,
          internalOrderMails: false,
        }),
      ),
    );
    // The action's own revision is not involved.
    expect(client.setCharityActionDetails).not.toHaveBeenCalled();
  });

  it("shows the changed switches after a conflict and the server's message", async () => {
    const client = fakeClient();
    client.saveBuyerMailConfiguration.mockRejectedValue(
      new ApiError(409, {
        code: "buyer_mail_configuration_conflict",
        message:
          "Die Einstellungen wurden inzwischen geändert. Bitte den aktuellen Stand laden.",
        requestId: "req-9",
      }),
    );
    await renderPage("#overview/edit", client);
    const section = await screen.findByTestId("buyer-mail-section");
    client.getBuyerMailConfiguration.mockResolvedValue({
      ...buyerMails,
      internalOrderMails: true,
      revision: 4,
    });
    fireEvent.click(within(section).getByRole("switch"));
    expect(
      await within(section).findByText(
        /Die Einstellungen wurden inzwischen geändert\./,
      ),
    ).toBeTruthy();
    await waitFor(() =>
      expect(
        (within(section).getByRole("switch") as HTMLInputElement).checked,
      ).toBe(true),
    );
  });

  it("offers no buyer mail switches for an action without orders", async () => {
    const client = fakeClient(management({ capabilities: ["acquisition"] }));
    await renderPage("#overview/edit", client);
    await screen.findByTestId("action-edit-forms");
    expect(screen.queryByTestId("buyer-mail-section")).toBeNull();
    expect(client.getBuyerMailConfiguration).not.toHaveBeenCalled();
  });

  it("is read-only when archived: no edit, no next step", async () => {
    await renderPage("", fakeClient(management({ status: "archived" }, [])));
    expect(screen.getByTestId("action-read-only").textContent).toContain(
      "Nur lesen.",
    );
    expect(screen.queryByTestId("action-edit")).toBeNull();
    expect(screen.queryByTestId("action-next-step")).toBeNull();
  });

  it("adds a delivery window with the configuration revision", async () => {
    const client = await renderPage("#delivery");
    const table = await screen.findByTestId("delivery-windows");
    // Booked boxes ignore cancelled orders.
    expect(within(table).getByText("6")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Lieferfenster hinzufügen" }),
    );
    const dialog = within(
      screen.getByRole("dialog", { name: "Lieferfenster hinzufügen" }),
    );
    fireEvent.click(dialog.getByTestId("delivery-window-save"));
    expect(dialog.getByText("Bitte einen Tag wählen.")).toBeTruthy();
    fireEvent.change(dialog.getByTestId("delivery-window-day"), {
      target: { value: "2099-11-13" },
    });
    fireEvent.click(dialog.getByTestId("delivery-window-save"));
    await waitFor(() =>
      expect(client.saveDeliveryConfiguration).toHaveBeenCalledWith(actionId, {
        expectedRevision: 4,
        enabled: true,
        timezone: "Europe/Berlin",
        windows: [
          {
            id: "w1",
            deliveryOn: "2099-11-12",
            startsAt: "09:00:00",
            endsAt: "11:00:00",
            retired: false,
          },
          {
            deliveryOn: "2099-11-13",
            startsAt: "09:00",
            endsAt: "11:00",
            retired: false,
          },
        ],
      }),
    );
  });

  it("keeps the modal input when the configuration changed meanwhile", async () => {
    const client = fakeClient();
    client.saveDeliveryConfiguration.mockRejectedValue(
      new ApiError(409, {
        code: "delivery_configuration_conflict",
        message: "Konflikt",
        requestId: "r1",
      }),
    );
    await renderPage("#delivery", client);
    await screen.findByTestId("delivery-windows");
    fireEvent.click(
      screen.getByRole("button", { name: "Lieferfenster hinzufügen" }),
    );
    const dialog = within(
      screen.getByRole("dialog", { name: "Lieferfenster hinzufügen" }),
    );
    fireEvent.change(dialog.getByTestId("delivery-window-day"), {
      target: { value: "2099-11-13" },
    });
    fireEvent.click(dialog.getByTestId("delivery-window-save"));
    expect(await dialog.findByText(/inzwischen geändert/)).toBeTruthy();
    expect(
      (dialog.getByTestId("delivery-window-day") as HTMLInputElement).value,
    ).toBe("2099-11-13");
    await waitFor(() =>
      expect(client.getDeliveryConfiguration).toHaveBeenCalledTimes(2),
    );
  });

  it("switches a window to ausgebucht at once, outside the form", async () => {
    const client = await renderPage("#delivery");
    const table = await screen.findByTestId("delivery-windows");
    expect(within(table).getByText("Buchbar")).toBeTruthy();
    const toggle = screen.getByRole("switch", {
      name: /ausgebucht$/,
    }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(client.setDeliveryWindowFullyBooked).toHaveBeenCalledWith(
        actionId,
        "w1",
        { fullyBooked: true },
      ),
    );
    // The status badge follows; the column header also reads "Ausgebucht".
    await waitFor(() =>
      expect(within(table).queryByText("Buchbar")).toBeNull(),
    );
    expect(within(table).getAllByText("Ausgebucht")).toHaveLength(2);
    expect(
      (screen.getByRole("switch", { name: /ausgebucht$/ }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(client.saveDeliveryConfiguration).not.toHaveBeenCalled();
  });

  it("retires a window only after the confirmation", async () => {
    const client = await renderPage("#delivery");
    await screen.findByTestId("delivery-windows");
    fireEvent.click(screen.getByRole("button", { name: /stilllegen$/ }));
    expect(client.saveDeliveryConfiguration).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Fenster stilllegen",
      }),
    );
    await waitFor(() =>
      expect(client.saveDeliveryConfiguration).toHaveBeenCalledWith(
        actionId,
        expect.objectContaining({
          windows: [expect.objectContaining({ id: "w1", retired: true })],
        }),
      ),
    );
  });

  it("start point fields round-trip", async () => {
    const stored: DeliveryConfigurationResponse = {
      ...delivery,
      startPoint: {
        address: "Marktstraße 50, 83646 Bad Tölz",
        label: "Bäckerei",
        lat: 47.7601,
        locating: false,
        lon: 11.5589,
      },
    };
    const client = fakeClient();
    client.getDeliveryConfiguration.mockResolvedValue(stored);
    client.saveDeliveryConfiguration.mockResolvedValue({
      ...stored,
      revision: 5,
      startPoint: {
        address: "Marktstraße 27, 83646 Bad Tölz",
        label: "Backstube",
        lat: null,
        locating: true,
        lon: null,
      },
    });
    await renderPage("#delivery", client, { tours: true });
    const label = (await screen.findByTestId(
      "delivery-start-label",
    )) as HTMLInputElement;
    const address = screen.getByTestId(
      "delivery-start-address",
    ) as HTMLInputElement;
    expect(label.value).toBe("Bäckerei");
    expect(address.value).toBe("Marktstraße 50, 83646 Bad Tölz");
    expect(screen.getByTestId("delivery-start-status").textContent).toContain(
      "Auf der Karte",
    );
    fireEvent.change(label, { target: { value: "Backstube" } });
    fireEvent.change(address, {
      target: { value: "Marktstraße 27, 83646 Bad Tölz" },
    });
    fireEvent.click(screen.getByTestId("delivery-start-save"));
    await waitFor(() =>
      expect(client.saveDeliveryConfiguration).toHaveBeenCalledWith(actionId, {
        enabled: true,
        expectedRevision: 4,
        startPoint: {
          address: "Marktstraße 27, 83646 Bad Tölz",
          label: "Backstube",
        },
        timezone: "Europe/Berlin",
        windows: [
          {
            deliveryOn: "2099-11-12",
            endsAt: "11:00:00",
            id: "w1",
            retired: false,
            startsAt: "09:00:00",
          },
        ],
      }),
    );
    expect(
      (await screen.findByTestId("delivery-start-status")).textContent,
    ).toContain("wird gesucht");
    expect(
      (screen.getByTestId("delivery-start-label") as HTMLInputElement).value,
    ).toBe("Backstube");
  });

  it("start point: hint when the address was not found, multi-line refused", async () => {
    const client = fakeClient();
    client.getDeliveryConfiguration.mockResolvedValue({
      ...delivery,
      startPoint: {
        address: "Am Markt",
        label: "Bäckerei",
        lat: null,
        locating: false,
        lon: null,
      },
    });
    await renderPage("#delivery", client, { tours: true });
    expect(
      (await screen.findByTestId("delivery-start-status")).textContent,
    ).toBe("Startpunkt nicht gefunden – Pin auf der Karte setzen");
    fireEvent.change(screen.getByTestId("delivery-start-label"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByTestId("delivery-start-save"));
    expect(
      await screen.findByText("Bitte eine Bezeichnung angeben."),
    ).toBeTruthy();
    expect(client.saveDeliveryConfiguration).not.toHaveBeenCalled();
  });

  it("start point: no fields without the tours flag; window saves leave it out", async () => {
    const client = await renderPage("#delivery");
    await screen.findByTestId("delivery-windows");
    expect(screen.queryByTestId("delivery-start-label")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /stilllegen$/ }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Fenster stilllegen",
      }),
    );
    await waitFor(() =>
      expect(client.saveDeliveryConfiguration).toHaveBeenCalled(),
    );
    const [, body] = client.saveDeliveryConfiguration.mock
      .calls[0] as unknown as [string, object];
    expect(body).not.toHaveProperty("startPoint");
  });

  it("lists the active alias, the redirects and the permanent address", async () => {
    await renderPage("#aliases");
    const list = within(await screen.findByTestId("alias-list"));
    expect(list.getByText("Aktiver Alias")).toBeTruthy();
    expect(list.getByText("/krapfen-flyer")).toBeTruthy();
    expect(list.getByText("/campaigns/krapfentaxi-2099/")).toBeTruthy();
    expect(screen.getByTestId("publication-alias")).toBeTruthy();
  });

  it("copies the action for its next edition", async () => {
    const assign = vi.fn();
    const client = await renderPage("#templates");
    fireEvent.click(await screen.findByTestId("copy-action"));
    const dialog = within(
      screen.getByRole("dialog", { name: "Für die nächste Ausgabe kopieren" }),
    );
    expect(
      (dialog.getByTestId("copy-action-name") as HTMLInputElement).value,
    ).toBe("Krapfentaxi 2100");
    expect(
      (dialog.getByTestId("copy-action-slug") as HTMLInputElement).value,
    ).toBe("krapfentaxi-2100");
    const { pathname, search, hash } = window.location;
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      pathname,
      search,
      hash,
    } as Location);
    fireEvent.click(dialog.getByTestId("copy-action-submit"));
    await waitFor(() =>
      expect(client.copyCharityAction).toHaveBeenCalledWith(actionId, {
        name: "Krapfentaxi 2100",
        startsOn: "2100-09-01",
        endsOn: "2100-11-15",
        archiveSlug: "krapfentaxi-2100",
      }),
    );
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("/admin/actions/new-id"),
    );
  });

  it("shows the offerings read-only with their form status", async () => {
    await renderPage("#offers");
    const table = within(await screen.findByTestId("offerings-table"));
    expect(table.getByText("Krapfenbox")).toBeTruthy();
    expect(table.getByText("Wird angeboten")).toBeTruthy();
    expect(table.getByText(/24,00/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Angebote/ }).textContent).toContain(
      "1",
    );
  });

  it("switches tabs with the number keys", async () => {
    await renderPage();
    fireEvent.keyDown(document.body, { key: "3" });
    await screen.findByTestId("alias-list");
    expect(window.location.hash).toBe("#aliases");
  });
});
