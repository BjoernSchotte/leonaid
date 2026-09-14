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
  for (const element of document.querySelectorAll<HTMLElement>("[style]")) {
    if (!FONT_FAMILIES.some(({ value }) => value === element.style.fontFamily))
      element.style.removeProperty("font-family");
    if (!FONT_SIZES.some((size) => element.style.fontSize === `${size}px`))
      element.style.removeProperty("font-size");
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
