import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";
import { checkUrl } from "./check-external-links.mjs";
import { validateContent } from "./check-content.mjs";
import { isAllowedOutput } from "./output-contract.mjs";

const inventory = path.resolve(
  import.meta.dirname,
  "../../../specs/multilingual-documentation/CONTENT-INVENTORY.md",
);

function frontmatter({
  docId = "DOC-P010",
  contentRevision = 1,
  reviewedRevision = contentRevision,
  draft = false,
} = {}) {
  return `---
title: Fixture
description: A fixture with enough description text for the schema contract.
${draft ? "draft: true\n" : ""}docId: ${docId}
audience: [user]
diataxis: explanation
contentRevision: ${contentRevision}
reviewedRevision: ${reviewedRevision}
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Docs test
---

# Start
`;
}

async function fixtureRoot() {
  return mkdtemp(path.join(tmpdir(), "leonaid-docs-quality-"));
}

async function page(root, locale, body, relative = "user/index.md") {
  const target = path.join(root, locale, relative);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, body);
}

async function expectFailure(name, prepare, message) {
  const root = await fixtureRoot();
  await prepare(root);
  const result = await validateContent({ docsRoot: root, inventory });
  if (!result.errors.some((error) => error.includes(message))) {
    throw new Error(
      `${name}: expected ${JSON.stringify(message)}, got ${JSON.stringify(result.errors)}`,
    );
  }
  console.log(`docs-quality: expected failure: ${name}`);
}

const valid = await fixtureRoot();
await page(valid, "de", frontmatter());
await page(valid, "en", frontmatter());
await page(
  valid,
  "de",
  frontmatter({ docId: "DOC-P999", draft: true }),
  "_drafts/only-de.md",
);
let result = await validateContent({ docsRoot: valid, inventory });
if (result.errors.length)
  throw new Error(`valid fixture failed: ${result.errors.join("; ")}`);
if (result.published.length !== 2 || result.documents.length !== 3) {
  throw new Error("draft fixture was not excluded from published pair checks");
}

await expectFailure(
  "missing translation",
  async (root) => page(root, "de", frontmatter()),
  "missing published en translation",
);
await expectFailure(
  "stale reviewed revision",
  async (root) => {
    await page(
      root,
      "de",
      frontmatter({ contentRevision: 2, reviewedRevision: 2 }),
    );
    await page(
      root,
      "en",
      frontmatter({ contentRevision: 2, reviewedRevision: 1 }),
    );
  },
  "reviewedRevision 1 does not match contentRevision 2",
);
await expectFailure(
  "broken anchor",
  async (root) => {
    await page(root, "de", `${frontmatter()}\n[Kaputt](/de/user/#missing)\n`);
    await page(root, "en", frontmatter());
  },
  "missing anchor /de/user/#missing",
);

let transientAttempts = 0;
const server = createServer((request, response) => {
  if (request.url === "/transient" && transientAttempts++ < 2) {
    response.writeHead(503).end();
  } else if (request.url === "/missing") {
    response.writeHead(404).end();
  } else {
    response.writeHead(200).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
const retry = await checkUrl(`http://127.0.0.1:${address.port}/transient`);
const missing = await checkUrl(`http://127.0.0.1:${address.port}/missing`);
await new Promise((resolve, reject) =>
  server.close((error) => (error ? reject(error) : resolve())),
);
if (retry.category !== "ok" || retry.attempts !== 3)
  throw new Error("temporary retry contract failed");
if (missing.category !== "permanent" || missing.attempts !== 1) {
  throw new Error("permanent link failure classification failed");
}

for (const file of [
  "build-manifest.json",
  "de/ops/index.html",
  "_astro/site.abc123.css",
  "pagefind/fragment/de_abc123.pf_fragment",
]) {
  if (!isAllowedOutput(file))
    throw new Error(`expected allowlisted output: ${file}`);
}
for (const file of [
  "private-build-canary.txt",
  "repository.env",
  "_astro/debug.js.map",
  "de/_drafts/not-published/index.html",
]) {
  if (isAllowedOutput(file))
    throw new Error(`unexpected allowlisted output: ${file}`);
}

console.log(
  "docs-quality: OK: parity, revision, anchor, draft, output allowlist and external retry contracts",
);
