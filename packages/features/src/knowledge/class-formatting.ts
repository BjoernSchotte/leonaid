import { Extension } from "@tiptap/core";
import TextAlign from "@tiptap/extension-text-align";
import { FontFamily, FontSize, TextStyle } from "@tiptap/extension-text-style";
import { Plugin } from "@tiptap/pm/state";

import { FONT_FAMILIES, FONT_SIZES, styleDeclarations } from "./paste";

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

function declared(element: HTMLElement, property: string): string {
  return (
    styleDeclarations(element.getAttribute("style") ?? "").get(property) ?? ""
  );
}

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
                declared(element, "text-align");
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
                declared(element, "font-family");
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
                : declared(element, "font-size");
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

/*
 * Typing over a selection lets the browser replace the selected DOM itself.
 * Chromium then keeps the look of the removed text by inserting
 * `<span style="font-size: …">`, which the strict CSP blocks and reports.
 * Replacing a non-empty selection in the document instead inherits the marks
 * of the selection and never writes an inline style. IME composition and
 * collapsed selections stay with the browser.
 */
export const ReplaceSelectionInput = Extension.create({
  name: "replaceSelectionInput",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        props: {
          handleDOMEvents: {
            beforeinput: (view, event) => {
              const input = event as InputEvent;
              if (
                input.inputType !== "insertText" ||
                input.isComposing ||
                !input.data
              ) {
                return false;
              }
              // The browser names the range it would replace; the editor
              // state may not have read a just-changed DOM selection yet.
              const [range] = input.getTargetRanges();
              if (!range || range.collapsed) return false;
              let from: number;
              let to: number;
              try {
                from = view.posAtDOM(range.startContainer, range.startOffset);
                to = view.posAtDOM(range.endContainer, range.endOffset);
              } catch {
                return false;
              }
              if (from >= to) return false;
              input.preventDefault();
              view.dispatch(
                view.state.tr.insertText(input.data, from, to).scrollIntoView(),
              );
              return true;
            },
          },
        },
      }),
    ];
  },
});
