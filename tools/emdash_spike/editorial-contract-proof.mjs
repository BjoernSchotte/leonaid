import assert from "node:assert/strict";
import { validCampaignEditorial } from "../../apps/campaign-site/src/auth/campaign-editorial.mjs";

const span = { _type: "span", _key: "span", text: "Text", marks: [] };
const block = {
  _type: "block",
  _key: "block",
  style: "normal",
  markDefs: [],
  children: [span],
};
const valid = { title: "Campaign", body: [block] };
assert.equal(validCampaignEditorial(valid), true);
let rejected = 0;
const deny = (data) => {
  assert.equal(validCampaignEditorial(data), false);
  rejected++;
};
// Published native editor serializes absent empty marks/markDefs. Validate
// their meaning directly; never normalize away unknown or malformed data.
const { marks: _marks, ...plainSpan } = span;
const { markDefs: _definitions, ...plainBlock } = block;
for (const children of [[plainSpan], [{ ...span, marks: ["strong"] }]]) {
  assert.equal(
    validCampaignEditorial({ ...valid, body: [{ ...plainBlock, children }] }),
    true,
  );
}
for (const candidate of [
  { ...plainBlock, markDefs: null },
  { ...plainBlock, children: [{ ...span, marks: null }] },
  { ...plainBlock, children: [{ ...span, marks: "strong" }] },
  { ...plainBlock, children: [{ ...span, marks: ["unregistered"] }] },
  {
    ...plainBlock,
    children: [{ ...plainSpan, html: "<script>unsafe()</script>" }],
  },
])
  deny({ ...valid, body: [candidate] });
for (const [field, limit] of Object.entries({
  title: 400,
  hero_title: 180,
  hero_summary: 1200,
  seo_description: 320,
})) {
  assert.equal(
    validCampaignEditorial({ title: "Campaign", [field]: "x".repeat(limit) }),
    true,
  );
  deny({ title: "Campaign", [field]: "x".repeat(limit + 1) });
}
for (const [field, limit, item] of [
  ["body", 60, block],
  ["faq", 20, { question: "Question", answer: "Answer" }],
  ["partners", 30, { name: "Partner" }],
]) {
  const rows = (length) =>
    Array.from({ length }, (_, index) => ({ ...item, _key: `row-${index}` }));
  assert.equal(
    validCampaignEditorial({ title: "Campaign", [field]: rows(limit) }),
    true,
  );
  deny({ title: "Campaign", [field]: rows(limit + 1) });
}
for (const candidate of [
  { ...block, _type: "html", html: "<script>unsafe()</script>" },
  { ...block, style: "script" },
  { ...block, level: 4 },
  { ...block, children: [span, span] },
  { ...block, children: [{ ...span, text: "x".repeat(4001) }] },
  { ...block, children: [{ ...span, marks: ["unregistered"] }] },
  {
    ...block,
    children: Array.from({ length: 101 }, (_, index) => ({
      ...span,
      _key: `s-${index}`,
    })),
  },
  { ...block, markDefs: [{ _type: "custom", _key: "mark" }] },
])
  deny({ ...valid, body: [candidate] });
deny({ ...valid, body: [block, block] });
for (const href of [
  "javascript:alert(1)",
  "data:text/html,unsafe",
  "http://example.invalid",
  "//example.invalid",
  "/\\example.invalid",
  "https://user:secret@example.invalid",
  "https://example.invalid/\nunsafe",
]) {
  deny({ ...valid, partners: [{ name: "Partner", website: href }] });
  deny({
    ...valid,
    body: [{ ...block, markDefs: [{ _type: "link", _key: "link", href }] }],
  });
}
for (const website of [
  "https://example.invalid/partner",
  "/campaigns/example/",
  "",
]) {
  assert.equal(
    validCampaignEditorial({
      ...valid,
      partners: [{ name: "Partner", website }],
    }),
    true,
  );
}
for (const data of [
  { ...valid, price: 1 },
  { ...valid, hero_image: { id: "unscoped" } },
  { ...valid, theme: "custom" },
  { ...valid, faq: [{ question: "Question", answer: "Answer", price: 1 }] },
  { ...valid, faq: [{ question: "x".repeat(301), answer: "Answer" }] },
  { ...valid, faq: [{ question: "Question", answer: "x".repeat(2401) }] },
  { ...valid, partners: [{ name: "x".repeat(201) }] },
  { ...valid, partners: [{ name: "Partner", description: "x".repeat(801) }] },
  {
    ...valid,
    body: Array.from({ length: 20 }, (_, index) => ({
      ...block,
      _key: `large-${index}`,
      children: [{ ...span, text: "x".repeat(4000) }],
    })),
  },
])
  deny(data);
console.log(
  `editorial-contract: OK: exact limits accepted; ${rejected} oversized, executable, unknown and unsafe nested inputs rejected`,
);
