import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  StatusIcon,
  StatusLabel,
  statusShape,
  type StatusShape,
} from "./status-icon";

const shapes: readonly StatusShape[] = [
  "draft",
  "open",
  "review",
  "progress",
  "done",
  "alert",
  "cancelled",
];

const shapeBody = (markup: string) =>
  markup.replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "");

describe("StatusIcon", () => {
  it("draws a distinct shape for every status", () => {
    const bodies = shapes.map((shape) =>
      shapeBody(
        renderToStaticMarkup(<StatusIcon label={shape} status={shape} />),
      ),
    );
    expect(new Set(bodies).size).toBe(shapes.length);
  });

  it.each(shapes)("exposes the label of %s as an image", (shape) => {
    const markup = renderToStaticMarkup(
      <StatusIcon label="Überfällig" status={shape} />,
    );
    expect(markup).toMatch(/^<svg[^>]* role="img"/);
    expect(markup).toContain('aria-label="Überfällig"');
    expect(markup).not.toContain("aria-hidden");
  });

  it("repeats the shape meaning in the tone", () => {
    const tone = (status: StatusShape) =>
      /class="status-icon tone-([a-z]+)"/.exec(
        renderToStaticMarkup(<StatusIcon label="x" status={status} />),
      )?.[1];
    expect(shapes.map(tone)).toEqual([
      "neutral",
      "info",
      "warn",
      "warn",
      "ok",
      "danger",
      "neutral",
    ]);
  });

  it("renders at 14 px on a 16-unit grid", () => {
    const markup = renderToStaticMarkup(<StatusIcon label="x" status="open" />);
    expect(markup).toContain('width="14"');
    expect(markup).toContain('height="14"');
    expect(markup).toContain('viewBox="0 0 16 16"');
  });

  it("is decorative in a status label and keeps the word for assistive tech", () => {
    const markup = renderToStaticMarkup(<StatusLabel status="Storniert" />);
    expect(markup).toContain('class="status-label is-cancelled"');
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toContain("<span>Storniert</span>");
  });

  it("maps domain statuses to shapes and falls back to open", () => {
    expect(statusShape["Überfällig"]).toBe("alert");
    expect(statusShape["Prüfbereit"]).toBe("review");
    expect(renderToStaticMarkup(<StatusLabel status="Unbekannt" />)).toContain(
      "is-open",
    );
  });
});
