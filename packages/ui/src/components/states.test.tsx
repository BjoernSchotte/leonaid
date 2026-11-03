// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PackageOpen } from "lucide-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmptyState } from "./empty-state";
import { SkeletonRows } from "./skeleton-rows";
import { ErrorState, StatusMessage } from "./status-message";

afterEach(cleanup);

describe("EmptyState", () => {
  it("renders the prototype markup with a 22 px Lucide icon", () => {
    render(
      <EmptyState
        action={<button type="button">Filter zurücksetzen</button>}
        description="Passen Sie die Filter an."
        icon={PackageOpen}
        title="Keine passenden Bestellungen"
      />,
    );
    const heading = screen.getByRole("heading", {
      level: 3,
      name: "Keine passenden Bestellungen",
    });
    expect(heading.className).toBe("empty-title");
    const root = heading.parentElement!;
    expect(root.className).toBe("empty");
    const icon = root.querySelector(".empty-icon");
    expect(icon?.getAttribute("aria-hidden")).toBe("true");
    expect(icon?.querySelector("svg")?.getAttribute("width")).toBe("22");
    expect(root.querySelector(".empty-text")?.textContent).toBe(
      "Passen Sie die Filter an.",
    );
    expect(root.querySelector(".empty-action")?.textContent).toBe(
      "Filter zurücksetzen",
    );
  });

  it("supports a level-2 heading for page-level states and element icons", () => {
    render(
      <EmptyState
        headingLevel={2}
        icon={<svg data-testid="custom" />}
        title="Noch nichts da"
      />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Noch nichts da" }),
    ).toBeTruthy();
    expect(screen.getByTestId("custom")).toBeTruthy();
    expect(document.querySelector(".empty-text")).toBeNull();
  });
});

describe("ErrorState", () => {
  it("is an alert with a danger title and a retry button", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <ErrorState onRetry={onRetry} title="Bestellungen nicht geladen">
        Der Server antwortet nicht.
      </ErrorState>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.className).toBe("error-state");
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: "Bestellungen nicht geladen",
      }),
    ).toBeTruthy();
    expect(alert.querySelector(".error-text")?.textContent).toBe(
      "Der Server antwortet nicht.",
    );
    const retry = screen.getByRole("button", { name: "Erneut versuchen" });
    expect(retry.className).toBe("btn btn-secondary btn-md");
    await user.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("omits the retry button without onRetry", () => {
    render(<ErrorState title="Fehler">Text</ErrorState>);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("StatusMessage", () => {
  it.each([
    ["info", "callout tone-info", "status"],
    ["success", "callout tone-ok", "status"],
    ["warning", "callout tone-warn", "status"],
    ["error", "callout tone-danger", "alert"],
  ] as const)("renders tone %s as %s", (tone, className, role) => {
    render(<StatusMessage tone={tone}>Hinweis</StatusMessage>);
    const message = screen.getByRole(role);
    expect(message.className).toBe(className);
    expect(
      message.querySelector(":scope > svg")?.getAttribute("aria-hidden"),
    ).toBe("true");
  });
});

describe("SkeletonRows", () => {
  it("renders hidden shimmer rows with the 60/40/50 line pattern", () => {
    const { container } = render(<SkeletonRows rows={4} />);
    const list = container.firstElementChild!;
    expect(list.className).toBe("skeleton-list");
    expect(list.getAttribute("aria-hidden")).toBe("true");
    const lines = [...list.querySelectorAll(".skeleton-line")].map(
      (line) => line.className,
    );
    expect(lines).toEqual([
      "skeleton skeleton-line w-60",
      "skeleton skeleton-line w-40",
      "skeleton skeleton-line w-50",
      "skeleton skeleton-line w-60",
    ]);
    expect(list.querySelectorAll(".skeleton-row")).toHaveLength(4);
    expect(list.querySelectorAll(".skeleton-dot")).toHaveLength(4);
    expect(list.querySelectorAll(".skeleton-chip")).toHaveLength(4);
  });

  it("defaults to six rows", () => {
    const { container } = render(<SkeletonRows />);
    expect(container.querySelectorAll(".skeleton-row")).toHaveLength(6);
  });
});
