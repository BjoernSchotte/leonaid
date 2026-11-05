// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChartLegend, ChartTable } from "./chart-canvas";
import { distributionConfig, stackedConfig, stackedSteps } from "./configs";
import { divergingSteps, type ChartTheme } from "./theme";

afterEach(() => cleanup());

const theme: ChartTheme = {
  zone: "rgb(1, 1, 1)",
  track: "rgb(2, 2, 2)",
  text: "rgb(3, 3, 3)",
  text2: "rgb(4, 4, 4)",
  border: "rgb(5, 5, 5)",
  surface: "rgb(6, 6, 6)",
  diverging: ["neg", "neg-soft", "mid", "pos-soft", "pos"],
  font: "Barlow",
};

describe("diverging steps", () => {
  it("runs from the positive to the negative pole with a grey middle", () => {
    expect(divergingSteps(2)).toEqual(["pos", "neg"]);
    expect(divergingSteps(3)).toEqual(["pos", "mid", "neg"]);
    expect(divergingSteps(5)).toEqual([
      "pos",
      "pos-soft",
      "mid",
      "neg-soft",
      "neg",
    ]);
    expect(divergingSteps(7)[0]).toBe("pos");
    expect(divergingSteps(7)[6]).toBe("neg");
    expect(stackedSteps(3, true)).toEqual(["neg", "mid", "pos"]);
  });
});

describe("chart configs", () => {
  it("draws withheld bars as empty with the withheld label", () => {
    const config = distributionConfig(
      [
        { label: "0", count: null },
        { label: "1", count: 7 },
      ],
      theme,
      { withheldLabel: "< 5", unit: "Antworten" },
    );
    expect(config.data.datasets[0]?.data).toEqual([0, 7]);
    expect(config.data.datasets[0]?.backgroundColor).toBe(theme.zone);
    const format = config.options?.plugins?.leonaidValueLabels?.format;
    expect(format?.(0, 0)).toBe("< 5");
    expect(format?.(0, 1)).toBe("7");
    expect(config.options?.animation).toBe(false);
  });

  it("stacks segments in ramp order, colours from the theme only", () => {
    const rows = [
      {
        label: "Organisation",
        segments: [
          { label: "Gut", percentage: 80 },
          { label: "Schlecht", percentage: null },
        ],
      },
    ];
    const positive = stackedConfig(rows, theme, { withheldLabel: "< 5" });
    expect(
      positive.data.datasets.map((dataset) => dataset.backgroundColor),
    ).toEqual(["pos", "neg"]);
    expect(positive.data.datasets[1]?.data).toEqual([0]);
    const negative = stackedConfig(rows, theme, {
      withheldLabel: "< 5",
      negativeFirst: true,
    });
    expect(
      negative.data.datasets.map((dataset) => dataset.backgroundColor),
    ).toEqual(["neg", "pos"]);
  });
});

describe("chart companions", () => {
  it("renders a legend with values and a table behind a disclosure", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <>
        <ChartLegend
          items={[
            { label: "Kritiker", value: "< 5", step: "neg" },
            { label: "Förderer", value: "12 (60 %)", step: "pos" },
          ]}
          label="Legende"
        />
        <ChartTable
          caption="NPS"
          columns={["Gruppe", "Anzahl"]}
          rows={[["Kritiker", "< 5"]]}
        />
      </>,
    );
    const legend = screen.getByRole("list", { name: "Legende" });
    expect(legend.textContent).toContain("Förderer12 (60 %)");
    expect(legend.querySelector(".chart-swatch-neg")).not.toBeNull();
    expect(screen.getByText("Als Tabelle anzeigen").tagName).toBe("SUMMARY");
    expect(screen.getByRole("table").textContent).toContain("Kritiker< 5");
  });

  it("lets keyboard users scroll a wide table (focusable, labelled region)", () => {
    render(
      <ChartTable
        caption="Antworten je Option"
        columns={["Frage", "Sehr gut", "Gut", "Mittel", "Schlecht"]}
        rows={[["Lieferung", "4", "3", "2", "1"]]}
      />,
    );
    const region = screen.getByRole("region", { name: "Antworten je Option" });
    expect(region.className).toBe("table-wrap");
    expect(region.tabIndex).toBe(0);
    expect(region.querySelector("table")).not.toBeNull();
  });
});
