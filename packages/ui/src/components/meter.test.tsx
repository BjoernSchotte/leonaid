// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Meter } from "./meter";

afterEach(cleanup);

describe("Meter", () => {
  it("writes the fill ratio through CSSOM", () => {
    const setProperty = vi.spyOn(CSSStyleDeclaration.prototype, "setProperty");
    render(<Meter label="Spendenziel" max={10000} value={7128} />);
    const meter = screen.getByRole("meter", { name: "Spendenziel" });
    expect(setProperty).toHaveBeenCalledWith("--meter", "0.7128");
    expect(meter.style.getPropertyValue("--meter")).toBe("0.7128");
    setProperty.mockRestore();
  });

  it("never renders a style attribute on the server", () => {
    const markup = renderToString(
      <Meter label="Spendenziel" max={10000} value={7128} />,
    );
    expect(markup).not.toContain("style=");
  });

  it("exposes value, max and label", () => {
    render(<Meter label="Rücklauf" max={40} value={12} />);
    const meter = screen.getByRole("meter", { name: "Rücklauf" });
    expect(meter.getAttribute("aria-valuemin")).toBe("0");
    expect(meter.getAttribute("aria-valuemax")).toBe("40");
    expect(meter.getAttribute("aria-valuenow")).toBe("12");
    expect(meter.className).toBe("meter tone-zone");
  });

  it("clamps the ratio and survives a zero max", () => {
    const { rerender } = render(<Meter label="Ziel" max={10} value={25} />);
    const meter = screen.getByRole("meter", { name: "Ziel" });
    expect(meter.style.getPropertyValue("--meter")).toBe("1");
    rerender(<Meter label="Ziel" max={10} value={-3} />);
    expect(meter.style.getPropertyValue("--meter")).toBe("0");
    rerender(<Meter label="Ziel" max={0} value={5} />);
    expect(meter.style.getPropertyValue("--meter")).toBe("0");
  });
});
