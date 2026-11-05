import type { ChartConfiguration } from "chart.js";
import { useEffect, useRef } from "react";

import { Chart, valueLabels } from "./register";
import {
  type DivergingStep,
  themeFor,
  useThemeVersion,
  type ChartTheme,
} from "./theme";

export interface ChartCanvasProps {
  /** Builds the chart from the resolved theme; memoise it (useCallback). */
  readonly config: (theme: ChartTheme) => ChartConfiguration<"bar">;
  /**
   * One sentence with every value: the canvas's accessible name and its
   * fallback content (a canvas has no semantics of its own).
   */
  readonly label: string;
  /** Plot height in px (set through CSSOM, no style attribute). */
  readonly height: number;
  readonly className?: string;
}

/**
 * Chart.js bar chart, our wrapper: created once, updated in place when the
 * config or theme changes, destroyed on unmount. Pair it with an HTML
 * legend and an "Als Tabelle anzeigen" table (`ChartTable`).
 */
export function ChartCanvas({
  config,
  label,
  height,
  className,
}: ChartCanvasProps) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const chart = useRef<Chart<"bar"> | null>(null);
  const themeVersion = useThemeVersion();

  useEffect(() => {
    host.current?.style.setProperty("--chart-h", `${height}px`);
  }, [height]);

  useEffect(() => {
    if (!canvas.current || !host.current) return;
    const next = config(themeFor(host.current));
    if (chart.current) {
      chart.current.data = next.data;
      chart.current.options = next.options ?? {};
      chart.current.update("none");
      return;
    }
    // No 2D context (e.g. a test DOM): keep the fallback text only.
    if (!canvas.current.getContext?.("2d")) return;
    chart.current = new Chart(canvas.current, {
      ...next,
      plugins: [...(next.plugins ?? []), valueLabels],
    });
  }, [config, themeVersion]);

  useEffect(
    () => () => {
      chart.current?.destroy();
      chart.current = null;
    },
    [],
  );

  return (
    <div
      className={className ? `chart-canvas ${className}` : "chart-canvas"}
      ref={host}
    >
      <canvas aria-label={label} ref={canvas} role="img">
        {label}
      </canvas>
    </div>
  );
}

export interface ChartTableProps {
  readonly caption: string;
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
  /** Summary text, default "Als Tabelle anzeigen". */
  readonly summary?: string;
}

/** The chart's data as a real table, behind a disclosure. */
export function ChartTable({
  caption,
  columns,
  rows,
  summary = "Als Tabelle anzeigen",
}: ChartTableProps) {
  return (
    <details className="chart-table">
      <summary>{summary}</summary>
      {/* Wide tables scroll sideways; scrollbars are hidden, so the region
          takes focus for keyboard scrolling (axe scrollable-region-focusable). */}
      <div
        aria-label={caption}
        className="table-wrap"
        role="region"
        tabIndex={0}
      >
        <table className="table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column, index) => (
                <th
                  className={index > 0 ? "right" : undefined}
                  key={column}
                  scope="col"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, index) =>
                  index === 0 ? (
                    <th key={index} scope="row">
                      {cell}
                    </th>
                  ) : (
                    <td className="num right" key={index}>
                      {cell}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export interface ChartLegendItem {
  readonly label: string;
  readonly value: string;
  /** The segment's ramp step (`divergingSteps`), same as in the chart. */
  readonly step: DivergingStep;
}

/** HTML legend with values: the direct labels of stacked segments. */
export function ChartLegend({
  items,
  label,
}: {
  readonly items: readonly ChartLegendItem[];
  readonly label: string;
}) {
  return (
    <ul aria-label={label} className="chart-legend">
      {items.map((item) => (
        <li key={item.label}>
          <span
            aria-hidden="true"
            className={`chart-swatch chart-swatch-${item.step}`}
          />
          <span className="chart-legend-label">{item.label}</span>
          <span className="chart-legend-value num">{item.value}</span>
        </li>
      ))}
    </ul>
  );
}
