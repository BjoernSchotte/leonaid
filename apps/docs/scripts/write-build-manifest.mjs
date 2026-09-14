import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { validateContent } from "./check-content.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(projectRoot, "../..");
const distRoot = path.join(projectRoot, "dist");
const docsRoot = path.join(projectRoot, "src/content/docs");
const inventory = path.join(
  repositoryRoot,
  "specs/multilingual-documentation/CONTENT-INVENTORY.md",
);
const generatedReference = path.join(
  projectRoot,
  "src/generated/openapi-reference.json",
);

const sourceSha = process.env.LEONAID_DOCS_REVISION ?? "development";
const artifactId =
  process.env.LEONAID_DOCS_ARTIFACT_ID ?? `local-${sourceSha.slice(0, 12)}`;
const builtAt = process.env.LEONAID_DOCS_BUILT_AT ?? new Date().toISOString();
const siteUrl =
  process.env.LEONAID_DOCS_SITE_URL ?? "https://docs.leonaid.invalid";
const basePath = (process.env.LEONAID_DOCS_BASE_PATH ?? "").replace(/\/+$/, "");

if (!/^([0-9a-f]{40}|development)$/.test(sourceSha)) {
  throw new Error(
    "LEONAID_DOCS_REVISION must be a full Git SHA or development",
  );
}
if (!/^\d{4}-\d{2}-\d{2}T/.test(builtAt) || Number.isNaN(Date.parse(builtAt))) {
  throw new Error("LEONAID_DOCS_BUILT_AT must be an ISO-8601 timestamp");
}
if (new URL(siteUrl).pathname !== "/") {
  throw new Error("LEONAID_DOCS_SITE_URL must contain only the site origin");
}
if (basePath && !/^\/[a-z0-9/-]+$/.test(basePath)) {
  throw new Error("LEONAID_DOCS_BASE_PATH must be an absolute URL path");
}

const validation = await validateContent({ docsRoot, inventory });
if (validation.errors.length) {
  throw new Error(
    `cannot create manifest for invalid content: ${validation.errors.join("; ")}`,
  );
}

const files = await Array.fromAsync(
  new Bun.Glob("**/*").scan({ cwd: distRoot, onlyFiles: true }),
);
files.sort();
const contentHash = createHash("sha256");
for (const file of files) {
  const bytes = await readFile(path.join(distRoot, file));
  contentHash.update(file);
  contentHash.update("\0");
  contentHash.update(bytes);
  contentHash.update("\0");
}

const apiReference = JSON.parse(await readFile(generatedReference, "utf8"));
const germanPages = validation.published
  .filter((document) => document.locale === "de")
  .sort((left, right) => left.data.docId.localeCompare(right.data.docId));
const documentedProductRevisions = [
  ...new Set(germanPages.map((document) => document.data.verifiedAgainst)),
].sort();

const manifest = {
  schemaVersion: 1,
  artifactId,
  builtAt: new Date(builtAt).toISOString(),
  sourceSha,
  contentSha256: contentHash.digest("hex"),
  hosting: {
    siteUrl,
    basePath,
    publicUrl: `${siteUrl.replace(/\/$/, "")}${basePath}/`,
  },
  documentation: {
    defaultLocale: "de",
    locales: ["de", "en"],
    publishedPages: validation.published.length,
    languagePairs: germanPages.length,
    documentedProductRevisions,
    revisions: Object.fromEntries(
      germanPages.map((document) => [
        document.data.docId,
        document.data.contentRevision,
      ]),
    ),
  },
  api: {
    openapi: apiReference.contract.openapi,
    sha256: apiReference.contract.sha256,
    version: apiReference.contract.version,
  },
};

await writeFile(
  path.join(distRoot, "build-manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
  "utf8",
);
console.log(
  `docs-build-manifest: OK: ${artifactId}, source=${sourceSha}, content=${manifest.contentSha256}`,
);
