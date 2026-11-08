import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it } from "vitest";

import {
  type ActivityFeedItemResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { ActivityFeedPage } from "../../../packages/features/src/activity-feed/activity-feed";

const itemId = "30000000-0000-4000-8000-000000000001";

function feedItem(
  overrides: Partial<ActivityFeedItemResponse> = {},
): ActivityFeedItemResponse {
  return {
    actionId: "20000000-0000-4000-8000-000000000001",
    actionName: "Krapfentaxi 2026",
    commitmentId: "50000000-0000-4000-8000-000000000001",
    currency: "EUR",
    eventType: "public_order_received",
    id: itemId,
    isRead: false,
    nextActionHref: "/app/sponsors?contact=1",
    nextActionLabel: "Kontakt und Bestellung abstimmen",
    occurredAt: "2026-11-06T08:00:00Z",
    partyDisplayName: "Doppelkontakt AG",
    partyId: "40000000-0000-4000-8000-000000000003",
    partyKind: "company",
    publicReference: "KT-0001",
    quantities: [{ quantity: 2, unit: "box" }],
    readAt: null,
    totalBoxes: 2,
    totalMinor: 2400,
    totalPieces: 0,
    ...overrides,
  };
}

interface SentRequest {
  readonly url: string;
  readonly init: RequestInit;
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}

/** A real API client whose transport answers like the feed endpoints. */
function feedClient(sent: SentRequest[]) {
  return new LeonAidApiClient("", async (input, init = {}) => {
    const url = String(input);
    sent.push({ url, init });
    if (init.method === "PATCH") {
      return json({
        ...feedItem(),
        isRead: true,
        readAt: "2026-11-06T09:00:00Z",
      });
    }
    return json({
      items: [feedItem()],
      limit: 50,
      offset: 0,
      total: 1,
      unreadCount: 1,
    });
  });
}

// jsdom cannot navigate; stop the link's default action after React ran.
function blockNavigation(event: MouseEvent) {
  event.preventDefault();
}

afterEach(() => {
  document.removeEventListener("click", blockNavigation);
});

describe("activity feed next action", () => {
  it("marks the entry read with a request that survives the page navigation", async () => {
    document.addEventListener("click", blockNavigation);
    const sent: SentRequest[] = [];
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <HotkeyProvider>
          <ToastProvider>
            <ActivityFeedPage client={feedClient(sent)} surface="pwa" />
          </ToastProvider>
        </HotkeyProvider>
      </QueryClientProvider>,
    );

    const link = await screen.findByTestId("activity-feed-next-action");
    fireEvent.click(link);

    await waitFor(() =>
      expect(sent.filter(({ init }) => init.method === "PATCH")).toHaveLength(
        1,
      ),
    );
    const patch = sent.find(({ init }) => init.method === "PATCH")!;
    expect(patch.url).toBe(`/api/v1/activity-feed/${itemId}`);
    expect(JSON.parse(String(patch.init.body))).toEqual({ read: true });
    // A full-page navigation aborts a normal fetch mid-body (API: 400).
    expect(patch.init.keepalive).toBe(true);
  });
});

const secondId = "30000000-0000-4000-8000-000000000002";

/** Two unread entries; reads and mark-all change what the next GET returns. */
function keyboardClient(sent: SentRequest[]) {
  const read = new Set<string>();
  const items = () =>
    [
      feedItem(),
      feedItem({ id: secondId, partyDisplayName: "Musterwerk GmbH" }),
    ].map((item) => ({ ...item, isRead: read.has(item.id) }));
  return new LeonAidApiClient("", async (input, init = {}) => {
    const url = String(input);
    sent.push({ url, init });
    if (init.method === "PATCH") {
      const id = url.split("/").at(-1)!;
      read.add(id);
      return json(items().find((item) => item.id === id));
    }
    if (init.method === "POST") {
      const updated = items().filter((item) => !item.isRead).length;
      items().forEach((item) => read.add(item.id));
      return json({ updated });
    }
    const all = items();
    return json({
      items: all,
      limit: 50,
      offset: 0,
      total: all.length,
      unreadCount: all.filter((item) => !item.isRead).length,
    });
  });
}

function press(key: string, shiftKey = false) {
  act(() => {
    (document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent("keydown", {
        key,
        shiftKey,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
}

describe("activity feed keyboard and a11y", () => {
  it("moves with j, reads with u, marks all with Shift+U and passes axe", async () => {
    const sent: SentRequest[] = [];
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <HotkeyProvider>
          <ToastProvider>
            <ActivityFeedPage client={keyboardClient(sent)} surface="web" />
          </ToastProvider>
        </HotkeyProvider>
      </QueryClientProvider>,
    );
    const links = await screen.findAllByTestId("activity-feed-next-action");
    expect(links).toHaveLength(2);
    // jsdom has no layout, so axe skips colour contrast here.
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations.map((violation) => violation.id)).toEqual([]);

    press("j");
    expect(document.activeElement).toBe(links[0]);
    press("j");
    expect(document.activeElement).toBe(links[1]);
    expect(links[1]!.tabIndex).toBe(0);
    expect(links[0]!.tabIndex).toBe(-1);

    press("u");
    await waitFor(() =>
      expect(screen.getByTestId("activity-feed-unread-count").textContent).toBe(
        "1 ungelesen",
      ),
    );
    const patch = sent.find(({ init }) => init.method === "PATCH")!;
    expect(patch.url).toBe(`/api/v1/activity-feed/${secondId}`);
    expect(JSON.parse(String(patch.init.body))).toEqual({ read: true });

    const markAll = screen.getByRole("button", {
      name: /Alle als gelesen markieren/,
    }) as HTMLButtonElement;
    expect(markAll.disabled).toBe(false);
    press("U", true);
    await waitFor(() => expect(markAll.disabled).toBe(true));
    expect(screen.getByTestId("activity-feed-unread-count").textContent).toBe(
      "Alles gelesen",
    );
    expect(
      sent.filter(
        ({ init, url }) =>
          init.method === "POST" && url === "/api/v1/activity-feed/read",
      ),
    ).toHaveLength(1);
    // Shift+U with nothing unread sends nothing more.
    press("U", true);
    expect(sent.filter(({ init }) => init.method === "POST")).toHaveLength(1);
  });
});
