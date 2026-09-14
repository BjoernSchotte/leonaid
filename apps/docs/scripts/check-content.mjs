import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import GithubSlugger from "github-slugger";
import { load as loadYaml } from "js-yaml";

const projectRoot = path.resolve(import.meta.dirname, "..");
const defaultDocsRoot = path.join(projectRoot, "src/content/docs");
const defaultInventory = path.resolve(
  projectRoot,
  "../../specs/multilingual-documentation/CONTENT-INVENTORY.md",
);
const locales = ["de", "en"];

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index === -1 ? fallback : path.resolve(process.argv[index + 1]);
}

async function markdownFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await markdownFiles(candidate)));
    if (entry.isFile() && /\.mdx?$/.test(entry.name)) files.push(candidate);
  }
  return files.sort();
}

function parseDocument(file, text, docsRoot) {
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!match) throw new Error(`${file}: missing YAML frontmatter`);
  const data = loadYaml(match[1]);
  if (!data || typeof data !== "object") {
    throw new Error(`${file}: frontmatter must be an object`);
  }
  const relative = path.relative(docsRoot, file).split(path.sep).join("/");
  const [locale, ...rest] = relative.split("/");
  if (!locales.includes(locale)) {
    throw new Error(`${relative}: expected a de/ or en/ locale directory`);
  }
  const pairPath = rest.join("/");
  const routeParts = pairPath.replace(/\.mdx?$/, "").split("/");
  if (routeParts.at(-1) === "index") routeParts.pop();
  const route = `/${locale}/${routeParts.length ? `${routeParts.join("/")}/` : ""}`;
  return {
    data,
    file,
    locale,
    pairPath,
    route,
    body: text.slice(match[0].length),
  };
}

function headings(body) {
  const slugger = new GithubSlugger();
  const result = new Set();
  let fenced = false;
  for (const line of body.split(/\r?\n/)) {
    if (/^\s*```/.test(line)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    const match = line.match(/^#{1,6}\s+(.+?)\s*#*$/);
    if (!match) continue;
    const plain = match[1]
      .replace(/<[^>]+>/g, "")
      .replace(/[`*_~]/g, "")
      .trim();
    result.add(slugger.slug(plain));
  }
  return result;
}

function collectFrontmatterLinks(value, result = []) {
  if (Array.isArray(value)) {
    for (const entry of value) collectFrontmatterLinks(entry, result);
  } else if (value && typeof value === "object") {
    for (const [key, entry] of Object.entries(value)) {
      if ((key === "link" || key === "href") && typeof entry === "string") {
        result.push(entry);
      } else {
        collectFrontmatterLinks(entry, result);
      }
    }
  }
  return result;
}

function links(document) {
  const withoutFences = document.body.replace(/```[\s\S]*?```/g, "");
  const result = collectFrontmatterLinks(document.data);
  for (const match of withoutFences.matchAll(
    /\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g,
  )) {
    result.push(match[1]);
  }
  for (const match of withoutFences.matchAll(
    /\b(?:href|link)=["']([^"']+)["']/g,
  )) {
    result.push(match[1]);
  }
  return [...new Set(result)];
}

function normalizedRoute(pathname) {
  if (pathname === "/") return pathname;
  const extension = path.posix.extname(pathname);
  return extension || pathname.endsWith("/") ? pathname : `${pathname}/`;
}

function comparable(value) {
  return JSON.stringify(value);
}

export async function validateContent({ docsRoot, inventory }) {
  const errors = [];
  const inventoryText = await readFile(inventory, "utf8");
  const inventoryIds = new Set(
    [...inventoryText.matchAll(/^\| (DOC-P\d{3}) \|/gm)].map(
      (match) => match[1],
    ),
  );
  const documents = [];
  for (const file of await markdownFiles(docsRoot)) {
    try {
      documents.push(
        parseDocument(file, await readFile(file, "utf8"), docsRoot),
      );
    } catch (error) {
      errors.push(error.message);
    }
  }

  const published = documents.filter(
    (document) => document.data.draft !== true,
  );
  const byRoute = new Map(
    published.map((document) => [document.route, document]),
  );
  const byPair = new Map();
  const idsByLocale = new Map(locales.map((locale) => [locale, new Map()]));

  for (const document of published) {
    const relative = `${document.locale}/${document.pairPath}`;
    const id = document.data.docId;
    if (!inventoryIds.has(id))
      errors.push(`${relative}: ${id} is missing from CONTENT-INVENTORY.md`);
    const existingId = idsByLocale.get(document.locale).get(id);
    if (existingId)
      errors.push(`${relative}: duplicate ${id}; first used by ${existingId}`);
    else idsByLocale.get(document.locale).set(id, relative);

    const pair = byPair.get(document.pairPath) ?? {};
    pair[document.locale] = document;
    byPair.set(document.pairPath, pair);

    if (document.data.reviewedRevision !== document.data.contentRevision) {
      errors.push(
        `${relative}: reviewedRevision ${document.data.reviewedRevision} does not match contentRevision ${document.data.contentRevision}`,
      );
    }
  }

  for (const [pairPath, pair] of byPair) {
    for (const locale of locales) {
      if (!pair[locale])
        errors.push(`${pairPath}: missing published ${locale} translation`);
    }
    if (!pair.de || !pair.en) continue;
    for (const field of [
      "docId",
      "audience",
      "diataxis",
      "contentRevision",
      "reviewedRevision",
      "verifiedAgainst",
    ]) {
      if (comparable(pair.de.data[field]) !== comparable(pair.en.data[field])) {
        errors.push(`${pairPath}: de/en ${field} values differ`);
      }
    }
  }

  for (const document of published) {
    const currentHeadings = headings(document.body);
    for (const link of links(document)) {
      if (/^(?:https?:|mailto:|tel:|data:)/.test(link)) continue;
      let target;
      try {
        target = new URL(link, `https://docs.leonaid.invalid${document.route}`);
      } catch {
        errors.push(
          `${document.locale}/${document.pairPath}: invalid link ${link}`,
        );
        continue;
      }
      const targetRoute = normalizedRoute(decodeURI(target.pathname));
      if (targetRoute === "/") continue;
      const targetLocale = targetRoute.split("/")[1];
      if (!locales.includes(targetLocale)) {
        errors.push(
          `${document.locale}/${document.pairPath}: unscoped internal link ${link}`,
        );
        continue;
      }
      if (
        targetLocale !== document.locale &&
        !(
          document.data.docId === "DOC-P001" &&
          targetRoute === `/${targetLocale}/`
        )
      ) {
        errors.push(
          `${document.locale}/${document.pairPath}: cross-locale link ${link}`,
        );
      }
      const targetDocument = byRoute.get(targetRoute);
      if (!targetDocument) {
        errors.push(
          `${document.locale}/${document.pairPath}: missing route ${targetRoute}`,
        );
        continue;
      }
      if (target.hash) {
        const anchor = decodeURIComponent(target.hash.slice(1));
        const targetHeadings =
          targetDocument === document
            ? currentHeadings
            : headings(targetDocument.body);
        if (!targetHeadings.has(anchor)) {
          errors.push(
            `${document.locale}/${document.pairPath}: missing anchor ${targetRoute}#${anchor}`,
          );
        }
      }
    }
  }

  return { documents, errors, published };
}

async function main() {
  const docsRoot = option("--docs-root", defaultDocsRoot);
  const inventory = option("--inventory", defaultInventory);
  const result = await validateContent({ docsRoot, inventory });
  if (result.errors.length) {
    console.error(`docs-content: FAILED (${result.errors.length})`);
    for (const error of result.errors) console.error(`- ${error}`);
    process.exitCode = 1;
    return;
  }
  console.log(
    `docs-content: OK: ${result.published.length} published pages, ${result.documents.length - result.published.length} drafts, de/en pairs and links valid`,
  );
}

if (import.meta.main) await main();
