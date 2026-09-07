import { validCampaignEditorial } from "../auth/campaign-editorial.mjs";

const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
const marks = {
  strong: "strong",
  em: "em",
  underline: "u",
  "strike-through": "s",
  code: "code",
};

// All tags originate in this file, all text/attributes are escaped, and the
// same strict editorial schema used by writes bounds the complete input.
export function editorialHtml(data) {
  if (!validCampaignEditorial(data))
    throw new Error("invalid_public_editorial");
  const blocks = data.body ?? [];
  const inline = (block) =>
    block.children
      .map((span) => {
        let value = escape(span.text).replaceAll("\n", "<br>");
        for (const mark of span.marks ?? []) {
          if (Object.hasOwn(marks, mark))
            value = `<${marks[mark]}>${value}</${marks[mark]}>`;
          else {
            const link = (block.markDefs ?? []).find(
              (item) => item._key === mark,
            );
            if (!link) throw new Error("invalid_public_editorial");
            value = `<a href="${escape(link.href)}" rel="noopener noreferrer">${value}</a>`;
          }
        }
        return value;
      })
      .join("");
  let index = 0;
  function list(level, kind) {
    const tag = kind === "number" ? "ol" : "ul";
    let result = `<${tag}>`;
    while (index < blocks.length) {
      const block = blocks[index];
      if (
        !block.listItem ||
        (block.level ?? 1) < level ||
        block.listItem !== kind
      )
        break;
      result += `<li>${inline(block)}`;
      index++;
      while (
        index < blocks.length &&
        blocks[index].listItem &&
        (blocks[index].level ?? 1) > level
      ) {
        result += list(blocks[index].level ?? 1, blocks[index].listItem);
      }
      result += "</li>";
    }
    return result + `</${tag}>`;
  }
  let result = "";
  while (index < blocks.length) {
    const block = blocks[index];
    if (block.listItem) result += list(block.level ?? 1, block.listItem);
    else {
      const tag = { h2: "h2", h3: "h3", blockquote: "blockquote", normal: "p" }[
        block.style ?? "normal"
      ];
      result += `<${tag}>${inline(block)}</${tag}>`;
      index++;
    }
  }
  return result;
}
