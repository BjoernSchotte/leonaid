import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const distRoot = path.resolve(import.meta.dirname, "../dist");
const draftMarkers = [
  "/de/_drafts/",
  "/en/_drafts/",
  "Unveröffentlichter Dokumentationsentwurf",
  "Unpublished documentation draft",
];

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
  const relative = decodeURIComponent(pathname).replace(/^\/+/, "");
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
const textFiles = files.filter((file) =>
  /\.(?:html|xml|json|pf_fragment|pf_meta)$/.test(file),
);

for (const file of textFiles) {
  const text = await readFile(path.join(distRoot, file), "utf8");
  for (const marker of draftMarkers) {
    if (text.includes(marker))
      errors.push(`${file}: published output contains draft marker ${marker}`);
  }
}

for (const relative of files.filter((file) => file.endsWith(".html"))) {
  const source = path.join(distRoot, relative);
  const html = await readFile(source, "utf8");
  const base = `https://docs.leonaid.invalid${routeForHtml(relative)}`;
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
  "sitemap-index.xml",
  "pagefind/pagefind.js",
]) {
  if (!files.includes(required))
    errors.push(`missing required build output ${required}`);
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
    `docs-build-output: OK: ${files.length} allowlisted static files; routes, anchors, assets, search, sitemap and draft exclusion valid`,
  );
}
