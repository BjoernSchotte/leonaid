import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const defaultDocsRoot = path.resolve(
  import.meta.dirname,
  "../src/content/docs",
);

async function files(directory) {
  const entries = await Array.fromAsync(
    new Bun.Glob("**/*.{md,mdx}").scan({ cwd: directory }),
  );
  return entries.map((entry) => path.join(directory, entry));
}

export async function checkUrl(url, { attempts = 3, timeoutMs = 10_000 } = {}) {
  let last = { category: "temporary", detail: "not attempted", url };
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      let response = await fetch(url, {
        method: "HEAD",
        redirect: "follow",
        signal: controller.signal,
        headers: { "user-agent": "LeonAid-docs-link-check/1" },
      });
      if (response.status === 405 || response.status === 501) {
        response = await fetch(url, {
          method: "GET",
          redirect: "follow",
          signal: controller.signal,
          headers: {
            range: "bytes=0-0",
            "user-agent": "LeonAid-docs-link-check/1",
          },
        });
      }
      if (response.ok || response.status === 206) {
        return {
          category: "ok",
          detail: `HTTP ${response.status}`,
          url,
          attempts: attempt,
        };
      }
      if (
        response.status === 408 ||
        response.status === 425 ||
        response.status === 429 ||
        response.status >= 500
      ) {
        last = {
          category: "temporary",
          detail: `HTTP ${response.status}`,
          url,
          attempts: attempt,
        };
      } else {
        return {
          category: "permanent",
          detail: `HTTP ${response.status}`,
          url,
          attempts: attempt,
        };
      }
    } catch (error) {
      last = {
        category: "temporary",
        detail: error.name === "AbortError" ? "timeout" : error.message,
        url,
        attempts: attempt,
      };
    } finally {
      clearTimeout(timer);
    }
    if (attempt < attempts) await Bun.sleep(250 * attempt);
  }
  return last;
}

async function urlsFromDocs(directory) {
  const urls = new Set();
  for (const file of await files(directory)) {
    const text = await readFile(file, "utf8");
    for (const match of text.matchAll(/https?:\/\/[^\s)>'"]+/g)) {
      urls.add(match[0].replace(/[.,;:]$/, ""));
    }
  }
  return [...urls].sort();
}

async function main() {
  const listIndex = process.argv.indexOf("--url-list");
  const rootIndex = process.argv.indexOf("--docs-root");
  const urls =
    listIndex === -1
      ? await urlsFromDocs(
          rootIndex === -1
            ? defaultDocsRoot
            : path.resolve(process.argv[rootIndex + 1]),
        )
      : (await readFile(path.resolve(process.argv[listIndex + 1]), "utf8"))
          .split(/\r?\n/)
          .map((url) => url.trim())
          .filter(Boolean);

  const results = [];
  for (const url of urls) results.push(await checkUrl(url));
  for (const result of results) {
    console.log(
      `${result.category.toUpperCase()}: ${result.url} (${result.detail}; attempts=${result.attempts})`,
    );
  }
  const permanent = results.filter((result) => result.category === "permanent");
  const temporary = results.filter((result) => result.category === "temporary");
  if (permanent.length) process.exitCode = 1;
  else if (temporary.length) process.exitCode = 2;
  else console.log(`docs-external-links: OK: ${results.length} URLs`);
}

if (import.meta.main) await main();
