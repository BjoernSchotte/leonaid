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

  it("moves focus with ArrowRight/ArrowLeft without selecting, roving tabindex", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);

    await user.click(tabs[0]!);
    onChange.mockClear();
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(tabs[1]);
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0, -1]);
    expect(onChange).not.toHaveBeenCalled();

    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(document.activeElement).toBe(tabs[2]);
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(tabs[0]);
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(tabs[2]);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("selects the focused tab on Enter and Space", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const tabs = screen.getAllByRole("tab");
    await user.click(tabs[0]!);
    onChange.mockClear();

    await user.keyboard("{ArrowRight}{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("done");
    expect(tabs[1]?.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").textContent).toBe("Inhalt done");

    await user.keyboard("{ArrowRight} ");
    expect(onChange).toHaveBeenLastCalledWith("all");
  });

  it("puts the tab stop back on the selected tab when focus leaves", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    await user.click(tabs[0]!);
    await user.keyboard("{ArrowRight}");
    await user.tab();
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
  });
});
