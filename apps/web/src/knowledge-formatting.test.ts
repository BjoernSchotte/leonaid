import { generateHTML, generateJSON } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { describe, expect, it } from "vitest";

import {
  ClassFontFamily,
  ClassFontSize,
  ClassTextAlign,
  ClassTextStyle,
} from "../../../packages/features/src/knowledge/class-formatting";

const extensions = [
  StarterKit,
  ClassTextStyle,
  ClassFontFamily,
  ClassFontSize,
  ClassTextAlign,
];

const document = {
  type: "doc",
  content: [
    {
      type: "paragraph",
      attrs: { textAlign: "center" },
      content: [
        {
          type: "text",
          text: "Zentriert",
          marks: [
            {
              type: "textStyle",
              attrs: { fontFamily: "serif", fontSize: "20px" },
            },
          ],
        },
      ],
    },
  ],
};

describe("CSP-safe formatting", () => {
  it("renders alignment, font and size as classes, never as style", () => {
    const html = generateHTML(document, extensions);
    expect(html).not.toContain("style=");
    expect(html).toContain('class="knowledge-align-center"');
    expect(html).toContain("knowledge-font-serif");
    expect(html).toContain("knowledge-size-20");
  });

  it("round-trips the classes into the same document attributes", () => {
    const json = generateJSON(generateHTML(document, extensions), extensions);
    expect(json).toEqual(document);
  });

  it("still reads inline styles from pasted HTML but drops unknown values", () => {
    const json = generateJSON(
      '<p style="text-align: right"><span style="font-family: serif; font-size: 13px">x</span></p>',
      extensions,
    );
    expect(json.content[0].attrs.textAlign).toBe("right");
    expect(json.content[0].content[0].marks[0].attrs).toEqual({
      fontFamily: "serif",
      fontSize: null,
    });
  });
});
