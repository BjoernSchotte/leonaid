// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Bell, Home, ListChecks, Plus, Truck, Users } from "lucide-react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { installDialogPolyfill } from "../test-utils/dialog-polyfill";
import type { ReactNode } from "react";

import { useLeaveGuard } from "./leave-guard";
import { MobileShell, type MobileShellProps } from "./mobile-shell";

beforeAll(installDialogPolyfill);
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

const tabs: MobileShellProps["tabs"] = [
  {
    key: "overview-pwa",
    label: "Start",
    href: "/app/",
    icon: Home,
    shortcut: "1",
  },
  {
    key: "sponsors",
    label: "Sponsoren",
    href: "/app/sponsors",
    icon: Users,
    shortcut: "2",
  },
  {
    key: "sponsor-new",
    label: "Neu",
    href: "/app/sponsors?view=new",
    icon: Plus,
    primary: true,
    shortcut: "3",
  },
  // No "4": the follow-up tab is missing for this account.
  {
    key: "activities",
    label: "Neues",
    href: "/app/activities",
    icon: Bell,
    shortcut: "5",
  },
];

function renderShell(
  overrides: Partial<MobileShellProps> = {},
  extra: ReactNode = null,
) {
  const onLogout = vi.fn();
  render(
    <MobileShell
      active="sponsors"
      campaign="Krapfentaxi 2026"
      menuItems={[
        {
          key: "tasks",
          label: "Aufgaben",
          icon: ListChecks,
          href: "/app/tasks",
          current: false,
        },
        { key: "delivery", label: "Auslieferung", icon: Truck, href: null },
      ]}
      offline={false}
      onLogout={onLogout}
      person="Anna Akquise"
      role="Akquisiteur"
      tabs={tabs}
      {...overrides}
    >
      <h1>Meine Sponsoren</h1>
      <input aria-label="Straße" />
      <input aria-label="Aufgaben suchen" type="search" />
      <form role="search">
        <input aria-label="Material filtern" />
      </form>
      <div data-leave-guard="off">
        <input aria-label="Notizfilter" />
      </div>
      {extra}
    </MobileShell>,
  );
  return { onLogout };
}

describe("MobileShell", () => {
  it("renders the app bar with campaign, role and person", () => {
    renderShell();
    const bar = screen.getByRole("banner");
    expect(bar.className).toBe("pwa-bar");
    expect(screen.getByTestId("current-action").textContent).toBe(
      "Krapfentaxi 2026",
    );
    expect(bar.querySelector(".pwa-campaign-sub")?.textContent).toBe(
      "Akquisiteur · Anna Akquise",
    );
    expect(screen.getByTestId("display-name").textContent).toBe("Anna Akquise");
    expect(screen.getByRole("main").id).toBe("main");
    expect(screen.getByRole("link", { name: "Zum Inhalt springen" })).toBe(
      document.querySelector(".pwa-skip-link"),
    );
    expect(
      document.querySelector(".pwa-stage")?.getAttribute("data-zone"),
    ).toBe("pwa");
  });

  it("marks the active tab and the filled Neu tab", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "App-Navigation" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Start",
      "Sponsoren",
      "Neu",
      "Neues",
    ]);
    const current = within(nav).getByRole("link", { name: "Sponsoren" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(current.className).toContain("is-active");
    expect(current.getAttribute("href")).toBe("/app/sponsors");
    const create = within(nav).getByRole("link", { name: "Neu" });
    expect(create.className).toContain("is-new");
    expect(create.getAttribute("aria-current")).toBeNull();
    expect(create.querySelector("svg")?.getAttribute("width")).toBe("22");
  });

  it("omits the tab bar when no tab is granted", () => {
    renderShell({ tabs: [], active: null });
    expect(
      screen.queryByRole("navigation", { name: "App-Navigation" }),
    ).toBeNull();
  });

  it("shows the offline banner and the gold network state", () => {
    renderShell({ offline: true });
    const banner = screen.getByTestId("offline-banner");
    expect(banner.parentElement?.getAttribute("role")).toBe("status");
    expect(banner.textContent).toContain("Du bist offline.");
    expect(banner.textContent).toContain(
      "LeonAid speichert keine Änderungen im Hintergrund.",
    );
    const net = screen.getByRole("img", { name: "Offline" });
    expect(net.className).toContain("is-offline");
    // The page stays rendered under the banner.
    expect(
      screen.getByRole("heading", { name: "Meine Sponsoren" }),
    ).toBeTruthy();
  });

  it("hides the offline banner while online", () => {
    renderShell();
    expect(screen.queryByTestId("offline-banner")).toBeNull();
    // The live region stays mounted (empty), so a later banner is announced.
    const region = document.querySelector(".pwa-offline-region");
    expect(region?.getAttribute("role")).toBe("status");
    expect(region?.textContent).toBe("");
    expect(screen.getByRole("img", { name: "Online" }).className).toBe(
      "pwa-net",
    );
  });

  it("offers the admin app and the start area to members with both roles", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onDefault = vi.fn();
    renderShell({
      surfaces: {
        switchTo: { label: "Zur Verwaltung", href: "/admin/" },
        startAreas: [
          { label: "Akquise-App als Startbereich verwenden", onSelect },
          { label: "Standard-Startbereich verwenden", onSelect: onDefault },
        ],
      },
    });
    await user.click(screen.getByRole("button", { name: "Mehr" }));
    const sheet = screen.getByRole("dialog", { name: "Mehr" });
    const surfaces = within(sheet).getByTestId("pwa-surfaces");
    expect(
      within(surfaces)
        .getByRole("link", { name: "Zur Verwaltung" })
        .getAttribute("href"),
    ).toBe("/admin/");
    await user.click(
      within(surfaces).getByRole("button", {
        name: "Akquise-App als Startbereich verwenden",
      }),
    );
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onDefault).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Mehr" }));
    await user.click(
      within(
        within(screen.getByRole("dialog", { name: "Mehr" })).getByTestId(
          "pwa-surfaces",
        ),
      ).getByRole("button", { name: "Standard-Startbereich verwenden" }),
    );
    expect(onDefault).toHaveBeenCalledTimes(1);
  });

  it("shows no Bereiche section without a second app", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByRole("button", { name: "Mehr" }));
    expect(screen.queryByTestId("pwa-surfaces")).toBeNull();
  });

  it("opens the Mehr sheet with areas, theme and sign-out", async () => {
    const user = userEvent.setup();
    const { onLogout } = renderShell();
    const opener = screen.getByRole("button", { name: "Mehr" });
    expect(opener.getAttribute("aria-haspopup")).toBe("dialog");
    await user.click(opener);
    const sheet = screen.getByRole("dialog", { name: "Mehr" });
    expect((sheet as HTMLDialogElement).open).toBe(true);
    const areas = within(sheet).getByRole("navigation", {
      name: "Weitere Bereiche",
    });
    expect(
      within(areas)
        .getByRole("link", { name: "Aufgaben" })
        .getAttribute("href"),
    ).toBe("/app/tasks");
    const delivery = areas.querySelector('[data-nav-key="delivery"]');
    expect(delivery?.getAttribute("aria-disabled")).toBe("true");
    expect(delivery?.textContent).toContain("In Aufbau");

    await user.click(within(sheet).getByRole("button", { name: "Dunkel" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("leonaid.theme")).toBe("dark");
    expect(
      within(sheet)
        .getByRole("button", { name: "Dunkel" })
        .getAttribute("aria-pressed"),
    ).toBe("true");

    await user.click(within(sheet).getByRole("button", { name: "Abmelden" }));
    expect(onLogout).toHaveBeenCalledTimes(1);

    await user.click(within(sheet).getByRole("button", { name: "Schließen" }));
    expect((sheet as HTMLDialogElement).open).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("lists the tab shortcuts in the Du shortcut help", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.keyboard("?");
    const help = screen.getByRole("dialog", { name: "Tastenkürzel" });
    expect(help.textContent).toContain("App: Start");
    expect(help.textContent).toContain("App: Neues");
    expect(help.textContent).toContain("Hell/Dunkel wechseln");
    expect(help.textContent).toContain("während du in ein Feld schreibst");
  });

  it("toggles light and dark with shift+t", async () => {
    const user = userEvent.setup();
    document.documentElement.dataset.theme = "light";
    renderShell();
    await user.keyboard("{Shift>}T{/Shift}");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("binds fixed digits per tab and leaves missing slots unbound", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.keyboard("?");
    const help = screen.getByRole("dialog", { name: "Tastenkürzel" });
    const keys = [...help.querySelectorAll(".kbd")].map(
      (key) => key.textContent,
    );
    expect(keys).toEqual(expect.arrayContaining(["1", "2", "3", "5"]));
    expect(keys).not.toContain("4");
  });

  function clickStart(init: MouseEventInit = {}) {
    const nav = screen.getByRole("navigation", { name: "App-Navigation" });
    const event = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      ...init,
    });
    act(() => {
      within(nav).getByRole("link", { name: "Start" }).dispatchEvent(event);
    });
    return event;
  }

  function beforeUnloadPrevented() {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  }

  it("asks once, in the app, before a tab drops typed input", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm");
    renderShell();
    // Nothing typed: the tab just navigates.
    expect(clickStart().defaultPrevented).toBe(false);
    expect(screen.queryByRole("alertdialog")).toBeNull();

    await user.type(screen.getByRole("textbox", { name: "Straße" }), "Weg 7");
    expect(clickStart().defaultPrevented).toBe(true);
    const question = screen.getByRole("alertdialog", {
      name: "Seite wechseln?",
    });
    expect(question.textContent).toContain(
      "Du hast Eingaben, die noch nicht gespeichert sind.",
    );
    expect(confirm).not.toHaveBeenCalled();
    await user.click(
      within(question).getByRole("button", { name: "Abbrechen" }),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Straße" })).toHaveProperty(
      "value",
      "Weg 7",
    );

    // A cleared field no longer counts.
    await user.clear(screen.getByRole("textbox", { name: "Straße" }));
    expect(clickStart().defaultPrevented).toBe(false);
    confirm.mockRestore();
  });

  it("stops counting a field once its form opts out (saved)", async () => {
    const user = userEvent.setup();
    renderShell();
    const field = screen.getByRole("textbox", { name: "Straße" });
    await user.type(field, "Weg 7");
    field.setAttribute("data-leave-guard", "off");
    expect(clickStart().defaultPrevented).toBe(false);
  });

  it("asks for pages registered with useLeaveGuard, then keeps them silent", async () => {
    const user = userEvent.setup();
    function DirtyEditor() {
      useLeaveGuard(true);
      return null;
    }
    renderShell({}, <DirtyEditor />);
    // Reload or close still get the browser's own question.
    expect(beforeUnloadPrevented()).toBe(true);
    expect(clickStart().defaultPrevented).toBe(true);
    const question = screen.getByRole("alertdialog", {
      name: "Seite wechseln?",
    });
    await user.click(
      within(question).getByRole("button", {
        name: "Verwerfen und wechseln",
      }),
    );
    // Answered in the app: no second, browser-side question.
    expect(beforeUnloadPrevented()).toBe(false);
  });

  it("does not ask for search and filter fields or opted-out fields", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.type(
      screen.getByRole("searchbox", { name: "Aufgaben suchen" }),
      "Detail",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Material filtern" }),
      "Flyer",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Notizfilter" }),
      "Plan",
    );
    expect(clickStart().defaultPrevented).toBe(false);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("does not ask for a new tab or window", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.type(screen.getByRole("textbox", { name: "Straße" }), "Weg 7");
    for (const init of [
      { ctrlKey: true },
      { metaKey: true },
      { shiftKey: true },
      { button: 1 },
    ]) {
      expect(clickStart(init).defaultPrevented).toBe(false);
    }
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("asks for a digit key too", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.type(screen.getByRole("textbox", { name: "Straße" }), "Weg 7");
    await user.click(screen.getByRole("heading", { name: "Meine Sponsoren" }));
    await user.keyboard("1");
    expect(
      screen.getByRole("alertdialog", { name: "Seite wechseln?" }),
    ).toBeTruthy();
  });
});
