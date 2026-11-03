export const FONT_FAMILIES = [
  { value: "sans-serif", label: "Sans Serif" },
  { value: "serif", label: "Serif" },
  { value: "monospace", label: "Monospace" },
];
export const FONT_SIZES = [12, 14, 16, 18, 20, 24, 32];

// Foreign documents often carry fonts outside our persisted document contract.
// Keep Tiptap in charge of structure; normalize fonts and link attributes.
/**
 * Read declarations from the raw style attribute. Under the strict CSP even
 * the parsed paste document inherits `style-src 'self'`, so `element.style`
 * stays empty; the attribute text itself is still available.
 */
export function styleDeclarations(value: string): Map<string, string> {
  const declarations = new Map<string, string>();
  for (const part of value.split(";")) {
    const separator = part.indexOf(":");
    if (separator < 0) continue;
    const name = part.slice(0, separator).trim().toLowerCase();
    const declared = part
      .slice(separator + 1)
      .replace(/!important/i, "")
      .trim()
      .replace(/^["']|["']$/g, "");
    if (name) declarations.set(name, declared.toLowerCase());
  }
  return declarations;
}

export function normalizePastedHTML(html: string): string {
  const document = new DOMParser().parseFromString(html, "text/html");
  // Supported values become the editor's formatting classes, and every style
  // attribute is dropped, so the paste never needs an inline style.
  for (const element of document.querySelectorAll<HTMLElement>("[style]")) {
    const style = styleDeclarations(element.getAttribute("style") ?? "");
    const family = style.get("font-family") ?? "";
    if (FONT_FAMILIES.some(({ value }) => value === family))
      element.classList.add(`knowledge-font-${family}`);
    const size = FONT_SIZES.find(
      (value) => style.get("font-size") === `${value}px`,
    );
    if (size !== undefined) element.classList.add(`knowledge-size-${size}`);
    const align = style.get("text-align") ?? "";
    if (["left", "center", "right", "justify"].includes(align))
      element.classList.add(`knowledge-align-${align}`);
    element.removeAttribute("style");
  }
  for (const link of document.querySelectorAll("a")) {
    link.removeAttribute("class");
    if (!["_blank", "_self"].includes(link.target))
      link.removeAttribute("target");
    link.rel = "noopener noreferrer nofollow";
    if (link.title.length > 2048) link.removeAttribute("title");
    if ((link.getAttribute("href") ?? "").length > 2048)
      link.removeAttribute("href");
  }
  return document.body.innerHTML;
}
