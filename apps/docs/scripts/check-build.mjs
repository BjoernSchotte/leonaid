import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { isAllowedOutput } from "./output-contract.mjs";

const distRoot = path.resolve(import.meta.dirname, "../dist");
const draftMarkers = [
  "/de/_drafts/",
  "/en/_drafts/",
  "Unveröffentlichter Dokumentationsentwurf",
  "Unpublished documentation draft",
];
const canaryPath = path.resolve(
  import.meta.dirname,
  "../tests/fixtures/private-build-canary.txt",
);
const basePath = (process.env.LEONAID_DOCS_BASE_PATH ?? "").replace(/\/+$/, "");
const siteUrl =
  process.env.LEONAID_DOCS_SITE_URL ?? "https://docs.leonaid.invalid";

async function outputFiles() {
  return Array.fromAsync(
    new Bun.Glob("**/*").scan({ cwd: distRoot, onlyFiles: true }),
  );
}

function routeForHtml(relative) {
  if (relative === "index.html") return "/";
  return `/${relative.replace(/\/index\.html$/, "/")}`;
}

function fileForPath(pathname) {
  let normalized = decodeURIComponent(pathname);
  if (
    basePath &&
    (normalized === basePath || normalized.startsWith(`${basePath}/`))
  ) {
    normalized = normalized.slice(basePath.length) || "/";
  }
  const relative = normalized.replace(/^\/+/, "");
  if (!relative || relative.endsWith("/") || !path.extname(relative))
    return path.join(distRoot, relative, "index.html");
  return path.join(distRoot, relative);
}

async function exists(file) {
  try {
    return (await stat(file)).isFile();
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

function localUrls(html) {
  return [...html.matchAll(/\b(?:href|src)=(?:"([^"]+)"|'([^']+)')/g)].map(
    (match) => match[1] ?? match[2],
  );
}

function anchors(html) {
  return new Set(
    [...html.matchAll(/\bid=(?:"([^"]+)"|'([^']+)')/g)].map(
      (match) => match[1] ?? match[2],
    ),
  );
}

const errors = [];
const files = await outputFiles();
const unexpected = files.filter((file) => !isAllowedOutput(file));
for (const file of unexpected)
  errors.push(`output is not allowlisted: ${file}`);

const canary = (await readFile(canaryPath, "utf8")).trim();
const textFiles = files.filter((file) =>
  /\.(?:html|xml|json|pf_fragment|pf_meta)$/.test(file),
);

for (const file of textFiles) {
  const text = await readFile(path.join(distRoot, file), "utf8");
  for (const marker of draftMarkers) {
    if (text.includes(marker))
      errors.push(`${file}: published output contains draft marker ${marker}`);
  }
  if (text.includes(canary)) {
    errors.push(`${file}: private build canary leaked into published output`);
  }
}

for (const relative of files.filter((file) => file.endsWith(".html"))) {
  const source = path.join(distRoot, relative);
  const html = await readFile(source, "utf8");
  const base = `https://docs.leonaid.invalid${basePath}${routeForHtml(relative)}`;
  for (const raw of localUrls(html)) {
    if (/^(?:https?:|mailto:|tel:|data:|javascript:)/.test(raw)) continue;
    const target = new URL(raw, base);
    if (target.origin !== "https://docs.leonaid.invalid") continue;
    const targetFile = fileForPath(target.pathname);
    if (
      !targetFile.startsWith(`${distRoot}${path.sep}`) &&
      targetFile !== path.join(distRoot, "index.html")
    ) {
      errors.push(`${relative}: output link leaves dist: ${raw}`);
      continue;
    }
    if (!(await exists(targetFile))) {
      errors.push(
        `${relative}: missing built route or asset ${target.pathname}`,
      );
      continue;
    }
    if (target.hash && targetFile.endsWith(".html")) {
      const targetHtml =
        targetFile === source ? html : await readFile(targetFile, "utf8");
      const anchor = decodeURIComponent(target.hash.slice(1));
      if (!anchors(targetHtml).has(anchor)) {
        errors.push(
          `${relative}: missing built anchor ${target.pathname}#${anchor}`,
        );
      }
    }
  }
}

for (const required of [
  "de/index.html",
  "en/index.html",
  "build-manifest.json",
  "robots.txt",
  "sitemap-index.xml",
  "pagefind/pagefind.js",
]) {
  if (!files.includes(required))
    errors.push(`missing required build output ${required}`);
}

if (siteUrl !== "https://docs.leonaid.invalid") {
  const publicRoot = `${siteUrl.replace(/\/$/, "")}${basePath}`;
  for (const locale of ["de", "en"]) {
    const html = await readFile(
      path.join(distRoot, locale, "index.html"),
      "utf8",
    );
    if (!html.includes(`rel="canonical" href="${publicRoot}/${locale}/"`)) {
      errors.push(`${locale}/index.html: canonical URL is invalid`);
    }
    for (const alternate of ["de", "en"]) {
      if (
        !html.includes(
          `rel="alternate" hreflang="${alternate}" href="${publicRoot}/${alternate}/"`,
        )
      ) {
        errors.push(`${locale}/index.html: missing ${alternate} alternate URL`);
      }
    }
  }
  const robots = await readFile(path.join(distRoot, "robots.txt"), "utf8");
  if (!robots.includes(`Sitemap: ${publicRoot}/sitemap-index.xml`)) {
    errors.push("robots.txt does not name the public sitemap");
  }
}

if (files.some((file) => /(?:^|\/)private-build-canary\.txt$/.test(file))) {
  errors.push("private build canary was copied into published output");
}

try {
  const manifest = JSON.parse(
    await readFile(path.join(distRoot, "build-manifest.json"), "utf8"),
  );
  if (manifest.schemaVersion !== 1)
    errors.push("manifest schemaVersion is not 1");
  if (!/^([0-9a-f]{40}|development)$/.test(manifest.sourceSha ?? "")) {
    errors.push("manifest sourceSha is invalid");
  }
  if (!/^[0-9a-f]{64}$/.test(manifest.contentSha256 ?? "")) {
    errors.push("manifest contentSha256 is invalid");
  }
  if (manifest.hosting?.basePath !== basePath) {
    errors.push("manifest basePath does not match the build configuration");
  }
  if (manifest.hosting?.siteUrl !== siteUrl) {
    errors.push("manifest siteUrl does not match the build configuration");
  }
  if (
    manifest.hosting?.publicUrl !==
    `${manifest.hosting?.siteUrl?.replace(/\/$/, "")}${basePath}/`
  ) {
    errors.push("manifest publicUrl is invalid");
  }
  if (manifest.documentation?.locales?.join(",") !== "de,en") {
    errors.push("manifest locales are not de,en");
  }
  if (manifest.documentation?.publishedPages !== 62) {
    errors.push("manifest does not contain all 62 published language pages");
  }
  if (!/^[0-9a-f]{64}$/.test(manifest.api?.sha256 ?? "")) {
    errors.push("manifest OpenAPI SHA is invalid");
  }
} catch (error) {
  errors.push(`build-manifest.json is invalid: ${error.message}`);
}

for (const forbidden of [
  "de/_drafts/not-published/index.html",
  "en/_drafts/not-published/index.html",
]) {
  if (files.includes(forbidden))
    errors.push(`draft has a direct route: ${forbidden}`);
}

if (errors.length) {
  console.error(`docs-build-output: FAILED (${errors.length})`);
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log(
    `docs-build-output: OK: ${files.length} allowlisted static files; manifest, routes, anchors, assets, search, sitemap, canary and draft exclusion valid`,
  );
}
