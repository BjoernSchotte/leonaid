// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import {
  Flag,
  LayoutDashboard,
  ListChecks,
  ShoppingBasket,
} from "lucide-react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useHotkeys } from "../keyboard/use-hotkeys";
import {
  activeNavigationKey,
  mobilePrimaryItems,
  RailShell,
  type RailNavItem,
  type RailShellProps,
} from "./rail-shell";

const overview: RailNavItem = {
  key: "overview-web",
  label: "Übersicht",
  href: "/admin/",
  icon: LayoutDashboard,
  group: "Arbeit",
  goKey: "d",
};
const actions: RailNavItem = {
  key: "actions",
  label: "Aktionen",
  href: "/admin/actions",
  icon: Flag,
  group: "Arbeit",
  goKey: "a",
};
const orders: RailNavItem = {
  key: "orders",
  label: "Bestellungen",
  href: "/admin/orders",
  icon: ShoppingBasket,
  group: "Arbeit",
  goKey: "b",
};
const tasks: RailNavItem = {
  key: "tasks",
  label: "Aufgaben",
  href: "/admin/tasks",
  icon: ListChecks,
  group: "Module",
  goKey: "t",
};

function press(key: string, init: KeyboardEventInit = {}) {
  const target = document.activeElement ?? document.body;
  act(() => {
    target.dispatchEvent(
      new KeyboardEvent("keydown", {
        key,
        bubbles: true,
        cancelable: true,
        ...init,
      }),
    );
  });
}

function shell(props: Partial<RailShellProps> = {}) {
  const navigate = vi.fn();
  const onLogout = vi.fn();
  const result = render(
    <RailShell
      activeKey="orders"
      navigate={navigate}
      navigation={[overview, actions, orders, tasks]}
      onLogout={onLogout}
      user={{ name: "Klara Kern", role: "Charity-Admin" }}
      {...props}
    >
      {props.children ?? <p>Seite</p>}
    </RailShell>,
  );
  return { ...result, navigate, onLogout };
}

beforeEach(() => {
  // jsdom lacks what cmdk uses for the campaign menu.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  // jsdom has no matchMedia; the theme button only reads it.
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

describe("RailShell", () => {
  it("lists exactly the given items in their groups and marks the active one", () => {
    shell();
    const rail = screen.getByRole("navigation", { name: "Hauptnavigation" });
    expect(
      within(rail)
        .getAllByRole("heading")
        .map((heading) => heading.textContent),
    ).toEqual(["Arbeit", "Module"]);
    expect(
      within(rail)
        .getAllByRole("link")
        .map((link) => link.getAttribute("data-nav-key")),
    ).toEqual(["overview-web", "actions", "orders", "tasks"]);
    expect(
      within(rail).getByRole("link", { name: /Bestellungen/ }),
    ).toHaveProperty("ariaCurrent", "page");
    expect(
      within(rail)
        .getByRole("link", { name: /Aktionen/ })
        .getAttribute("aria-current"),
    ).toBeNull();
  });

  it("colours the shell and the topbar band with the active zone", () => {
    shell();
    expect(screen.getByTestId("rail-shell").dataset.zone).toBe("orders");
    expect(screen.getByTestId("topbar-zone").textContent).toBe("Bestellungen");
  });

  it("falls back to the overview zone when no item is active", () => {
    shell({ activeKey: undefined });
    expect(screen.getByTestId("rail-shell").dataset.zone).toBe("overview-web");
  });

  it("navigates with g and the zone letter for every item it shows", () => {
    const { navigate } = shell();
    for (const item of [overview, actions, orders, tasks]) {
      press("g");
      press(item.goKey!);
    }
    expect(navigate.mock.calls.map(([href]) => href)).toEqual([
      "/admin/",
      "/admin/actions",
      "/admin/orders",
      "/admin/tasks",
    ]);
  });

  it("has no g binding for an item the server did not return", () => {
    const { navigate } = shell({ navigation: [overview, orders] });
    press("g");
    press("t");
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.queryByText("Aufgaben")).toBeNull();
  });

  it("lets page bindings win over shell bindings, also after a shell update", () => {
    const pageRun = vi.fn();
    function Page() {
      useHotkeys([
        { keys: "g b", label: "Seite", group: "Seite", run: pageRun },
      ]);
      return <p>Seite</p>;
    }
    const { navigate, rerender } = shell({ children: <Page /> });
    press("g");
    press("b");
    expect(pageRun).toHaveBeenCalledTimes(1);

    // Identity refetch: new navigation array, same shell instance.
    rerender(
      <RailShell
        activeKey="orders"
        navigate={navigate}
        navigation={[overview, orders]}
        onLogout={() => undefined}
        user={{ name: "Klara Kern", role: "Charity-Admin" }}
      >
        <Page />
      </RailShell>,
    );
    press("g");
    press("b");
    expect(pageRun).toHaveBeenCalledTimes(2);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("lets a page that mounts after the shell win", () => {
    const pageRun = vi.fn();
    function Page() {
      useHotkeys([
        { keys: "g b", label: "Seite", group: "Seite", run: pageRun },
      ]);
      return null;
    }
    function Late() {
      const [ready, setReady] = useState(false);
      return ready ? (
        <Page />
      ) : (
        <button onClick={() => setReady(true)} type="button">
          laden
        </button>
      );
    }
    const { navigate } = shell({ children: <Late /> });
    fireEvent.click(screen.getByRole("button", { name: "laden" }));
    press("g");
    press("b");
    expect(pageRun).toHaveBeenCalledTimes(1);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("puts the skip link first in the tab order", () => {
    shell({ onOpenPalette: () => undefined });
    const focusable = screen
      .getByTestId("rail-shell")
      .querySelectorAll<HTMLElement>("a[href], button");
    expect(focusable[0]?.textContent).toBe("Zum Inhalt springen");
    expect(focusable[0]?.getAttribute("href")).toBe("#main-content");
    expect(document.getElementById("main-content")?.tagName).toBe("MAIN");
  });

  it("mounts the palette slot and opens it from every search entry", () => {
    const onOpenPalette = vi.fn();
    shell({ onOpenPalette, palette: <div data-testid="palette" /> });
    expect(screen.getByTestId("palette")).toBeTruthy();
    const entries = screen.getAllByRole("button", { name: /^Suchen/ });
    expect(entries).toHaveLength(2);
    for (const entry of entries) fireEvent.click(entry);
    fireEvent.click(screen.getByTestId("mobile-menu"));
    fireEvent.click(
      within(screen.getByTestId("mobile-sheet")).getByRole("button", {
        name: "Suchen und Befehle",
      }),
    );
    expect(onOpenPalette).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("mobile-sheet").hasAttribute("open")).toBe(false);
  });

  it("lets a page binding beat the palette slot's binding", () => {
    const paletteRun = vi.fn();
    const pageRun = vi.fn();
    function Palette() {
      useHotkeys([
        { keys: "/", label: "Suchen", group: "Allgemein", run: paletteRun },
      ]);
      return null;
    }
    function Page() {
      useHotkeys([{ keys: "/", label: "Liste", group: "Liste", run: pageRun }]);
      return null;
    }
    shell({ palette: <Palette />, children: <Page /> });
    press("/");
    expect(pageRun).toHaveBeenCalledTimes(1);
    expect(paletteRun).not.toHaveBeenCalled();
  });

  it("hides the search entries without a palette", () => {
    shell();
    expect(screen.queryByRole("button", { name: /Suchen/ })).toBeNull();
  });

  it("switches the campaign through the option menu", () => {
    const onSelect = vi.fn();
    shell({
      campaignSwitcher: {
        campaigns: [
          { id: "a1", name: "Krapfentaxi 2026" },
          { id: "a2", name: "Weihnachtsmarkt" },
        ],
        currentId: "a1",
        onSelect,
      },
    });
    expect(screen.getByTestId("current-action").textContent).toBe(
      "Krapfentaxi 2026",
    );
    fireEvent.click(screen.getByTestId("campaign-switcher"));
    fireEvent.click(screen.getByRole("option", { name: /Weihnachtsmarkt/ }));
    expect(onSelect).toHaveBeenCalledWith("a2");
  });

  it("shows the user and signs out", () => {
    const { onLogout } = shell();
    expect(screen.getByTestId("display-name").textContent).toBe("Klara Kern");
    expect(screen.getByTestId("roles").textContent).toBe("Charity-Admin");
    fireEvent.click(screen.getByTestId("logout"));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it("opens the Mehr sheet with every area and the sign-out", () => {
    const { onLogout } = shell();
    fireEvent.click(screen.getByTestId("mobile-menu"));
    const sheet = screen.getByTestId("mobile-sheet");
    expect(sheet.hasAttribute("open")).toBe(true);
    expect(
      within(sheet)
        .getAllByRole("link")
        .map((link) => link.getAttribute("data-nav-key")),
    ).toEqual(["overview-web", "actions", "orders", "tasks"]);
    fireEvent.click(within(sheet).getByRole("button", { name: "Abmelden" }));
    expect(onLogout).toHaveBeenCalledTimes(1);
    fireEvent.click(within(sheet).getByRole("button", { name: "Schließen" }));
    expect(sheet.hasAttribute("open")).toBe(false);
  });

  it("toggles light and dark with shift+t", () => {
    shell();
    press("T", { shiftKey: true });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("leonaid.theme")).toBe("dark");
    press("T", { shiftKey: true });
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("activeNavigationKey", () => {
  const items = [overview, actions, orders, tasks];

  it("matches the longest href prefix", () => {
    expect(activeNavigationKey(items, "/admin/orders")).toBe("orders");
    expect(activeNavigationKey(items, "/admin/actions/new")).toBe("actions");
    expect(activeNavigationKey(items, "/admin/tasks/")).toBe("tasks");
  });

  it("matches the overview only on its own path", () => {
    expect(activeNavigationKey(items, "/admin/")).toBe("overview-web");
    expect(activeNavigationKey(items, "/admin")).toBe("overview-web");
    expect(activeNavigationKey(items, "/admin/unknown")).toBeUndefined();
  });

  it("does not match a sibling that shares a prefix", () => {
    expect(activeNavigationKey(items, "/admin/ordersx")).toBeUndefined();
  });
});

describe("mobilePrimaryItems", () => {
  it("prefers overview, orders, invoices and tasks, then fills in rail order", () => {
    expect(
      mobilePrimaryItems([overview, actions, orders, tasks]).map(
        (item) => item.key,
      ),
    ).toEqual(["overview-web", "orders", "tasks", "actions"]);
  });

  it("shows fewer entries when the account has fewer", () => {
    expect(mobilePrimaryItems([actions]).map((item) => item.key)).toEqual([
      "actions",
    ]);
  });
});
