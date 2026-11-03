export const FONT_FAMILIES = [
  { value: "sans-serif", label: "Sans Serif" },
  { value: "serif", label: "Serif" },
  { value: "monospace", label: "Monospace" },
];
export const FONT_SIZES = [12, 14, 16, 18, 20, 24, 32];

// Foreign documents often carry fonts outside our persisted document contract.
// Keep Tiptap in charge of structure; normalize fonts and link attributes.
export function normalizePastedHTML(html: string): string {
  const document = new DOMParser().parseFromString(html, "text/html");
  // The strict CSP stops the live document from applying inline styles, so
  // supported values become the editor's formatting classes here, in the
  // inert parsed document, and every style attribute is dropped.
  for (const element of document.querySelectorAll<HTMLElement>("[style]")) {
    const family = element.style.fontFamily;
    if (FONT_FAMILIES.some(({ value }) => value === family))
      element.classList.add(`knowledge-font-${family}`);
    const size = FONT_SIZES.find(
      (value) => element.style.fontSize === `${value}px`,
    );
    if (size !== undefined) element.classList.add(`knowledge-size-${size}`);
    const align = element.style.textAlign;
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
