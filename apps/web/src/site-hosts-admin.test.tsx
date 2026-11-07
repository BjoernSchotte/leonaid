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
  type LeonAidApiClient,
  type SiteBindingResponse,
  type SiteHostListResponse,
  type SiteHostResponse,
} from "@leonaid/api-client";
import { SiteHostsTab, systemSection } from "@leonaid/features";
import { ToastProvider } from "@leonaid/ui";

import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

beforeAll(() => {
  installDialogPolyfill();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function binding(fields: Partial<SiteBindingResponse>): SiteBindingResponse {
  return {
    actionId: "a-2025",
    actionName: "Lions Open 2025",
    archiveSlug: "lions-open-2025",
    atRoot: false,
    availability: "archive",
    campaignPage: true,
    editionUrl: "https://lionsopen.de/2025/",
    endedReason: null,
    id: "b-2025",
    isPrimary: true,
    revision: 1,
    segment: "2025",
    targetUrl: null,
    validFrom: "2025-05-01T08:00:00Z",
    validTo: null,
    ...fields,
  };
}

function host(fields: Partial<SiteHostResponse>): SiteHostResponse {
  return {
    bindings: [],
    createdAt: "2026-11-01T08:00:00Z",
    displayHostname: "lionsopen.de",
    failedChecks: 0,
    history: [],
    hostname: "lionsopen.de",
    id: "h-1",
    kind: "campaign",
    lastCheckResult: null,
    lastCheckedAt: null,
    redirectToHostId: null,
    redirectToHostname: null,
    revision: 4,
    status: "active",
    verificationPath: "/.well-known/leonaid-host-check/token",
    verifiedAt: "2026-11-01T09:00:00Z",
    ...fields,
  };
}

const list: SiteHostListResponse = {
  actions: [
    {
      availability: "archive",
      campaignPage: true,
      id: "a-2025",
      name: "Lions Open 2025",
      archiveSlug: "lions-open-2025",
      status: "completed",
    },
    {
      availability: "inactive",
      campaignPage: true,
      id: "a-2026",
      name: "Lions Open 2026",
      archiveSlug: "lions-open-2026",
      status: "scheduled",
    },
    {
      availability: "published",
      campaignPage: false,
      id: "a-legacy",
      name: "Altaktion",
      archiveSlug: "altaktion",
      status: "active",
    },
  ],
  adminHost: "app.example.org",
  hosts: [
    host({
      bindings: [binding({ atRoot: true })],
      history: [
        binding({
          endedReason: "segment_changed",
          id: "b-old",
          segment: "lo-2025",
          targetUrl: "https://lionsopen.de/2025/",
          validTo: "2026-01-01T08:00:00Z",
        }),
      ],
    }),
    host({
      displayHostname: "neu.example.org",
      hostname: "neu.example.org",
      id: "h-2",
      revision: 1,
      status: "pending",
    }),
  ],
  publicHost: "example.org",
  publicHostAliases: ["www.example.org"],
};

function fakeClient() {
  return {
    listSiteHosts: vi.fn(async () => list),
    addSiteHost: vi.fn(async () =>
      host({ displayHostname: "krapfentaxi.org" }),
    ),
    bindSiteEdition: vi.fn(async () => list.hosts[0]),
    moveSiteRoot: vi.fn(async () => list.hosts[0]),
    changeSiteEditionSegment: vi.fn(async () => list.hosts[0]),
    unbindSiteEdition: vi.fn(async () => list.hosts[0]),
    setPrimarySiteEdition: vi.fn(async () => list.hosts[0]),
    setSiteHostRedirect: vi.fn(async () => list.hosts[1]),
    removeSiteHost: vi.fn(async () => list.hosts[0]),
    previewSiteHostRemoval: vi.fn(async () => ({
      hostId: "h-1",
      items: [
        {
          actionId: "a-2025",
          actionName: "Lions Open 2025",
          bindingId: "b-2025",
          currentUrl: "https://lionsopen.de/2025/",
          newUrl: "https://example.org/archive/lions-open-2025",
        },
      ],
      redirectHosts: [],
      revision: 4,
    })),
  };
}

function renderTab(client = fakeClient()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SiteHostsTab client={client as unknown as LeonAidApiClient} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return client;
}

describe("Domains", () => {
  it("has its own system URL", () => {
    expect(systemSection("/admin/system/domains")).toBe("domains");
  });

  it("lists hosts with status, editions, DNS hint and old paths", async () => {
    renderTab();
    const panels = await screen.findAllByTestId("site-host");
    expect(panels).toHaveLength(2);
    const [lionsopen, pending] = panels;
    expect(within(lionsopen!).getByText("Aktiv")).toBeTruthy();
    expect(lionsopen!.textContent).toContain("aktuell auf /");
    expect(lionsopen!.textContent).toContain("Frühere Pfade (1)");
    expect(lionsopen!.textContent).toContain("/lo-2025/");
    // An active host needs no DNS hint; a pending subdomain gets the CNAME.
    expect(lionsopen!.textContent).not.toContain("Prüfadresse");
    expect(within(pending!).getByText("Ausstehend")).toBeTruthy();
    expect(pending!.textContent).toContain("CNAME");
    expect(pending!.textContent).toContain(
      "http://neu.example.org/.well-known/leonaid-host-check/token",
    );
  });

  it("adds a host and reuses the command id for a retry", async () => {
    const client = renderTab();
    client.addSiteHost.mockRejectedValueOnce(
      new ApiError(409, {
        code: "site_host_busy",
        message: "Beschäftigt.",
        requestId: "r-1",
      }),
    );
    const input = await screen.findByTestId("site-host-name");
    fireEvent.change(input, { target: { value: "krapfentaxi.org" } });
    fireEvent.click(screen.getByRole("button", { name: /Domain hinzufügen/ }));
    expect(await screen.findByText(/Beschäftigt\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Domain hinzufügen/ }));
    await waitFor(() => expect(client.addSiteHost).toHaveBeenCalledTimes(2));
    const [first, second] = client.addSiteHost.mock.calls as unknown as [
      [{ commandId: string; hostname: string }],
      [{ commandId: string; hostname: string }],
    ];
    expect(first[0].hostname).toBe("krapfentaxi.org");
    expect(second[0].commandId).toBe(first[0].commandId);
  });

  it("hands the domain to the follow-up with a preview", async () => {
    const client = renderTab();
    const [lionsopen] = await screen.findAllByTestId("site-host");
    fireEvent.click(
      within(lionsopen!).getByRole("button", {
        name: "Domain an Folgeaktion übergeben",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    const select = within(dialog).getByTestId("site-edition-action");
    // Ended actions cannot take over the root.
    expect(select.textContent).not.toContain("Lions Open 2025");
    fireEvent.change(select, { target: { value: "a-2026" } });
    fireEvent.change(within(dialog).getByTestId("site-edition-segment"), {
      target: { value: "2026" },
    });
    const preview = within(dialog).getByTestId("site-move-preview");
    expect(preview.textContent).toContain("lionsopen.de/ → Lions Open 2026");
    expect(preview.textContent).toContain(
      "Lions Open 2025 → lionsopen.de/2025/",
    );
    fireEvent.click(within(dialog).getByTestId("site-dialog-confirm"));
    await waitFor(() =>
      expect(client.moveSiteRoot).toHaveBeenCalledWith(
        "h-1",
        expect.objectContaining({
          actionId: "a-2026",
          revision: 4,
          segment: "2026",
        }),
      ),
    );
  });

  it("warns before binding an action without a campaign page", async () => {
    renderTab();
    const [, pending] = await screen.findAllByTestId("site-host");
    fireEvent.click(
      within(pending!).getByRole("button", { name: "Aktion binden" }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByTestId("site-edition-action"), {
      target: { value: "a-legacy" },
    });
    expect(dialog.textContent).toContain(
      "keine veröffentlichte Kampagnenseite",
    );
    fireEvent.change(within(dialog).getByTestId("site-edition-segment"), {
      target: { value: "Bad Segment" },
    });
    expect(
      (within(dialog).getByTestId("site-dialog-confirm") as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("unbinds the only root edition only after the confirmation", async () => {
    const client = renderTab();
    const [lionsopen] = await screen.findAllByTestId("site-host");
    fireEvent.click(within(lionsopen!).getByRole("button", { name: "Lösen" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByTestId(
      "site-dialog-confirm",
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(client.unbindSiteEdition).toHaveBeenCalledWith(
        "h-1",
        "b-2025",
        expect.objectContaining({ confirmRootRemoval: true, revision: 4 }),
      ),
    );
  });

  it("shows where each edition goes before a removal", async () => {
    const client = renderTab();
    const [lionsopen] = await screen.findAllByTestId("site-host");
    fireEvent.click(
      within(lionsopen!).getByRole("button", { name: /Domain entfernen/ }),
    );
    const preview = await screen.findByTestId("site-removal-preview");
    expect(preview.textContent).toContain(
      "https://lionsopen.de/2025/ → https://example.org/archive/lions-open-2025",
    );
    fireEvent.click(screen.getByTestId("site-dialog-confirm"));
    await waitFor(() =>
      expect(client.removeSiteHost).toHaveBeenCalledWith(
        "h-1",
        expect.objectContaining({ revision: 4 }),
      ),
    );
  });

  it("names the system-admin requirement on 403", async () => {
    const client = fakeClient();
    client.listSiteHosts.mockRejectedValue(
      new ApiError(403, {
        code: "system_admin_required",
        message: "Nein.",
        requestId: "r",
      }),
    );
    renderTab(client);
    expect(await screen.findByText("Nur für System-Admins")).toBeTruthy();
  });
});
