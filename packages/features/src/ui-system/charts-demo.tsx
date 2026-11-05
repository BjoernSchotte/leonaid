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

// As the server discloses (k = 5): once a count is withheld, every cell
// under 10 is withheld with it, zeros included.
const scores = [
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  null,
  12,
  14,
  16,
] as const;
// The segments add up the same answers: 0–6 (withheld above) are 6,
// 7 (withheld) is 4 plus 12 for 8, and 9–10 are 14 + 16.
const segments = [
  ["Kritiker (0–6)", 6],
  ["Passive (7–8)", 16],
  ["Förderer (9–10)", 30],
] as const;
const answers = segments.reduce((sum, [, count]) => sum + count, 0);
const share = (count: number) => Math.round((count / answers) * 100);
// NPS: promoters minus critics, in percent of all answers.
const nps = Math.round(((segments[2][1] - segments[0][1]) / answers) * 100);
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
              percentage: (count / answers) * 100,
            })),
          },
        ],
        theme,
        { withheldLabel: "–", showRowLabels: false, negativeFirst: true },
      ),
    [],
  );
  const distribution = useCallback(
    (theme: ChartTheme) =>
      distributionConfig(
        scores.map((count, index) => ({ label: String(index), count })),
        theme,
        { withheldLabel: "–", unit: "Antworten" },
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
        { withheldLabel: "–" },
      ),
    [],
  );
  const npsSteps = stackedSteps(3, true);
  const matrixSteps = stackedSteps(columns.length);
  return (
    <div className="ui-catalog-charts" data-testid="ui-catalog-charts">
      <figure className="ui-catalog-chart">
        <figcaption>Net Promoter Score: {nps}</figcaption>
        <ChartCanvas
          config={segmentConfig}
          height={28}
          label={`Empfehlung: ${segments
            .map(([label, count]) => `${label} ${count} (${share(count)} %)`)
            .join(", ")}.`}
        />
        <ChartLegend
          items={segments.map(([label, count], index) => ({
            label,
            value: `${count} (${share(count)} %)`,
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
            .map((count, index) => `${index}: ${count ?? "–"}`)
            .join(", ")}.`}
        />
        <ChartTable
          caption="Verteilung 0 bis 10"
          columns={["Wert", "Anzahl"]}
          rows={scores.map((count, index) => [
            String(index),
            count === null ? "–" : String(count),
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
