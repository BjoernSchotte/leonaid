import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  type ChartType,
  LinearScale,
  type Plugin,
  Tooltip,
} from "chart.js";

/*
 * Tree-shaken registration: only bar charts with category/linear scales and
 * the canvas tooltip (no Legend: legends are HTML next to the chart).
 */
Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

export interface ValueLabelOptions {
  /** Text per data point; null draws nothing. */
  readonly format?: (datasetIndex: number, index: number) => string | null;
  readonly color?: string;
  readonly font?: string;
  /** "end": after a horizontal bar; "top": above a vertical bar. Segment
   * values of stacked bars go in the HTML legend, not on the fill. */
  readonly position?: "end" | "top";
}

declare module "chart.js" {
  interface PluginOptionsByType<TType extends ChartType> {
    leonaidValueLabels?: ValueLabelOptions & { _type?: TType };
  }
}

/** Direct labels drawn on the canvas in text ink (no datalabels plugin). */
export const valueLabels: Plugin<"bar"> = {
  id: "leonaidValueLabels",
  afterDatasetsDraw(chart, _args, options: ValueLabelOptions) {
    const { format } = options;
    if (!format) return;
    const { ctx } = chart;
    ctx.save();
    ctx.fillStyle = options.color ?? "#000";
    ctx.font = `600 12px ${options.font ?? "sans-serif"}`;
    const position = options.position ?? "end";
    ctx.textAlign = position === "end" ? "left" : "center";
    ctx.textBaseline = position === "top" ? "bottom" : "middle";
    chart.data.datasets.forEach((_dataset, datasetIndex) => {
      const meta = chart.getDatasetMeta(datasetIndex);
      if (meta.hidden) return;
      meta.data.forEach((element, index) => {
        const text = format(datasetIndex, index);
        if (!text) return;
        const bar = element.getProps(["x", "y"], true) as {
          x: number;
          y: number;
        };
        if (position === "end") ctx.fillText(text, bar.x + 6, bar.y);
        else ctx.fillText(text, bar.x, bar.y - 4);
      });
    });
    ctx.restore();
  },
};

export { Chart };
