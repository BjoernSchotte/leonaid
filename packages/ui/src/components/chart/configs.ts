import type { ChartConfiguration, TooltipItem } from "chart.js";

import { divergingColors, divergingSteps, type ChartTheme } from "./theme";

/*
 * Pure chart configs: (data, theme) => ChartConfiguration. No colour
 * literals; every colour comes from the resolved theme.
 */

const base = (theme: ChartTheme) => ({
  maintainAspectRatio: false,
  animation: false as const,
  responsive: true,
  font: { family: theme.font },
});

const tooltip = (theme: ChartTheme) => ({
  backgroundColor: theme.surface,
  borderColor: theme.border,
  borderWidth: 1,
  titleColor: theme.text,
  bodyColor: theme.text,
  titleFont: { family: theme.font },
  bodyFont: { family: theme.font },
  displayColors: false,
});

export interface DistributionBar {
  readonly label: string;
  /** null: withheld (fewer than the minimum group size). */
  readonly count: number | null;
}

/**
 * Vertical bars with a count above each, e.g. NPS scores 0–10. A withheld
 * count draws no bar and prints `withheldLabel` ("< 5").
 */
export function distributionConfig(
  bars: readonly DistributionBar[],
  theme: ChartTheme,
  { withheldLabel, unit }: { withheldLabel: string; unit: string },
): ChartConfiguration<"bar"> {
  const max = Math.max(1, ...bars.map((bar) => bar.count ?? 0));
  return {
    type: "bar",
    data: {
      labels: bars.map((bar) => bar.label),
      datasets: [
        {
          data: bars.map((bar) => bar.count ?? 0),
          backgroundColor: theme.zone,
          borderRadius: 4,
          borderSkipped: "start",
          maxBarThickness: 22,
        },
      ],
    },
    options: {
      ...base(theme),
      layout: { padding: { top: 18 } },
      scales: {
        x: {
          grid: { display: false },
          border: { color: theme.border },
          ticks: { color: theme.text2, font: { family: theme.font, size: 12 } },
        },
        y: { display: false, max: max * 1.08, beginAtZero: true },
      },
      plugins: {
        tooltip: {
          ...tooltip(theme),
          callbacks: {
            label: (item: TooltipItem<"bar">) => {
              const count = bars[item.dataIndex]?.count ?? null;
              return count === null ? withheldLabel : `${count} ${unit}`;
            },
          },
        },
        leonaidValueLabels: {
          color: theme.text,
          font: theme.font,
          position: "top",
          format: (_dataset, index) => {
            const count = bars[index]?.count ?? null;
            return count === null ? withheldLabel : String(count);
          },
        },
      },
    },
  };
}

export interface StackSegment {
  readonly label: string;
  /** Share of the row in percent; null: withheld. */
  readonly percentage: number | null;
}

export interface StackRow {
  readonly label: string;
  readonly segments: readonly StackSegment[];
}

/**
 * 100 % stacked horizontal bars, one per row, segments coloured along the
 * diverging ramp in segment order (first = positive pole). Segment values
 * belong in the HTML legend and the table, not on the fills. A 2 px surface
 * gap separates segments.
 */
export function stackedConfig(
  rows: readonly StackRow[],
  theme: ChartTheme,
  {
    withheldLabel,
    showRowLabels = true,
    negativeFirst = false,
  }: {
    withheldLabel: string;
    showRowLabels?: boolean;
    negativeFirst?: boolean;
  },
): ChartConfiguration<"bar"> {
  const segmentLabels = rows[0]?.segments.map((segment) => segment.label) ?? [];
  const colors = divergingColors(theme, segmentLabels.length);
  if (negativeFirst) colors.reverse();
  return {
    type: "bar",
    data: {
      labels: rows.map((row) => row.label),
      datasets: segmentLabels.map((label, segmentIndex) => ({
        label,
        data: rows.map((row) => row.segments[segmentIndex]?.percentage ?? 0),
        backgroundColor: colors[segmentIndex],
        borderColor: theme.surface,
        borderWidth: { right: 2 },
        borderSkipped: false as const,
        barThickness: 18,
      })),
    },
    options: {
      ...base(theme),
      indexAxis: "y",
      scales: {
        x: { display: false, stacked: true, min: 0, max: 100 },
        y: {
          stacked: true,
          display: showRowLabels,
          grid: { display: false },
          border: { display: false },
          ticks: { color: theme.text2, font: { family: theme.font, size: 12 } },
        },
      },
      plugins: {
        tooltip: {
          ...tooltip(theme),
          callbacks: {
            label: (item: TooltipItem<"bar">) => {
              const value =
                rows[item.dataIndex]?.segments[item.datasetIndex]?.percentage ??
                null;
              return `${item.dataset.label}: ${
                value === null ? withheldLabel : `${Math.round(value)} %`
              }`;
            },
          },
        },
      },
    },
  };
}

/** Ramp steps of `stackedConfig`'s segments, for the matching HTML legend. */
export function stackedSteps(count: number, negativeFirst = false) {
  const steps = divergingSteps(count);
  return negativeFirst ? steps.reverse() : steps;
}
