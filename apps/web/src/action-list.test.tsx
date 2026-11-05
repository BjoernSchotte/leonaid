import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type {
  CharityActionSummaryResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { ActionListPage, resetCommandPaletteState } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

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
  resetCommandPaletteState();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/admin/actions");
  vi.restoreAllMocks();
});

function action(
  id: string,
  name: string,
  overrides: Partial<CharityActionSummaryResponse> = {},
): CharityActionSummaryResponse {
  return {
    endsOn: "2026-12-20",
    goal: { actualValue: "0", currency: "EUR", goalValue: "1200", unit: null },
    id,
    leadNames: ["Klara Kern"],
    name,
    startsOn: "2026-11-01",
    status: "active",
    templateName: "Krapfentaxi",
    ...overrides,
  };
}

const items = [
  action("a1", "Krapfentaxi 2026"),
  action("a2", "Lions Open", {
    status: "draft",
    templateName: null,
    leadNames: [],
    goal: { actualValue: "0", currency: null, goalValue: null, unit: null },
  }),
  action("a3", "Krapfentaxi 2025", {
    status: "archived",
    startsOn: "2025-11-01",
    endsOn: "2025-12-20",
  }),
];

function renderList(listCharityActions = vi.fn(async () => ({ items }))) {
  const client = { listCharityActions } as unknown as LeonAidApiClient;
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ToastProvider>
        <HotkeyProvider>
          <ActionListPage client={client} />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return listCharityActions;
}

describe("Aktionen verwalten (prototype CampaignList)", () => {
  it("lists running and planned actions grouped by status, linking each", async () => {
    renderList();
    expect(
      await screen.findByRole("heading", { name: "Aktionen", level: 1 }),
    ).toBeTruthy();
    const running = await screen.findByText("Krapfentaxi 2026");
    expect(running.closest("a")?.getAttribute("href")).toBe(
      "/admin/actions/a1",
    );
    const row = running.closest("li");
    expect(row?.textContent).toContain("Leitung Klara Kern");
    expect(row?.textContent).toMatch(/1\.200,00\s€/);
    expect(screen.getByText("Lions Open")).toBeTruthy();
    // The archived action is only in "Archiv" and "Alle".
    expect(screen.queryByText("Krapfentaxi 2025")).toBeNull();
    for (const label of ["Laufend und geplant", "Alle", "Archiv"]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });

  it("shows the archive view", async () => {
    renderList();
    await screen.findByText("Krapfentaxi 2026");
    fireEvent.click(screen.getByRole("button", { name: "Archiv" }));
    expect(await screen.findByText("Krapfentaxi 2025")).toBeTruthy();
    expect(screen.queryByText("Krapfentaxi 2026")).toBeNull();
  });

  it("offers creating an action", async () => {
    renderList();
    await screen.findByText("Krapfentaxi 2026");
    const header = screen.getByRole("heading", { name: "Aktionen", level: 1 })
      .parentElement!.parentElement!;
    expect(
      within(header).getByRole("button", { name: /Aktion anlegen/ }),
    ).toBeTruthy();
  });

  it("shows the error state with a retry", async () => {
    const list = renderList(
      vi.fn(async () => {
        throw new Error("offline");
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Erneut/ }));
    expect(list).toHaveBeenCalledTimes(2);
  });
});
