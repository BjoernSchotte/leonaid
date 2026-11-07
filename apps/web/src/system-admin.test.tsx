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

import type {
  CurrentIdentityResponse,
  FeatureFlagAdminResponse,
  LeonAidApiClient,
  OperationsOverviewResponse,
  PrivacySubjectReportResponse,
} from "@leonaid/api-client";
import {
  FeatureFlagProvider,
  SystemPage,
  resetCommandPaletteState,
  systemSection,
  waitedFor,
} from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

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
  cleanup();
  resetCommandPaletteState();
  window.history.replaceState(null, "", "/admin/system");
  vi.restoreAllMocks();
});

const overview: OperationsOverviewResponse = {
  api: { averageLatencyMs: 12, errors: 0, requests: 40 },
  dependencies: [
    {
      dependency: "twenty",
      errorCode: null,
      latencyMs: 30,
      requestId: "r1",
      status: "ready",
    },
    {
      dependency: "mail",
      errorCode: "smtp_down",
      latencyMs: 900,
      requestId: "r2",
      status: "unavailable",
    },
  ],
  failedJobs: [
    {
      aggregateId: "a1",
      aggregateType: "invoice",
      attempts: 5,
      eventType: "invoice.mail",
      failedAt: "2026-11-03T08:00:00Z",
      id: "job-1",
      lastErrorCode: "smtp_timeout",
      manualRetryCount: 0,
    },
  ],
  generatedAt: "2026-11-03T09:00:00Z",
  login: { challengesLast24h: 3, completionsLast24h: 3, failuresLast24h: 0 },
  mail: { completed: 3, deadLetter: 0, pending: 0, processing: 0 },
  monitoring: { activeAlerts: [], checks: [], status: "ready" },
  outbox: { completed: 10, deadLetter: 1, pending: 2, processing: 0 },
  requestId: "req-overview",
  siteHosts: [
    {
      failedChecks: 2,
      hostname: "lionsopen.de",
      lastCheckResult: "Der Name ist im DNS nicht auflösbar.",
      lastCheckedAt: "2026-11-03T03:00:00Z",
      liveBindings: 1,
      status: "active",
    },
  ],
};

const flag: FeatureFlagAdminResponse = {
  clientSafe: true,
  defaultEnabled: false,
  description: "Zeigt einen Hinweis.",
  effect: "Alle sehen den Hinweis.",
  enabled: false,
  key: "admin.preview_notice",
  revision: 3,
  title: "Vorschau-Hinweis",
  updatedAt: "2026-11-02T08:00:00Z",
  updatedByUserId: null,
};

const subject = "ida@example.invalid";
const report: PrivacySubjectReportResponse = {
  consents: [],
  crmDeletionStatus: "pending_manual_review",
  found: true,
  generatedAt: "2026-11-03T09:00:00Z",
  openLegalDecisions: [],
  orderDeliveries: [],
  references: [
    {
      actionId: null,
      id: "c1",
      label: "KT26-0002",
      referenceType: "invoice",
      status: "issued",
    },
  ],
  retention: {
    auditDays: 3650,
    commitmentDays: 3650,
    consentEvidenceDays: 3650,
    contactDays: 730,
    invoiceDays: 3650,
    legalConfigurationVersion: 1,
    legalConfigurationVersionId: "v1",
  },
  subjectEmail: subject,
  suppressions: [],
};

function fakeClient() {
  return {
    getOperationsOverview: vi.fn(async () => overview),
    getPlatformInformation: vi.fn(async () => ({
      apiVersion: "v1",
      release: "2026.11.1",
      service: "leonaid",
    })),
    retryOperationalJob: vi.fn(async () => ({})),
    getPilotDailyReport: vi.fn(),
    runSupportProbe: vi.fn(),
    getSupportRequestDiagnostic: vi.fn(),
    listFeatureFlags: vi.fn(async () => ({ flags: [flag] })),
    updateFeatureFlag: vi.fn(async () => ({
      ...flag,
      enabled: true,
      revision: 4,
    })),
    getFeatureFlagSystemStatus: vi.fn(),
    getFeatureFlagEvaluations: vi.fn(async () => ({ flags: [] })),
    lookupPrivacySubject: vi.fn(async () => report),
    exportPrivacySubject: vi.fn(),
    revokePrivacyConsent: vi.fn(),
    erasePrivacySubject: vi.fn(async () => ({
      anonymizedCommitments: 1,
      caseId: "case-1",
      clearedActivityNotes: 0,
      clearedReminders: 0,
      completedAt: "2026-11-03T09:05:00Z",
      openDecisions: [],
      retainedDocumentIds: [],
      retainedInvoiceIds: ["inv-1"],
      retention: report.retention,
      retentionReasons: [],
      revokedConsents: 0,
      status: "completed_with_retention",
      subjectHash: "h",
    })),
  };
}

const identity = {
  actionMemberships: [],
  displayName: "Simone System",
  globalRoles: ["system_admin"],
  installation: { clubName: "Lions Club Musterstadt" },
  navigation: [],
  roleLabels: [],
  userId: "10000000-0000-4000-8000-000000000001",
} as unknown as CurrentIdentityResponse;

let queryClient: QueryClient;

function renderPage(url: string) {
  window.history.replaceState(null, "", url);
  const client = fakeClient();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <HotkeyProvider>
          <FeatureFlagProvider
            client={client as unknown as LeonAidApiClient}
            identity={identity}
            surface="web"
          >
            <SystemPage
              client={client as unknown as LeonAidApiClient}
              identity={identity}
            />
          </FeatureFlagProvider>
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return client;
}

describe("systemSection", () => {
  it("maps each URL to its tab", () => {
    expect(systemSection("/admin/system")).toBe("operations");
    expect(systemSection("/admin/system/jobs/")).toBe("jobs");
    expect(systemSection("/admin/system/flags")).toBe("flags");
    expect(systemSection("/admin/privacy")).toBe("privacy");
    expect(systemSection("/admin/system/ui")).toBe("operations");
  });
});

describe("waitedFor", () => {
  it("rounds the wait to a readable unit", () => {
    expect(waitedFor(12.7)).toBe("12 s");
    expect(waitedFor(300)).toBe("5 min");
    expect(waitedFor(10_800)).toBe("3 h");
  });
});

describe("SystemPage", () => {
  it("switches tabs with the URL and shows the failed-job count", async () => {
    renderPage("/admin/system");
    expect(
      await screen.findByText(
        "Version 2026.11.1 · eine Installation für Lions Club Musterstadt",
      ),
    ).toBeTruthy();
    const hosts = await screen.findByTestId("operations-site-hosts");
    expect(hosts.textContent).toContain("lionsopen.de");
    expect(hosts.textContent).toContain("2 Prüfung(en) fehlgeschlagen");
    expect(hosts.textContent).toContain("nicht auflösbar");
    const jobsTab = await screen.findByRole("tab", {
      name: /Hintergrundaufgaben/,
    });
    await waitFor(() => expect(jobsTab.textContent).toContain("1"));

    fireEvent.click(jobsTab);
    expect(window.location.pathname).toBe("/admin/system/jobs");
    expect(await screen.findByTestId("operations-jobs")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Datenschutz" }));
    expect(window.location.pathname).toBe("/admin/privacy");
    expect(screen.getByText("Nach einer Person suchen")).toBeTruthy();

    // Tabs replace the history entry (prototype behaviour); Back or
    // Forward still re-renders the tab of the current URL.
    window.history.pushState(null, "", "/admin/system/jobs");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByTestId("operations-jobs")).toBeTruthy();
  });

  it("retries a failed job only after the confirmation", async () => {
    const client = renderPage("/admin/system/jobs");
    const queue = await screen.findByTestId("operations-outbox");
    expect(queue.textContent).toContain("Wartend2");
    expect(queue.textContent).toContain("Keine fällige Aufgabe wartet");
    fireEvent.click(await screen.findByTestId("retry-job-job-1"));
    expect(client.retryOperationalJob).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: /erneut versuchen/i }),
    );
    await waitFor(() =>
      expect(client.retryOperationalJob).toHaveBeenCalledWith("job-1"),
    );
  });

  it("keeps the last overview and an open dialog when a refresh fails", async () => {
    const client = renderPage("/admin/system/jobs");
    fireEvent.click(await screen.findByTestId("retry-job-job-1"));
    const dialog = await screen.findByRole("alertdialog");
    client.getOperationsOverview.mockRejectedValueOnce(new Error("offline"));
    await act(() =>
      queryClient.refetchQueries({ queryKey: ["operations-overview"] }),
    );
    expect(
      await screen.findByText(
        "Betriebsstatus konnte nicht aktualisiert werden",
      ),
    ).toBeTruthy();
    expect(screen.getByTestId("retry-job-job-1")).toBeTruthy();
    expect(dialog.isConnected).toBe(true);
    expect(screen.queryByText("Betriebsstatus nicht erreichbar")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Jetzt neu laden" }));
    await waitFor(() =>
      expect(
        screen.queryByText("Betriebsstatus konnte nicht aktualisiert werden"),
      ).toBeNull(),
    );
  });

  it("switches a function only after the confirmation", async () => {
    const client = renderPage("/admin/system/flags");
    const toggle = (await screen.findByTestId(
      "feature-switch-admin.preview_notice",
    )) as HTMLInputElement;
    fireEvent.click(toggle);
    expect(client.updateFeatureFlag).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Einschalten" }),
    );
    await waitFor(() => expect(client.updateFeatureFlag).toHaveBeenCalled());
  });

  it("anonymizes only after the address is typed again", async () => {
    const client = renderPage("/admin/privacy");
    fireEvent.change(screen.getByTestId("privacy-email"), {
      target: { value: ` ${subject.toUpperCase()} ` },
    });
    fireEvent.click(screen.getByRole("button", { name: "Nachweise suchen" }));
    await waitFor(() =>
      expect(client.lookupPrivacySubject).toHaveBeenCalledWith({
        email: subject,
      }),
    );
    expect(
      (await screen.findByTestId("privacy-summary")).textContent,
    ).toContain(subject);

    fireEvent.click(screen.getByRole("button", { name: /Anonymisieren/ }));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Operative Daten anonymisieren?",
    });
    const confirm = within(dialog).getByRole("button", {
      name: "Verbindlich anonymisieren",
    }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(
      within(dialog).getByTestId("privacy-erasure-confirmation"),
      {
        target: { value: "ida@example" },
      },
    );
    expect(confirm.disabled).toBe(true);
    fireEvent.change(
      within(dialog).getByTestId("privacy-erasure-confirmation"),
      {
        target: { value: subject },
      },
    );
    expect(confirm.disabled).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(client.erasePrivacySubject).toHaveBeenCalledWith({
        confirmation: subject,
        email: subject,
      }),
    );
    expect(
      await screen.findByText("Anonymisierung abgeschlossen"),
    ).toBeTruthy();
  });

  it("rejects an incomplete address without asking the server", async () => {
    const client = renderPage("/admin/privacy");
    fireEvent.change(screen.getByTestId("privacy-email"), {
      target: { value: "ida@" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Nachweise suchen" }));
    expect(await screen.findByText(/vollständige E-Mail-Adresse/)).toBeTruthy();
    expect(client.lookupPrivacySubject).not.toHaveBeenCalled();
  });

  it("erases the found subject even after the search field changed", async () => {
    const client = renderPage("/admin/privacy");
    fireEvent.change(screen.getByTestId("privacy-email"), {
      target: { value: subject },
    });
    fireEvent.click(screen.getByRole("button", { name: "Nachweise suchen" }));
    await screen.findByTestId("privacy-summary");
    // The admin starts typing the next request; the found subject stays.
    fireEvent.change(screen.getByTestId("privacy-email"), {
      target: { value: "other@example.invalid" },
    });
    // The re-lookup after the erasure fails: the erasure still succeeded.
    client.lookupPrivacySubject.mockRejectedValueOnce(new Error("offline"));

    fireEvent.click(screen.getByRole("button", { name: /Anonymisieren/ }));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Operative Daten anonymisieren?",
    });
    fireEvent.change(
      within(dialog).getByTestId("privacy-erasure-confirmation"),
      { target: { value: subject } },
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Verbindlich anonymisieren" }),
    );
    await waitFor(() =>
      expect(client.erasePrivacySubject).toHaveBeenCalledWith({
        confirmation: subject,
        email: subject,
      }),
    );
    expect(
      await screen.findByText("Anonymisierung abgeschlossen"),
    ).toBeTruthy();
    await waitFor(() =>
      expect(client.lookupPrivacySubject).toHaveBeenLastCalledWith({
        email: subject,
      }),
    );
    expect(screen.queryByText("Vorgang nicht abgeschlossen")).toBeNull();
  });
});
