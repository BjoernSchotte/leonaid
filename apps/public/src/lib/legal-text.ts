/**
 * Structure of a legal text from the legal configuration (privacy policy,
 * members' notice). The format is deliberately small and needs no HTML:
 * blocks are separated by an empty line, "## " starts a heading, lines
 * starting with "- " form a list; every other block is a paragraph whose
 * line breaks are kept. The renderer only emits text nodes, so a text can
 * never inject markup.
 */
export type LegalTextBlock =
  | { readonly kind: "heading"; readonly text: string }
  | { readonly kind: "paragraph"; readonly lines: readonly string[] }
  | { readonly kind: "list"; readonly items: readonly string[] };

export function legalTextBlocks(text: string | null | undefined) {
  const blocks: LegalTextBlock[] = [];
  const source = (text ?? "").replace(/\r\n?/g, "\n");
  for (const raw of source.split(/\n\s*\n/)) {
    const lines = raw
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line !== "");
    if (lines.length === 0) continue;
    let paragraph: string[] = [];
    let list: string[] = [];
    const flushParagraph = () => {
      if (paragraph.length)
        blocks.push({ kind: "paragraph", lines: paragraph });
      paragraph = [];
    };
    const flushList = () => {
      if (list.length) blocks.push({ kind: "list", items: list });
      list = [];
    };
    for (const line of lines) {
      if (line.startsWith("## ")) {
        flushParagraph();
        flushList();
        blocks.push({ kind: "heading", text: line.slice(3).trim() });
      } else if (line.startsWith("- ")) {
        flushParagraph();
        list.push(line.slice(2).trim());
      } else {
        flushList();
        paragraph.push(line);
      }
    }
    flushParagraph();
    flushList();
  }
  return blocks;
}
