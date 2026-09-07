import assert from "node:assert/strict";
import { editorialHtml } from "../../apps/campaign-site/src/public/editorial-html.mjs";

const block = (key, text, extra = {}) => ({
  _type: "block",
  _key: key,
  children: [{ _type: "span", _key: `${key}_span`, text }],
  ...extra,
});
const render = (body) => editorialHtml({ title: "Synthetic", body });
assert.equal(
  render([block("a", "<script>\" & '</script>")]),
  "<p>&lt;script&gt;&quot; &amp; &#39;&lt;/script&gt;</p>",
);
assert.equal(
  render([
    block("a", "Heading", { style: "h2" }),
    block("b", "Subheading", { style: "h3" }),
    block("c", "Quote", { style: "blockquote" }),
  ]),
  "<h2>Heading</h2><h3>Subheading</h3><blockquote>Quote</blockquote>",
);
assert.equal(
  render([
    block("a", "One", { listItem: "number" }),
    block("b", "Nested", { listItem: "bullet", level: 2 }),
    block("c", "Deeper", { listItem: "number", level: 3 }),
    block("d", "Two", { listItem: "number" }),
    block("e", "After"),
  ]),
  "<ol><li>One<ul><li>Nested<ol><li>Deeper</li></ol></li></ul></li><li>Two</li></ol><p>After</p>",
);
for (const mark of ["strong", "em", "underline", "strike-through", "code"]) {
  const tag = {
    strong: "strong",
    em: "em",
    underline: "u",
    "strike-through": "s",
    code: "code",
  }[mark];
  assert.equal(
    render([
      block("a", "", {
        children: [{ _type: "span", _key: "s", text: "Safe", marks: [mark] }],
      }),
    ]),
    `<p><${tag}>Safe</${tag}></p>`,
  );
}
for (const key of ["link", "constructor", "__proto__"]) {
  const link = block("a", "", {
    markDefs: [
      { _type: "link", _key: key, href: "https://example.org/?a=1&b=2" },
    ],
    children: [{ _type: "span", _key: "s", text: "Go", marks: [key] }],
  });
  assert.equal(
    render([link]),
    '<p><a href="https://example.org/?a=1&amp;b=2" rel="noopener noreferrer">Go</a></p>',
  );
  for (const href of [
    "javascript:alert(1)",
    "//attacker.invalid",
    "data:text/html,x",
    'https://example.org/" onclick=alert(1)',
  ]) {
    assert.throws(
      () =>
        render([{ ...link, markDefs: [{ _type: "link", _key: key, href }] }]),
      /invalid_public_editorial/,
    );
  }
}
for (const body of [
  [{ _type: "html", html: "<script>bad</script>" }],
  [block("a", "Bad", { style: "script" })],
  [block("a", "Bad", { onclick: "bad" })],
])
  assert.throws(() => render(body), /invalid_public_editorial/);
console.log(
  "editorial-html: escaping, supported styles/marks, nested lists, prototype-like link keys and unsafe markup/URL rejection passed",
);
