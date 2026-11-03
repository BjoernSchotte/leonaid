// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TabPanel, Tabs } from "./tabs";

afterEach(cleanup);

const items = [
  { id: "open", label: "Offen", count: 12 },
  { id: "done", label: "Erledigt" },
  { id: "all", label: "Alle", count: 40 },
] as const;

type Id = (typeof items)[number]["id"];

function Harness({ onChange }: { readonly onChange?: (id: Id) => void }) {
  const [value, setValue] = useState<Id>("open");
  return (
    <>
      <Tabs
        idPrefix="orders"
        items={items}
        label="Ansichten"
        onChange={(id) => {
          onChange?.(id);
          setValue(id);
        }}
        value={value}
      />
      <TabPanel idPrefix="orders" tabId={value}>
        Inhalt {value}
      </TabPanel>
    </>
  );
}

describe("Tabs", () => {
  it("renders a labelled tablist with prototype classes and counts", () => {
    render(<Harness />);
    const list = screen.getByRole("tablist", { name: "Ansichten" });
    expect(list.className).toBe("tabs");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.className)).toEqual([
      "tab is-active",
      "tab",
      "tab",
    ]);
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true");
    expect(tabs[0]?.getAttribute("aria-controls")).toBe("orders-panel-open");
    expect(tabs[0]?.querySelector(".tab-count")?.textContent).toBe("12");
    const panel = screen.getByRole("tabpanel", { name: /Offen/ });
    expect(panel.id).toBe("orders-panel-open");
  });

  it("moves focus and selection with ArrowRight/ArrowLeft, Home and End", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);

    await user.click(tabs[0]!);
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(tabs[1]);
    expect(onChange).toHaveBeenLastCalledWith("done");
    expect(tabs[1]?.getAttribute("aria-selected")).toBe("true");
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0, -1]);
    expect(screen.getByRole("tabpanel").textContent).toBe("Inhalt done");

    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(document.activeElement).toBe(tabs[2]);
    expect(onChange).toHaveBeenLastCalledWith("all");
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(tabs[0]);
    expect(onChange).toHaveBeenLastCalledWith("open");
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(tabs[2]);
    expect(onChange).toHaveBeenLastCalledWith("all");
  });

  it("keeps Enter and Space as native activation", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const tabs = screen.getAllByRole("tab");
    tabs[1]!.focus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("done");
    tabs[2]!.focus();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenLastCalledWith("all");
  });

  it("keeps the single tab stop on the selected tab", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    await user.click(tabs[0]!);
    await user.keyboard("{ArrowRight}");
    await user.tab();
    expect(document.activeElement?.getAttribute("role")).toBe("tabpanel");
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0, -1]);
  });
});
