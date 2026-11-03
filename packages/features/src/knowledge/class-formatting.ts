import TextAlign from "@tiptap/extension-text-align";
import { FontFamily, FontSize, TextStyle } from "@tiptap/extension-text-style";

import { FONT_FAMILIES, FONT_SIZES } from "./paste";

/*
 * The stock Tiptap extensions render alignment, font family and font size as
 * inline `style` attributes, which the strict Content Security Policy
 * (`style-src 'self'`) blocks. These variants keep the same document
 * attributes and commands but render CSS classes from knowledge.css. Parsing
 * accepts the classes and, for pasted or older HTML, the inline style.
 */

const ALIGNMENTS = ["left", "center", "right", "justify"] as const;

/** The stock mark only recognizes spans with a style attribute. */
export const ClassTextStyle = TextStyle.extend({
  parseHTML() {
    return [
      {
        tag: "span",
        consuming: false,
        getAttrs: (element: HTMLElement) =>
          element.hasAttribute("style") ||
          [...element.classList].some(
            (name) =>
              name.startsWith("knowledge-font-") ||
              name.startsWith("knowledge-size-"),
          )
            ? {}
            : false,
      },
    ];
  },
});

function classValue(element: HTMLElement, prefix: string): string | null {
  const found = [...element.classList].find((name) => name.startsWith(prefix));
  return found ? found.slice(prefix.length) : null;
}

export const ClassTextAlign = TextAlign.extend({
  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          textAlign: {
            default: this.options.defaultAlignment,
            parseHTML: (element: HTMLElement) => {
              const value =
                classValue(element, "knowledge-align-") ??
                element.style.textAlign;
              return ALIGNMENTS.some((alignment) => alignment === value)
                ? value
                : this.options.defaultAlignment;
            },
            renderHTML: (attributes: Record<string, unknown>) => {
              const value = attributes.textAlign;
              if (!value || value === this.options.defaultAlignment) return {};
              return { class: `knowledge-align-${String(value)}` };
            },
          },
        },
      },
    ];
  },
}).configure({ types: ["heading", "paragraph"] });

export const ClassFontFamily = FontFamily.extend({
  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          fontFamily: {
            default: null,
            parseHTML: (element: HTMLElement) => {
              const value =
                classValue(element, "knowledge-font-") ??
                element.style.fontFamily;
              return FONT_FAMILIES.some((font) => font.value === value)
                ? value
                : null;
            },
            renderHTML: (attributes: Record<string, unknown>) =>
              attributes.fontFamily
                ? { class: `knowledge-font-${String(attributes.fontFamily)}` }
                : {},
          },
        },
      },
    ];
  },
});

export const ClassFontSize = FontSize.extend({
  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (element: HTMLElement) => {
              const fromClass = classValue(element, "knowledge-size-");
              const value = fromClass
                ? `${fromClass}px`
                : element.style.fontSize;
              return FONT_SIZES.some((size) => `${size}px` === value)
                ? value
                : null;
            },
            renderHTML: (attributes: Record<string, unknown>) =>
              attributes.fontSize
                ? {
                    class: `knowledge-size-${String(attributes.fontSize).replace(/px$/, "")}`,
                  }
                : {},
          },
        },
      },
    ];
  },
});
