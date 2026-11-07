import { describe, expect, it } from "vitest";

import { legalTextBlocks } from "./legal-text";

describe("legalTextBlocks", () => {
  it("splits headings, paragraphs and lists", () => {
    expect(
      legalTextBlocks(
        "## Verantwortlicher\n\nDer Verein.\nZweite Zeile.\n\n- eins\n- zwei\n\nSchluss.",
      ),
    ).toEqual([
      { kind: "heading", text: "Verantwortlicher" },
      { kind: "paragraph", lines: ["Der Verein.", "Zweite Zeile."] },
      { kind: "list", items: ["eins", "zwei"] },
      { kind: "paragraph", lines: ["Schluss."] },
    ]);
  });

  it("separates a heading from the text right below it", () => {
    expect(legalTextBlocks("## Titel\nText\n- Punkt")).toEqual([
      { kind: "heading", text: "Titel" },
      { kind: "paragraph", lines: ["Text"] },
      { kind: "list", items: ["Punkt"] },
    ]);
  });

  it("ignores empty input, CRLF and extra blank lines", () => {
    expect(legalTextBlocks(null)).toEqual([]);
    expect(legalTextBlocks("  \n\n ")).toEqual([]);
    expect(legalTextBlocks("A\r\n\r\n\r\n\r\nB")).toEqual([
      { kind: "paragraph", lines: ["A"] },
      { kind: "paragraph", lines: ["B"] },
    ]);
  });

  it("keeps markup as plain text", () => {
    expect(legalTextBlocks("<script>alert(1)</script>")).toEqual([
      { kind: "paragraph", lines: ["<script>alert(1)</script>"] },
    ]);
  });
});
