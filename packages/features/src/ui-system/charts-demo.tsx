import { useCallback } from "react";

import {
  ChartCanvas,
  ChartLegend,
  ChartTable,
  distributionConfig,
  stackedConfig,
  stackedSteps,
  type ChartTheme,
} from "@leonaid/ui";

/*
 * Catalog fixture for the Chart.js wrapper (Task 5.6b): an NPS segment bar,
 * a 0–10 distribution with withheld counts and a matrix with the diverging
 * ramp, each with its legend or table. Fixed demo values.
 */

const scores = [0, 0, 0, null, 0, null, null, null, 5, 6, 10] as const;
const segments = [
  ["Kritiker (0–6)", 6],
  ["Passive (7–8)", 8],
  ["Förderer (9–10)", 16],
] as const;
const matrix = [
  { label: "Organisation", segments: [64, 18, 18] },
  { label: "Verpflegung", segments: [40, 30, 30] },
] as const;
const columns = ["Gut", "Teils", "Verbesserungsbedarf"];

export function ChartsDemo() {
  const segmentConfig = useCallback(
    (theme: ChartTheme) =>
      stackedConfig(
        [
          {
            label: "Empfehlung",
            segments: segments.map(([label, count]) => ({
              label,
              percentage: (count / 30) * 100,
            })),
          },
        ],
        theme,
        { withheldLabel: "< 5", showRowLabels: false, negativeFirst: true },
      ),
    [],
  );
  const distribution = useCallback(
    (theme: ChartTheme) =>
      distributionConfig(
        scores.map((count, index) => ({ label: String(index), count })),
        theme,
        { withheldLabel: "< 5", unit: "Antworten" },
      ),
    [],
  );
  const matrixConfig = useCallback(
    (theme: ChartTheme) =>
      stackedConfig(
        matrix.map((row) => ({
          label: row.label,
          segments: row.segments.map((percentage, index) => ({
            label: columns[index]!,
            percentage,
          })),
        })),
        theme,
        { withheldLabel: "< 5" },
      ),
    [],
  );
  const npsSteps = stackedSteps(3, true);
  const matrixSteps = stackedSteps(columns.length);
  return (
    <div className="ui-catalog-charts" data-testid="ui-catalog-charts">
      <figure className="ui-catalog-chart">
        <figcaption>Net Promoter Score: 33</figcaption>
        <ChartCanvas
          config={segmentConfig}
          height={28}
          label="Empfehlung: Kritiker (0–6) 6 (20 %), Passive (7–8) 8 (27 %), Förderer (9–10) 16 (53 %)."
        />
        <ChartLegend
          items={segments.map(([label, count], index) => ({
            label,
            value: `${count} (${Math.round((count / 30) * 100)} %)`,
            step: npsSteps[index]!,
          }))}
          label="Legende: Empfehlung"
        />
      </figure>
      <figure className="ui-catalog-chart">
        <figcaption>Verteilung 0 bis 10</figcaption>
        <ChartCanvas
          config={distribution}
          height={140}
          label={`Verteilung: ${scores
            .map((count, index) => `${index}: ${count ?? "< 5"}`)
            .join(", ")}.`}
        />
        <ChartTable
          caption="Verteilung 0 bis 10"
          columns={["Wert", "Anzahl"]}
          rows={scores.map((count, index) => [
            String(index),
            count === null ? "< 5" : String(count),
          ])}
        />
      </figure>
      <figure className="ui-catalog-chart">
        <figcaption>Bewertung (Matrix)</figcaption>
        <ChartCanvas
          config={matrixConfig}
          height={72}
          label="Bewertung: Organisation Gut 64 %, Teils 18 %, Verbesserungsbedarf 18 %; Verpflegung Gut 40 %, Teils 30 %, Verbesserungsbedarf 30 %."
        />
        <ChartLegend
          items={columns.map((label, index) => ({
            label,
            value: "",
            step: matrixSteps[index]!,
          }))}
          label="Legende: Bewertung"
        />
      </figure>
    </div>
  );
}
