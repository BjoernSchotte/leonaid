import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  CurrentIdentityResponse,
  DashboardDonationResponse,
  DashboardResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { RoleDashboardPage } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

const actionId = "20000000-0000-4000-8000-000000000001";

afterEach(() => {
  cleanup();
});

const identity = {
  actionMemberships: [
    {
      actionId,
      actionName: "Krapfentaxi 2026",
      role: "charity_admin",
      roleLabel: "Charity-Admin",
    },
  ],
  displayName: "Klara Kern",
  donationActions: [{ actionId, actionName: "Krapfentaxi 2026" }],
  globalRoles: [],
  navigation: [],
  roleLabels: [],
} as unknown as CurrentIdentityResponse;

function dashboard(donations: DashboardDonationResponse): DashboardResponse {
  return {
    acquirer: null,
    actionId,
    actionName: "Krapfentaxi 2026",
    beneficiaries: ["Kinderhafen Beispielstadt"],
    charityAdmin: {
      commitments: {
        activeTotal: 2,
        activeTotalMinor: 14_400,
        cancelled: 0,
        confirmed: 1,
        currency: "EUR",
        draft: 0,
        invoiced: 1,
        quantities: [],
        reviewReady: 0,
        total: 2,
        totalBoxes: 4,
        totalPieces: 96,
      },
      delivery: { enabled: false, windows: [] },
      donations,
      invoices: {
        cancelled: 0,
        currency: "EUR",
        deliveryFailed: 0,
        invoicedAmountMinor: 7_200,
        issued: 1,
        open: 1,
        openAmountMinor: 7_200,
        overdue: 0,
        overdueAmountMinor: 0,
        paid: 0,
        sent: 0,
        total: 1,
      },
      orderValueWeeks: [],
      pipeline: {
        committed: 1,
        contacted: 0,
        declined: 0,
        handedOver: 0,
        open: 1,
        total: 2,
      },
    },
    generatedAt: "2026-11-10T10:00:00Z",
    goal: {
      actualValue: "144.00",
      configured: true,
      currency: "EUR",
      progressBasisPoints: 1_440,
      targetValue: "1000.00",
      unit: null,
    },
    metricDefinitions: [],
  };
}

async function renderDashboard(donations: DashboardDonationResponse) {
  window.history.replaceState(null, "", `/admin/?action=${actionId}`);
  const client = {
    getActionDashboard: vi.fn(async () => dashboard(donations)),
    listInboxCases: vi.fn(async () => ({ items: [] })),
  };
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ToastProvider>
        <HotkeyProvider>
          <RoleDashboardPage
            client={client as unknown as LeonAidApiClient}
            identity={identity}
            mode="charity_admin"
          />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findByText("Weitere Kennzahlen");
}

describe("donation figure of the action overview", () => {
  it("shows what arrived and what is pledged and open, next to the order figures", async () => {
    await renderDashboard({
      currency: "EUR",
      enabled: true,
      paid: 1,
      pledged: 2,
      pledgedOpenMinor: 12_500,
      receivedMinor: 6_000,
    });
    const figure = screen.getByTestId("dashboard-donations");
    expect(figure.textContent?.replace(/\s+/g, " ")).toContain(
      "Spenden60,00 €eingegangen · 125,00 € zugesagt, noch offen",
    );
    expect(figure.querySelector("a")?.getAttribute("href")).toBe(
      `/admin/donations?action=${actionId}`,
    );
  });

  it("is absent for an action without the donations capability", async () => {
    await renderDashboard({
      currency: "EUR",
      enabled: false,
      paid: 0,
      pledged: 0,
      pledgedOpenMinor: 0,
      receivedMinor: 0,
    });
    expect(screen.queryByTestId("dashboard-donations")).toBeNull();
  });
});
